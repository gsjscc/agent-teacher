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

# 任务
1. 如果上面有"之前的对话"，先理解学生这句话是不是在追问/指代前面聊过的内容（比如"它""这样的话""再讲讲"），
   不要把这句话当成孤立的新问题重新讲一遍已经讲过的内容，要接着上文继续，除非学生明显换了话题
2. 按四步结构（一句话讲本质→打比方→分层展开→收尾"所以呢"）生成讲解文本，篇幅按detail_level伸缩；
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
