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


# ----------------------------------------------------------------------
# 题库加载 + Q矩阵（带缓存，1220题不大，进程内常驻即可）
# ----------------------------------------------------------------------
_question_index: Optional[dict] = None
_q_matrix_cache: dict = {}


def _load_questions() -> dict:
    global _question_index
    if _question_index is None:
        with open(QUESTION_BANK_PATH, "r", encoding="utf-8") as f:
            questions = json.load(f)
        _question_index = {q["id"]: q for q in questions}
    return _question_index


def get_q_matrix(question_id: str) -> list:
    """返回某道题对应的知识点ID列表（可能不止一个）。缓存，避免每次答题都重新调分类。

    分类逻辑走 llm_client.classify_knowledge_points_llm()——配了真实API key时是LLM语义分类
    （参考Dialogue-KT论文的"LLM打KC标签"思路），没配key时自动降级成关键词匹配，两种情况
    调用方都不用关心，接口形状不变。
    """
    if question_id in _q_matrix_cache:
        return _q_matrix_cache[question_id]
    questions = _load_questions()
    q = questions.get(question_id)
    if not q:
        _q_matrix_cache[question_id] = []
        return []
    kps = classify_knowledge_points_llm(q.get("stem", ""))
    kp_ids = [kp.id for kp in kps]
    # 兜底：多标签分类没命中时，退回题库原有的单标签 knowledge_point_id（parse_question_bank.py 打的）
    if not kp_ids and q.get("knowledge_point_id"):
        kp_ids = [q["knowledge_point_id"]]
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
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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
