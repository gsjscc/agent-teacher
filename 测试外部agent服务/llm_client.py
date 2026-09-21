#!/usr/bin/env python3
"""
讲解生成 + 媒体决策的 LLM 调用封装。

2026-09-17：从 Anthropic 切换成百度千帆（QIANFAN_API_KEY），因为手头没有 Anthropic key、
千帆 key 已实测可用。千帆 v2 chat/completions 是 OpenAI 兼容格式，调用方（mastery_model.py/
server.py）完全不用感知这层切换——generate_explanation_and_media()/classify_knowledge_points_llm()
两个对外函数签名和降级策略都没变，改的只是 _call_llm() 内部的请求/响应格式。

占位说明：没配 QIANFAN_API_KEY 时自动降级成规则版 MOCK（在 reply 里标出 [MOCK-LLM] 前缀，
避免真跑起来时误以为是真实模型输出）。key 从项目根目录的 .env 文件读取（QIANFAN_API_KEY=xxx
这一行），.env 已加入 .gitignore 不会被提交。

对应提示词库.md 第6/7条模板：这里的 PROMPT_TEMPLATE 就是把那两条模板拼起来的程序化版本。
"""

import json
import os
import re
import urllib.request
import urllib.error


def _load_dotenv():
    """极简 .env 加载器（不引入 python-dotenv 依赖，跟本服务"纯标准库"原则一致）。
    只在对应环境变量还没被设置时才从 .env 补，优先级：真实环境变量 > .env 文件。"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()

from knowledge_base import KnowledgePoint, KNOWLEDGE_POINTS, classify_knowledge_points_multi

QIANFAN_API_KEY = os.environ.get("QIANFAN_API_KEY", "")
QIANFAN_BASE_URL = os.environ.get("QIANFAN_BASE_URL", "https://qianfan.baidubce.com")
QIANFAN_MODEL = os.environ.get("QIANFAN_MODEL", "deepseek-v4-flash")

PROMPT_TEMPLATE = """当前知识点：{knowledge_point}
标准内容/推导依据（供你讲解时参考，不要整段照抄）：
{standard_content}

该学生当前状态：掌握度={mastery_level}，detail_level={detail_level}，encourage_level={encourage_level}
{conversation_context_block}
可用的可视化素材（只能从下面列表里选，不能杜撰不存在的素材）：
{available_media_manifest}

学生这句话原文：
{message}

# 核心原则：强化思维，而非替代思维
不要替学生想。你的价值在于帮学生自己想清楚，而不是给一个正确答案让他抄。任何时候能反问的，优先反问。

# 先判断场景，再决定怎么回应（学生一句话可能同时带多种意图，按最主要的那一种回应）
1. 报错求助（"这题不对""为什么我判断错了"）→ 用分步追问定位卡在哪一步，不要一次性讲完整个知识点
2. 主动学习（"我想学第三章""我对压力角不太懂"）→ 判断是章节级还是知识点级需求，按掌握程度（mastery_level）调整讲解深度和讲法（类比多/公式少 vs 直接上公式推导）
3. 自测复习（"我要复习""考前自测一下"）→ 优先给结构化复习清单，按知识点先修顺序安排
4. 可视化探索（"演示一下""拖动看看"）→ 引导学生动手尝试，观察结果后追问"你看到了什么规律""为什么会这样"，而不是直接告诉答案

# 苏格拉底式引导（每次回应尽量落实，不是空泛地"多提问"）
- 引导而非直接给结论：面对"这个怎么算/这是什么"，先反问"你打算怎么判断？""你觉得可能是哪种情况？"
- 学生给出结论后，追问"你这么判断的依据是什么？"，检验依据是否站得住，而不是直接说对错
- 把追问定在"这条规则成立的上层原理"上，不要停留在"套公式"层面
- 只有明确需要结构化产出（复习清单、解题步骤总结）时才用结构化格式，其余时候用口语化的引导对话

# 任务
1. 如果上面有"之前的对话"，先理解学生这句话是不是在追问/指代前面聊过的内容（比如"它""这样的话""再讲讲"），
   不要把这句话当成孤立的新问题重新讲一遍已经讲过的内容，要接着上文继续，除非学生明显换了话题
2. 结合上面的场景判断和苏格拉底式引导原则生成回应内容。只有学生明确要直接答案、或者是"自测复习"这类
   需要结构化产出的场景时，才用四步结构（一句话讲本质→打比方→分层展开→收尾"所以呢"）完整展开，
   篇幅按detail_level伸缩；其余场景（尤其是报错求助、可视化探索）优先用引导性提问，不要一次性把结论讲完；
   如果是追问，可以跳过"一句话讲本质"这类开场，直接接着回应
3. 判断这道题/这个问题是否需要配视觉素材，如果需要，从可用素材里选一个最合适的，不要什么都配

# 媒体选择判断依据（按优先级）
- 学生明确要求"看图""演示""动画""3d""模拟"这类可视化诉求 → 优先满足学生的明确请求，选对应素材
- 问题涉及"运动过程""怎么动的""为什么能转/不能转"这类动态特性 → 优先选3D交互素材（如果manifest里有）
- 问题涉及"结构长什么样""杆件怎么连接""哪个是曲柄"这类静态结构辨认 → 优先选静态结构图
- mastery_level=已掌握 且 detail_level=低（学生只是想快速确认一下）→ 倾向none
- mastery_level=未学/薄弱 → 倾向配图或3D，降低单靠文字理解的门槛

只输出以下JSON，不要输出多余文字：
{{
  "explanation": "按上面四步结构生成的讲解文本",
  "media": {{
    "content_id": "从manifest里选的素材id，或 none",
    "reason": "一句话说明为什么选（或不选）这个素材"
  }}
}}"""


def _extract_json(text: str) -> dict:
    """从模型输出里抠出JSON——即使模型多输出了几句废话也能兜底解析。"""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"未能从模型输出中解析出JSON：{text[:200]}")
    return json.loads(match.group(0))


def _call_llm(prompt: str) -> str:
    """真实调用千帆 v2 chat/completions（OpenAI兼容格式）。走标准库 urllib，不引入额外依赖。"""
    url = f"{QIANFAN_BASE_URL}/v2/chat/completions"
    payload = {
        "model": QIANFAN_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {QIANFAN_API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"]


def _mock_generate(knowledge_point: KnowledgePoint, message: str, student_state: dict) -> dict:
    """没配API key时的规则版占位实现，模拟提示词库第7条的判断逻辑（不是真的语义理解，
    只是关键词规则近似，纯粹为了让 “分类路由→讲解生成→媒体决策→嵌入渲染” 这条链路
    在没有真实模型接入前也能跑通测试）。
    """
    mastery = student_state.get("mastery_level", "未学")
    detail = student_state.get("detail_level", "中")
    available_ids = {m.content_id for m in knowledge_point.media_options}

    explanation = (
        f"[MOCK-LLM 占位输出，等真实API接入后由模型生成] "
        f"关于「{knowledge_point.name}」：{knowledge_point.standard_content}"
    )

    lower_msg = message.lower()
    wants_dynamic = any(w in message for w in ["3d", "动画", "模拟", "怎么动", "运动过程", "过程"]) or "3d" in lower_msg
    wants_static = any(w in message for w in ["图", "结构", "长什么样", "组成", "画一下"])

    if wants_dynamic and "linkage_3d" in available_ids:
        content_id, reason = "linkage_3d", "[MOCK规则] 消息含动态/过程类关键词，且该知识点有3D素材"
    elif wants_static and any(cid != "linkage_3d" for cid in available_ids):
        content_id = next(cid for cid in available_ids if cid != "linkage_3d")
        reason = "[MOCK规则] 消息含结构/静态类关键词，优先选静态图"
    elif mastery == "已掌握" and detail == "低":
        content_id, reason = "none", "[MOCK规则] 已掌握+低详略度，倾向纯文字"
    elif knowledge_point.media_options:
        content_id = knowledge_point.media_options[0].content_id
        reason = "[MOCK规则] 未命中明确诉求，默认给该知识点的第一个素材降低理解门槛"
    else:
        content_id, reason = "none", "[MOCK规则] 该知识点暂无可用素材"

    return {"explanation": explanation, "media": {"content_id": content_id, "reason": reason}}


KC_TAGGING_PROMPT_TEMPLATE = """以下是本课程全部知识点的候选清单（id: 名称 - 关键词）：
{candidates}

学生这句话原文：
{text}

# 任务
判断这句话实际涉及候选清单里的哪些知识点（可能是1个，也可能是多个——比如学生同时问了
"整转副判断"和"自由度计算"，就要把两个都列出来）。只能从上面的候选id里选，不能编造不存在的id；
完全不涉及课程知识点内容的（比如闲聊、操作性提问）返回空列表。

只输出以下JSON，不要输出多余文字：
{{"knowledge_point_ids": ["从候选id里选的0个或多个id"]}}"""


def _mock_classify_kc(text: str) -> list:
    """没配key/调用失败时降级成关键词匹配（knowledge_base.classify_knowledge_points_multi），
    跟generate_explanation_and_media的降级策略保持一致。"""
    return classify_knowledge_points_multi(text)


def classify_knowledge_points_llm(text: str) -> list:
    """给一段学生原话（不一定是完整句子，可能是对话里的一轮），返回涉及的知识点列表（可能多个）。

    对应 [Dialogue-KT论文](../参考论文/Dialogue-KT_Knowledge_Tracing_in_Dialogues.pdf) 里"用LLM给
    每轮对话打知识点标签"的思路——不训练、只是prompt，论文人类专家评估这一步准确率很高（表4，
    正确性评分0.93/1）。用来替代 knowledge_base.classify_knowledge_points_multi() 的纯关键词匹配：
    关键词匹配的死角是学生换个说法（比如描述"最短杆和最长杆之和"但没提"杆长条件"这个词）就会
    分类失败或漏标次要知识点，LLM能理解语义、不依赖字面关键词命中。

    没配API key或调用失败时，降级为关键词匹配版本（不是直接报错断链路，跟 generate_explanation_and_media
    的降级策略一致）——这样 mastery_model.py 等调用方不需要关心key是否配置，接口形状不变。
    """
    if not text:
        return []
    if not QIANFAN_API_KEY:
        return _mock_classify_kc(text)

    candidates = "\n".join(f"{kp.id}: {kp.name} - {'、'.join(kp.keywords)}" for kp in KNOWLEDGE_POINTS)
    prompt = KC_TAGGING_PROMPT_TEMPLATE.format(candidates=candidates, text=text)
    try:
        raw_text = _call_llm(prompt)
        result = _extract_json(raw_text)
        ids = set(result.get("knowledge_point_ids", []))
        matched = [kp for kp in KNOWLEDGE_POINTS if kp.id in ids]
        # LLM偶尔会返回候选清单里没有的id（幻觉），这里直接过滤掉而不是报错，
        # 跟media_options"不能杜撰不存在的素材"是同一条防线
        return matched
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, json.JSONDecodeError):
        return _mock_classify_kc(text)


FALLBACK_REPLY_PROMPT_TEMPLATE = """你是"机械小助手"，河南科技大学《机械原理》《机械设计基础》
课程的学习伙伴。

{conversation_context_block}
学生刚发来这句话：
{message}

# 背景
分类模块判断这句话没有涉及课程范围内的任何知识点——但这本身可能对应好几种完全不同的情况，
不要机械地当成"只有一种可能"：
- 学生只是打招呼/寒暄/道谢/告别，压根没打算问知识点
- 学生问了课程范围外的东西（其他课程、生活闲聊、跟机械原理无关的内容）
- 学生的话里其实带着知识点，只是分类模块没识别出来（比如用词很口语化、缩写、错别字，
  或者问的是这门课确实没覆盖到的细分领域）
- 学生的表达太模糊/不完整，看不出想问什么

# 任务
你自己判断这句话属于上面哪种情况，给出自然、简短、符合这种情况的回应：
- 打招呼/寒暄 -> 像正常人一样回应，顺带提一句你能帮上什么忙（讲知识点/3D演示/自测出题），
  不要机械地报菜单
- 真的超纲/无关 -> 委婉说明这不在你的服务范围内，不用逐条列举课程目录
- 看起来可能跟课程有关但你能理解意思 -> 直接尝试用你自己的知识回答，不要因为"分类模块
  没认出来"就拒绝回答，那样对学生很不友好；只在真的看不懂在问什么的时候才反问澄清
- 太模糊看不懂 -> 反问学生想问什么，不要瞎猜

不要提"分类""关键词""覆盖范围""知识点列表"这类技术性说法，学生感受不到、也不需要知道
你内部是怎么判断的。直接输出你的回复文本，不要输出多余的解释或JSON。"""


def _mock_fallback_reply(message: str) -> str:
    """没配key时的降级占位——没法做语义判断，退化成最保守的一句通用回应，
    带[MOCK-LLM]前缀避免被误当成真实模型输出，跟本文件其他MOCK函数一致。"""
    return "[MOCK-LLM 占位输出] 这句话好像不属于《机械原理》《机械设计基础》的内容，能换个说法或者说明具体想问哪部分吗？"


def generate_fallback_reply(message: str, conversation_context: str = "") -> str:
    """分类模块判断这句话没有命中任何知识点时的兜底回复生成——不是无脑返回一句写死的
    "不在覆盖范围内"，而是把判断"这到底是问候/闲聊/超纲问题/表达模糊"这件事也交给LLM
    自己做（原因见 FALLBACK_REPLY_PROMPT_TEMPLATE 顶部说明）：关键词/规则判断只适合
    覆盖有限的、能穷举的场景，学生实际的说法五花八门，硬编码规则很快就会碰到没覆盖到
    的说法，而LLM天然能理解语义，不需要为每种可能的问候/寒暄措辞单独维护一份关键词表。

    没配key或调用失败时降级成 _mock_fallback_reply()，跟本文件其他函数策略一致，
    不会因为这一步失败就导致整条链路报错断掉。
    """
    if not QIANFAN_API_KEY:
        return _mock_fallback_reply(message)

    context_block = f"之前的对话：\n{conversation_context}\n" if conversation_context else ""
    prompt = FALLBACK_REPLY_PROMPT_TEMPLATE.format(conversation_context_block=context_block, message=message)
    try:
        return _call_llm(prompt).strip()
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        fallback = _mock_fallback_reply(message)
        return f"[LLM调用失败，已降级为占位输出：{e}] " + fallback


FILL_BLANK_JUDGE_PROMPT_TEMPLATE = """题目：
{stem}

标准答案（按空的顺序给出，学生的回答不需要逐字照抄，意思对、关键数值/术语对即可判对）：
{correct_answers}

学生的回答原文：
{student_answer}

# 任务
判断学生的回答是否覆盖了标准答案里的要点。宽松一点判断——允许口语化表达、允许漏掉无关紧要
的修饰词，但关键数值、专有名词、因果关系不能错或漏。只要判断，不需要解释。

只输出以下JSON，不要输出多余文字：
{{"correct": true 或 false}}"""


def _mock_judge_fill_blank(correct_answers: list, student_answer: str) -> bool:
    """没配key/调用失败时的降级判断：填空题标准答案通常是简短的数字/术语，退化成
    "标准答案里的每一项是否都在学生回答原文里逐字出现"这种粗糙但至少不瞎猜的规则——
    比语义判断严格得多（学生换个说法就会被判错），跟其他MOCK函数一样只是保证链路
    不断，不追求跟真实LLM判断一样准。"""
    if not correct_answers:
        return False
    return all(str(ans).strip() and str(ans).strip() in student_answer for ans in correct_answers)


def judge_fill_blank_llm(stem: str, correct_answers: list, student_answer: str) -> bool:
    """判断填空题的学生作答是否正确。填空题的标准答案是"每个空一个字符串"的列表
    （见 题库.json 的 answer 字段，如 ["6", "3", "3"]），但学生是把所有空的答案揉在一整段
    自由文本里回答的（比如"应该是6个瞬心，3个绝对的3个相对的"），没法用简单的字符串
    位置对齐去逐空比对，跟 classify_knowledge_points_llm 一样的理由——语义判断只能靠LLM，
    规则匹配的死角是学生换个措辞就会被误判。

    没配key或调用失败时降级成 _mock_judge_fill_blank()（更严格的字面匹配），不直接报错
    断掉整条"判分->更新表B"的链路，跟本文件其他函数的降级策略保持一致。
    """
    if not QIANFAN_API_KEY:
        return _mock_judge_fill_blank(correct_answers, student_answer)

    prompt = FILL_BLANK_JUDGE_PROMPT_TEMPLATE.format(
        stem=stem,
        correct_answers="、".join(str(a) for a in correct_answers),
        student_answer=student_answer,
    )
    try:
        raw_text = _call_llm(prompt)
        result = _extract_json(raw_text)
        return bool(result.get("correct", False))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, json.JSONDecodeError):
        return _mock_judge_fill_blank(correct_answers, student_answer)


def generate_explanation_and_media(knowledge_point: KnowledgePoint, message: str, student_state: dict,
                                    conversation_context: str = "") -> dict:
    """对外唯一入口：给定知识点+学生消息+学情状态，返回 {explanation, media:{content_id, reason}}。

    student_state 预期字段（暂时都给默认值，等表B/共享个性化层节点接入后传真实值）：
      mastery_level: 未学/学习中/薄弱/已掌握
      detail_level: 低/中/高
      encourage_level: 低/中/高

    conversation_context: conversation_memory.build_context_text() 生成的"之前聊了什么"文本，
      空字符串表示没有历史（第一次对话/本地缓冲还没有记录），此时对应的模板段落直接留空，
      不会误导模型以为"之前没聊过"就是"确定是新话题"——只是没有可参考的历史而已。
    """
    student_state = student_state or {}
    student_state.setdefault("mastery_level", "未学")
    student_state.setdefault("detail_level", "中")
    student_state.setdefault("encourage_level", "中")

    if not QIANFAN_API_KEY:
        return _mock_generate(knowledge_point, message, student_state)

    context_block = f"\n之前的对话（供你判断这句话是否在追问/指代前面的内容）：\n{conversation_context}\n" if conversation_context else "\n"

    prompt = PROMPT_TEMPLATE.format(
        knowledge_point=knowledge_point.name,
        standard_content=knowledge_point.standard_content,
        mastery_level=student_state["mastery_level"],
        detail_level=student_state["detail_level"],
        encourage_level=student_state["encourage_level"],
        conversation_context_block=context_block,
        available_media_manifest=knowledge_point.media_manifest_text(),
        message=message,
    )
    try:
        raw_text = _call_llm(prompt)
        return _extract_json(raw_text)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, json.JSONDecodeError) as e:
        # 真实调用失败时兜底降级成 mock，避免因为API问题导致整条链路直接报错断掉
        fallback = _mock_generate(knowledge_point, message, student_state)
        fallback["explanation"] = f"[LLM调用失败，已降级为占位输出：{e}] " + fallback["explanation"]
        return fallback
