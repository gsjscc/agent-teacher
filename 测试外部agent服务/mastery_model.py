#!/usr/bin/env python3
"""
表B「学生掌握度画像表」更新规则 v2/v3 的实现：CDM（Q矩阵，多知识点）+ IRT简化版（Elo在线更新）
+ 遗忘曲线（读时动态衰减）。

对应 [执行计划.md] 3.x 的讨论结论，落地方式：
  - CDM（v2）：一道题可能同时考察多个知识点，用 knowledge_base.classify_knowledge_points_multi()
    对题干重新打标，得到 Q矩阵（question_id -> [knowledge_point_id, ...]），不用EM估计、
    不用重新人工标注，复用题库已有的关键词路由逻辑。
  - IRT简化版（v2）：不做联合MLE/EM估计，改用Elo评分机制——每个(学生,知识点)维护一个能力分，
    每道题维护一个难度分（初始值从题库.json已有的"难易度"字段易/中/难映射而来），答题时
    按标准Elo公式互相更新，能塞进一次HTTP请求处理，不需要批量训练。
  - 遗忘曲线（v3）：不用FSRS/HLR那种要拟合参数的模型，用艾宾浩斯简化公式 R(t)=e^(-t/S)，
    S（记忆稳定性）按当前掌握状态给固定值，不需要训练样本。**不持久化衰减结果、不用定时任务
    批量刷新**——只在 get_profile() 读表B时用"距最近一次更新的天数"现算，跟这个模块"读时计算，
    不额外写回"的既有设计（Elo也是这个原则）保持一致。同时提供 get_due_for_review()，
    借用SM-2"该不该提醒复习"的判断逻辑，给触发器/车道C复习推送用。

没有真实数据库（执行计划.md 3.4已确认【数据源→添加表单】不能自建表），这里用本地JSON
文件模拟表B的持久化，字段设计对齐 教学智能体方案讨论.md 9.5 的表B schema，
后续接【资源管理→插件】自建HTTP API时，把这里的读写换成真表的读写即可，接口形状不用变。
"""

import json
import math
import os
import tempfile
import threading
import time
from typing import Optional

from knowledge_base import KNOWLEDGE_POINTS
from llm_client import classify_knowledge_points_llm
from signal_log import record_signal, get_signals

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
QUESTION_BANK_PATH = os.path.join(BASE_DIR, "..", "题库", "题库.json")
STUDENT_MASTERY_PATH = os.path.join(DATA_DIR, "student_mastery.json")  # 表B
ITEM_RATING_PATH = os.path.join(DATA_DIR, "item_ratings.json")  # 题目难度分（表B之外的辅助表，不直接暴露给平台）
STUDENT_STYLE_PATH = os.path.join(DATA_DIR, "student_style.json")  # 学生的detail_level/encourage_level偏好，按学生持久化

RATING_DEFAULT = 1500.0
K_STUDENT = 32.0  # 学生能力分变化步长，比题目难度分快，符合"学生水平比题目难度更易变"的直觉
K_ITEM = 8.0

DIFFICULTY_SEED = {"易": 1300.0, "中": 1500.0, "难": 1700.0}

# 非做题类信号（自报/提问/自我解释/可视化探索）没有"题目难度"这个对手可比，
# 用不了Elo的期望值公式，改用9.5原文"简化打分"的思路：固定步长直接加减到rating上。
# 步长取15分，量级上跟一次Elo做题更新（K_STUDENT=32×weight，单知识点题通常整个32分）
# 比起来更温和——这是有意的：一次自报/自我解释的可信度不如一次实际做题的信号强，
# 不应该跟做题信号权重相当，具体数值待9.5待办里说的"跑真实对话样本"后再调。
QUALITATIVE_SIGNAL_STEP = 15.0
POLARITY_DIRECTION = {"正": 1.0, "负": -1.0, "中": 0.0}

# 遗忘曲线：记忆稳定性S（单位：天），按当前（衰减前的）掌握状态给固定值，掌握得越牢固衰减越慢。
# 数值先拍脑袋定，跑一段真实复习间隔数据后如果衰减太快/太慢再调，跟表B的分数阈值是同一个道理。
STABILITY_DAYS_BY_STATE = {"薄弱": 3.0, "学习中": 7.0, "已掌握": 21.0}
REVIEW_RETENTION_THRESHOLD = 0.85  # 预估记忆保持率跌破这个值，判定"该复习了"

_KP_NAME_BY_ID = {kp.id: kp.name for kp in KNOWLEDGE_POINTS}

# server.py 用 ThreadingHTTPServer（同进程多线程），两个学生同时答题时如果都各自
# "读整个表B JSON -> 改内存 -> 整个写回"，后写的那个会把先写的更新覆盖掉（丢失更新问题）。
# 用一把进程内的锁把"读-改-写"整个过程串行化即可解决——不需要引入外部依赖或跨进程文件锁，
# 因为目前就是单进程部署（同一台机器上一个systemd服务），锁的粒度按数据文件区分，
# 避免答题更新和信号写入互相不必要地阻塞。
_mastery_lock = threading.Lock()
# detail_level/encourage_level偏好是单独一个文件（student_style.json），跟表B/题目难度表
# 不是同一份数据、更新频率也低得多（只有学生明确表达风格诉求时才写），用独立的锁而不是复用
# _mastery_lock，避免答题高频写入跟风格偏好这种低频写入互相排队等待。
_style_lock = threading.Lock()


# ----------------------------------------------------------------------
# 题库加载 + Q矩阵（带缓存，1220题不大，进程内常驻即可）
# ----------------------------------------------------------------------
_question_index: Optional[dict] = None
_q_matrix_cache: dict = {}
# get_q_matrix() 的缓存字典是全局共享的、并发下没有天然保护：多个线程第一次同时问同一道题时
# 都会判定"缓存未命中"，都各自发起真实LLM分类请求，谁的网络请求先完成谁的结果就先写进缓存，
# 但完成顺序不确定——如果一次调用因为高并发下超时/网络问题降级成关键词匹配、而这道题在题库里
# 又没有knowledge_point_id兜底字段，就会分类出空列表；空列表一旦被写进缓存就是"一次失败、
# 永久失败"（在压测里实测到：本该更新30次的表B只更新了18次，另外12次全部命中了这个空缓存）。
# 用锁串行化"查缓存->分类->写缓存"，并且只缓存非空结果——分类失败/超时不应该被当成"这题真的
# 没有知识点"钉死下来，下次请求应该有机会重新分类。
_q_matrix_lock = threading.Lock()


def _load_questions() -> dict:
    global _question_index
    if _question_index is None:
        with open(QUESTION_BANK_PATH, "r", encoding="utf-8") as f:
            questions = json.load(f)
        _question_index = {q["id"]: q for q in questions}
    return _question_index


def get_question(question_id: str) -> Optional[dict]:
    """按id查一道题的完整原始数据（stem/options/answer/type等字段），给 quiz.py 出题/判分用。
    公开这个函数是为了不让 quiz.py 直接伸手进来碰 _load_questions()/_question_index 这些
    模块内部实现细节——题库究竟是一次性加载进内存的字典、还是以后换成真数据库查询，
    quiz.py 都不需要关心，接口形状不变。"""
    return _load_questions().get(question_id)


def iter_questions():
    """给 quiz.py 挑题用——返回题库里所有题目的可迭代视图（不是拷贝，调用方不应该修改）。"""
    return _load_questions().values()


def get_q_matrix(question_id: str) -> list:
    """返回某道题对应的知识点ID列表（可能不止一个）。缓存，避免每次答题都重新调分类。

    分类逻辑走 llm_client.classify_knowledge_points_llm()——配了真实API key时是LLM语义分类
    （参考Dialogue-KT论文的"LLM打KC标签"思路），没配key时自动降级成关键词匹配，两种情况
    调用方都不用关心，接口形状不变。
    """
    if question_id in _q_matrix_cache:
        return _q_matrix_cache[question_id]

    with _q_matrix_lock:
        # 双重检查：进锁前的判断只是为了避免每次都抢锁，真正决定"要不要重新分类"的判断
        # 必须在拿到锁之后再做一次——否则多个线程会排队依次重复分类同一道题。
        if question_id in _q_matrix_cache:
            return _q_matrix_cache[question_id]

        questions = _load_questions()
        q = questions.get(question_id)
        if not q:
            # 题库里根本没有这个question_id，这是关于题库内容的静态事实、不会因为重试而改变，
            # 缓存空列表没问题（不同于下面"分类失败"的情况）
            _q_matrix_cache[question_id] = []
            return []

        kps = classify_knowledge_points_llm(q.get("stem", ""))
        kp_ids = [kp.id for kp in kps]
        # 兜底：多标签分类没命中时，退回题库原有的单标签 knowledge_point_id（parse_question_bank.py 打的）
        if not kp_ids and q.get("knowledge_point_id"):
            kp_ids = [q["knowledge_point_id"]]

        # 只缓存非空结果——分类失败/高并发下临时降级判断不出知识点，不代表"这题真的没有知识点"，
        # 不应该被永久钉死；下次请求应该有机会重新分类，直到真的分类出结果才固化进缓存。
        if kp_ids:
            _q_matrix_cache[question_id] = kp_ids
        return kp_ids


def get_question_difficulty_label(question_id: str) -> str:
    questions = _load_questions()
    q = questions.get(question_id)
    return (q or {}).get("difficulty", "中")


# ----------------------------------------------------------------------
# 本地JSON持久化（模拟表B / 题目难度分表，读写接口形状对齐未来真表插件）
# ----------------------------------------------------------------------
def _load_json(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: str, data: dict):
    """原子写入：先写到同目录下的临时文件，再用os.replace()整体换名，而不是直接对目标文件
    open("w")截断重写——后者如果进程在写到一半时被杀（比如systemd重启、断电），会留下一个
    内容被截断的坏JSON文件，下次_load_json直接解析失败断整条链路；os.replace()在同一文件系统
    内是原子操作，要么换成完整的新内容，要么保留原文件，不存在"半写"的中间状态。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _mastery_state(rating: float, n_obs: int) -> str:
    """rating -> 表B的"掌握状态"枚举，阈值以 RATING_DEFAULT=1500 为中心对称，先用固定值，
    不需要标注样本去拟合——跑一段真实数据后如果状态切换太敏感/迟钝，再调这两个阈值。"""
    if n_obs == 0:
        return "未学"
    if rating < 1350:
        return "薄弱"
    if rating < 1650:
        return "学习中"
    return "已掌握"


def _expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def _apply_forgetting_decay(rating: float, n_obs: int, last_updated_ts) -> dict:
    """遗忘曲线：算"如果现在才检测，这个知识点的分/状态大概会衰减成什么样"，
    不改动持久化数据里的rating，只在读的这一刻现算。

    没学过（n_obs==0）没有"忘"这个概念，直接原样返回，retention记1.0。
    """
    raw_state = _mastery_state(rating, n_obs)
    if n_obs == 0 or last_updated_ts is None:
        return {
            "rating": round(rating, 1),
            "mastery_state": raw_state,
            "retention": 1.0,
            "days_since_review": None,
            "needs_review": False,
        }

    days = max(0.0, (time.time() - last_updated_ts) / 86400.0)
    stability = STABILITY_DAYS_BY_STATE.get(raw_state, 7.0)
    retention = math.exp(-days / stability)
    # 衰减往"未观测到的中性基准分"回退，而不是无脑往0掉——距离上次观测越久，
    # 越不确定学生现在到底记不记得，回退到"不确定"比回退到"完全不会"更符合直觉
    decayed_rating = RATING_DEFAULT + (rating - RATING_DEFAULT) * retention

    return {
        "rating": round(decayed_rating, 1),
        "mastery_state": _mastery_state(decayed_rating, n_obs),
        "retention": round(retention, 3),
        "days_since_review": round(days, 1),
        "needs_review": retention < REVIEW_RETENTION_THRESHOLD,
    }


# ----------------------------------------------------------------------
# 核心：一次答题 -> 更新Q矩阵覆盖到的每个知识点的学生能力分 + 该题的难度分
# ----------------------------------------------------------------------
def record_answer(student_id: str, question_id: str, correct: bool) -> dict:
    """记一次作答结果：先写表A（原始信号，signal_type="做题"），再按Elo公式更新表B
    （多知识点）和题目难度分——表B的每次变化都能倒查回表A里"因为哪道题、答对还是答错"。

    correct 由上游（题库自动判分，或车道A/C的judge节点）算好传进来，这里不做判卡逻辑，
    只负责"这个结果该怎么反映到掌握度画像"，职责跟9.5的信号分层设计一致。
    """
    kp_ids = get_q_matrix(question_id)
    if not kp_ids:
        return {"question_id": question_id, "knowledge_points": [], "note": "题目未能匹配到知识点，跳过更新"}

    # 先落表A：一道题可能对应多个知识点（Q矩阵），每个知识点各记一行原始信号
    for kp_id in kp_ids:
        record_signal(
            student_id, kp_id, signal_type="做题",
            polarity="正" if correct else "负",
            evidence=f"题目{question_id}：{'答对' if correct else '答错'}",
        )

    # 整段"读表B+题目难度表 -> 改内存 -> 写回"必须串行化：如果两个学生（或同一学生两次
    # 快速提交）的请求在不同线程里交叉执行，后写的会拿着自己读到的旧版student_mastery整个
    # 覆盖掉，把先写的那次更新冲掉——这不是理论风险，ThreadingHTTPServer确实会并发调这个函数。
    with _mastery_lock:
        item_ratings = _load_json(ITEM_RATING_PATH)
        item_entry = item_ratings.get(question_id)
        if item_entry is None:
            item_entry = {"rating": DIFFICULTY_SEED.get(get_question_difficulty_label(question_id), RATING_DEFAULT), "n": 0}

        student_mastery = _load_json(STUDENT_MASTERY_PATH)
        student_rows = student_mastery.setdefault(student_id, {})

        actual = 1.0 if correct else 0.0
        weight = 1.0 / len(kp_ids)  # Q矩阵按均分权重，避免一题多标签的题目"重复计分"占便宜
        item_expected_values = []
        updated_kps = []

        for kp_id in kp_ids:
            kp_row = student_rows.get(kp_id, {"rating": RATING_DEFAULT, "n": 0, "last_updated": None})
            expected = _expected_score(kp_row["rating"], item_entry["rating"])
            item_expected_values.append(expected)

            kp_row["rating"] = kp_row["rating"] + K_STUDENT * weight * (actual - expected)
            kp_row["n"] = kp_row["n"] + 1
            kp_row["last_updated"] = int(time.time())
            student_rows[kp_id] = kp_row

            updated_kps.append({
                "knowledge_point_id": kp_id,
                "knowledge_point_name": _KP_NAME_BY_ID.get(kp_id, kp_id),
                "rating": round(kp_row["rating"], 1),
                "mastery_state": _mastery_state(kp_row["rating"], kp_row["n"]),
                "n_observations": kp_row["n"],
            })

        # 题目难度分：整题只更新一次（不随Q矩阵重复更新），用各知识点expected的均值做"这题对这个学生的综合预期通过率"
        item_expected = sum(item_expected_values) / len(item_expected_values)
        item_entry["rating"] = item_entry["rating"] - K_ITEM * (actual - item_expected)
        item_entry["n"] = item_entry["n"] + 1
        item_ratings[question_id] = item_entry

        _save_json(STUDENT_MASTERY_PATH, student_mastery)
        _save_json(ITEM_RATING_PATH, item_ratings)

    return {
        "question_id": question_id,
        "correct": correct,
        "item_difficulty_rating": round(item_entry["rating"], 1),
        "knowledge_points": updated_kps,
    }


def record_qualitative_signal(student_id: str, knowledge_point_id: str, signal_type: str,
                               polarity: str, evidence: str = "") -> dict:
    """记一次非做题类信号（自报/提问/自我解释/可视化探索），先写表A，再用固定步长
    （而不是Elo期望值公式）直接调整该知识点的rating——对应9.5"自报已懂+1、自我解释
    不出依据-1"这类简化打分规则，只是把+1/-1的单位换成了跟Elo同量纲的rating分。

    车道B（主动学习）/车道D（可视化探索）之前完全不产生数据，就是靠这个接口接入
    统一的表A/表B，不需要每条车道自己另外维护一套判断逻辑。
    """
    if signal_type == "做题":
        raise ValueError("做题类信号请用 record_answer()，需要题目难度信息走Elo更新")

    signal_row = record_signal(student_id, knowledge_point_id, signal_type, polarity, evidence)
    effective_polarity = signal_row["effective_polarity"]
    delta = POLARITY_DIRECTION[effective_polarity] * QUALITATIVE_SIGNAL_STEP

    with _mastery_lock:
        student_mastery = _load_json(STUDENT_MASTERY_PATH)
        student_rows = student_mastery.setdefault(student_id, {})
        kp_row = student_rows.get(knowledge_point_id, {"rating": RATING_DEFAULT, "n": 0, "last_updated": None})
        kp_row["rating"] = kp_row["rating"] + delta
        kp_row["n"] = kp_row["n"] + 1
        kp_row["last_updated"] = int(time.time())
        student_rows[knowledge_point_id] = kp_row
        _save_json(STUDENT_MASTERY_PATH, student_mastery)

    return {
        "student_id": student_id,
        "knowledge_point_id": knowledge_point_id,
        "knowledge_point_name": _KP_NAME_BY_ID.get(knowledge_point_id, knowledge_point_id),
        "signal_type": signal_type,
        "polarity": polarity,
        "effective_polarity": effective_polarity,
        "repeated_question": signal_row["repeated_question"],
        "rating": round(kp_row["rating"], 1),
        "mastery_state": _mastery_state(kp_row["rating"], kp_row["n"]),
        "n_observations": kp_row["n"],
    }


def get_profile(student_id: str) -> dict:
    """GET /profile 的数据来源——对应 执行计划.md 里"表B（学生掌握度画像表）"插件读接口。

    每行同时给"raw_rating"（上次实际观测到的分，Elo更新结果，持久化在JSON里那份）和
    "rating"（叠加遗忘曲线衰减后的现算值，共享个性化层/车道读的应该是这个，而不是raw）。
    """
    student_mastery = _load_json(STUDENT_MASTERY_PATH)
    rows = student_mastery.get(student_id, {})
    profile = []
    for kp_id, row in rows.items():
        decayed = _apply_forgetting_decay(row["rating"], row["n"], row.get("last_updated"))
        profile.append({
            "knowledge_point_id": kp_id,
            "knowledge_point_name": _KP_NAME_BY_ID.get(kp_id, kp_id),
            "raw_rating": round(row["rating"], 1),
            "rating": decayed["rating"],
            "mastery_state": decayed["mastery_state"],
            "n_observations": row["n"],
            "last_updated": row.get("last_updated"),
            "days_since_review": decayed["days_since_review"],
            "retention": decayed["retention"],
            "needs_review": decayed["needs_review"],
        })
    profile.sort(key=lambda r: r["rating"])
    return {"student_id": student_id, "knowledge_points": profile}


def format_profile_summary_text(student_id: str) -> str:
    """把get_profile()的结果格式化成一段给LLM看的文本——server.py在生成讲解/兜底回复之前
    都会调这个，喂给llm_client.py里新增的"场景5：范围模糊/依赖个人情况的诉求"判断逻辑用
    （比如"给我列个复习计划"）：模型能直接看到这个学生在**全部**已学知识点上的掌握情况，
    不需要再问学生"你哪里不会"——只有当画像答不了学生问题里真正缺的那部分（比如没写"还有
    多久考试"这类只有学生自己知道的主观信息）时，才应该反问。

    不用student_id（未登录/系统变量没绑定）或者这个学生完全没有学习记录（新学生）时返回
    明确写着"没有数据"的提示，而不是空字符串——让模型清楚知道"这不是没有薄弱点，是压根
    没数据"，避免它误判成"这个学生什么都会"。
    """
    if not student_id:
        return "（没有学生身份信息，无法读取学情画像）"
    profile = get_profile(student_id)["knowledge_points"]
    if not profile:
        return "（该学生目前没有任何学习/答题记录——新学生或数据还没积累起来，无法从画像判断薄弱点）"
    lines = []
    for row in profile:
        tag = "（已到复习节点）" if row["needs_review"] else ""
        lines.append(f"- {row['knowledge_point_name']}：{row['mastery_state']}{tag}")
    return "该学生在已学过的知识点上的掌握情况（未列出的知识点=从没学过，没有数据）：\n" + "\n".join(lines)


# ----------------------------------------------------------------------
# detail_level/encourage_level 偏好——真正的数据源
#
# 之前server.py里这两个字段是`data.get("detail_level", "中")`，也就是从任务流插件节点转发
# 过来的请求体里读——但从来没有任何地方会真的填这个字段，所以永远只能拿到硬编码的默认值"中"，
# 跟"没接真实数据源"是一回事。现在改成：按学生持久化存进student_style.json（跟表B同类的
# 本地JSON文件持久化方式，字段设计对齐提示词库.md"风格调整意图识别节点"一节），由
# detect_style_change_llm()识别到学生明确表达"想要更详细/更简单/更鼓励/更严格直接"时才更新，
# 平时读的都是这个学生自己上一次表达过的真实偏好（或者从没表达过时的默认值"中"），不是
# 猜出来的、也不是请求方随便传一个就能覆盖的。
# ----------------------------------------------------------------------
_STYLE_LEVELS = ["低", "中", "高"]


def _shift_style_level(current: str, change: str, increase_word: str, decrease_word: str) -> str:
    """把"低/中/高"三档按学生表达的变化量（更详细/更简单，或更鼓励/更严格直接）移动一档，
    到顶/到底就不再往外走，不会越界成不存在的档位。current不是这三档之一时（脏数据/首次）
    按"中"处理，不报错断链路。"""
    idx = _STYLE_LEVELS.index(current) if current in _STYLE_LEVELS else 1
    if change == increase_word:
        idx = min(idx + 1, len(_STYLE_LEVELS) - 1)
    elif change == decrease_word:
        idx = max(idx - 1, 0)
    return _STYLE_LEVELS[idx]


def get_style_prefs(student_id: str) -> dict:
    """讲解生成/兜底回复要用的detail_level/encourage_level真正来源。没有student_id
    （访客/系统变量没绑定）或者这个学生从没表达过风格偏好时，返回默认值"中"/"中"——
    默认值本身没问题，问题只在于"永远只能是默认值"，这个函数保证一旦学生表达过就能
    读到真实值。"""
    if not student_id:
        return {"detail_level": "中", "encourage_level": "中"}
    styles = _load_json(STUDENT_STYLE_PATH)
    row = styles.get(student_id, {})
    return {
        "detail_level": row.get("detail_level", "中"),
        "encourage_level": row.get("encourage_level", "中"),
    }


def update_style_prefs(student_id: str, detail_level_change: str, encourage_level_change: str) -> dict:
    """detect_style_change_llm()判断出学生这句话在要求调整讲解方式时调用，把变化量落到
    持久化的档位上并写回。detail_level_change/encourage_level_change取值是"更详细/更简单/
    不变"和"更鼓励/更严格直接/不变"，跟llm_client.py里判断出来的字段值原样对应，这里不
    重新解释语义，只负责"档位怎么挪、挪完存哪"。返回更新后的最新偏好，调用方（server.py）
    可以直接拿去当这一轮student_state的detail_level/encourage_level用，不用再读一次。"""
    if not student_id:
        return {"detail_level": "中", "encourage_level": "中"}
    with _style_lock:
        styles = _load_json(STUDENT_STYLE_PATH)
        row = styles.get(student_id, {"detail_level": "中", "encourage_level": "中"})
        row["detail_level"] = _shift_style_level(row.get("detail_level", "中"), detail_level_change, "更详细", "更简单")
        row["encourage_level"] = _shift_style_level(row.get("encourage_level", "中"), encourage_level_change, "更鼓励", "更严格直接")
        row["last_updated"] = int(time.time())
        styles[student_id] = row
        _save_json(STUDENT_STYLE_PATH, styles)
        return {"detail_level": row["detail_level"], "encourage_level": row["encourage_level"]}


def get_due_for_review(student_id: str) -> dict:
    """借SM-2"该不该提醒复习"的间隔判断思路：从表B里挑出 needs_review=True 的知识点，
    给触发器/车道C复习推送、5.2教师端学情预警用，不用另外维护一张"复习计划表"。
    """
    profile = get_profile(student_id)["knowledge_points"]
    due = [row for row in profile if row["needs_review"]]
    due.sort(key=lambda r: r["retention"])  # 保持率掉得最狠的排前面，最该先复习
    return {"student_id": student_id, "due_for_review": due}


if __name__ == "__main__":
    # 自测：模拟一个学生对几道不同知识点/难度的题连续作答，观察rating和mastery_state怎么变化
    sid = "demo_student"
    questions = _load_questions()
    sample_ids = list(questions.keys())[:5]
    print("样例题目的Q矩阵：")
    for qid in sample_ids:
        print(f"  {qid}: {get_q_matrix(qid)} (难度={get_question_difficulty_label(qid)})")

    print("\n模拟连续答对同一知识点相关的题：")
    for qid in sample_ids:
        result = record_answer(sid, qid, correct=True)
        print(f"  答对 {qid} ->", json.dumps(result, ensure_ascii=False))

    print("\n最终画像（rating已叠加遗忘曲线，raw_rating是Elo原始观测值）：")
    print(json.dumps(get_profile(sid), ensure_ascii=False, indent=2))

    print("\n手动把最近更新时间往前调20天，模拟很久没复习，看衰减和needs_review怎么变：")
    student_mastery = _load_json(STUDENT_MASTERY_PATH)
    for row in student_mastery[sid].values():
        row["last_updated"] -= 20 * 86400
    _save_json(STUDENT_MASTERY_PATH, student_mastery)
    print(json.dumps(get_due_for_review(sid), ensure_ascii=False, indent=2))
