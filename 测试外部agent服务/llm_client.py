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
该学生完整学情画像（已学过的知识点掌握情况，供你判断范围模糊/依赖个人情况的诉求要不要先问清楚——
比如"给我列个复习计划"，如果这里已经能看出哪些知识点薄弱/该复习，就不用再问学生"你哪里不会"，
直接结合这份画像出方案；如果画像是空的、或者答不了学生问题里真正缺的那部分（比如没写"还有多久
考试""每天能投多久"这类只有学生自己知道的信息），才需要反问）：
{student_profile_summary}

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
5. 范围模糊/依赖个人情况的诉求（"给我列个复习计划""帮我梳理一下这门课""我该先学哪个"这类，不是
   问某一个具体知识点，而是要一个跨知识点的安排/判断）→ 先看上面的完整学情画像和"之前的对话"
   能不能覆盖回答所需要的信息；缺的是画像/历史里已经有的（比如哪里薄弱），不用再问，直接结合
   已有数据出方案；缺的是只有学生自己知道的信息（还有多久考试、每天能投入多少时间、想不想聚焦
   某几章），先问清楚这一个最关键的缺口，不要在信息不够的情况下直接假设/瞎猜给一个通用方案。
   反问的时候如果要给学生列举几个可选项（比如让学生挑章节/挑方向），把选项列成一行一个的列表
   （比如"- 凸轮机构\n- 齿轮传动\n- 连杆机构"），不要把好几个选项揉进一句话里读起来费劲——
   哪怕只是在问澄清问题、还没到最终出方案那一步，只要涉及列举选项就要用列表，方便学生一眼
   看清楚能选什么、也方便简短回复。这一条不适用于范围明确的具体问题（比如"什么是转动副"）——
   那类问题不需要为了"了解学生情况"额外反问，直接回答/引导即可，不要把这条规则用成"逢事必先
   问一堆背景信息"

# 苏格拉底式引导（每次回应尽量落实，不是空泛地"多提问"）
- 引导而非直接给结论：面对"这个怎么算/这是什么"，先反问"你打算怎么判断？""你觉得可能是哪种情况？"
- 学生给出结论后，追问"你这么判断的依据是什么？"，检验依据是否站得住，而不是直接说对错
- 把追问定在"这条规则成立的上层原理"上，不要停留在"套公式"层面
- 只有明确需要结构化产出（复习清单、解题步骤总结）时才用结构化格式，其余时候用口语化的引导对话
- 每次只抛一个问题、停在那里等学生回答，不要在同一条回复里把"想象一下……再对比一下……你先说说……"
  这类好几个反问/类比/铺垫连着堆完——学生一看是好几个问题挤在一起，往往就不会真的停下来想，
  只会顺着往下看完，等于你自己把整个推导过程讲完了，学生只是被动读者，没有真正交互
- 尤其是mastery_level=未学/薄弱时，凡是要学生判断/选择的地方，尽量把开放式反问收窄成具体的
  选项（比如"A. 速度突变  B. 加速度突变，你觉得刚性冲击对应哪个？"），列成一行一个的列表；
  给了选项学生才会真的停下来选一个，而不是看着一堆开放式问题随口带过、跟没问一样。给完这一个
  问题就停，等学生这一轮回复之后再问下一步，不要一次性把后面几步问题也一起写出来
- 学生答完这一步之后（不管是选的选项还是自己打字回答），先看"之前的对话"里那道题问的是什么、
  正确答案该是什么，再对着学生这句话判断对错：答对了，明确肯定"对，就是XX"，再顺势抛下一步的
  问题，把引导链条往前推一格；答错了，不要只说"不对，再想想"，要具体说出学生这个答案错在哪个
  环节（比如学生把"加速度突变"当成了"速度突变"），针对这个具体的错误点重新给一个更小的台阶
  （换个更具体的类比或更窄的选项）帮他纠正，而不是重复一遍原来的问题

# 任务
1. 如果上面有"之前的对话"，先理解学生这句话是不是在追问/指代前面聊过的内容（比如"它""这样的话""再讲讲"），
   不要把这句话当成孤立的新问题重新讲一遍已经讲过的内容，要接着上文继续，除非学生明显换了话题；
   如果"之前的对话"最后一轮是你自己提出的场景5澄清问题，这一轮学生的回答就是在答那个问题，直接
   拿去结合学情画像出方案，不要再问一遍
2. 结合上面的场景判断和苏格拉底式引导原则生成回应内容。只有学生明确要直接答案、或者是"自测复习"/
   场景5这类需要结构化产出的场景时，才用四步结构（一句话讲本质→打比方→分层展开→收尾"所以呢"）
   完整展开，篇幅按detail_level伸缩；其余场景（尤其是报错求助、可视化探索）优先用引导性提问，
   不要一次性把结论讲完；如果是追问，可以跳过"一句话讲本质"这类开场，直接接着回应；场景5下，
   信息够用可以出方案了，用Markdown格式输出（## 标题分组、- [ ] 复选框列表）；还在反问阶段但
   要列举选项时，也要用列表格式呈现选项（见上面场景5说明），不要写成一整句话；其余场景不用
   Markdown格式，保持口语化
3. 判断这道题/这个问题是否需要配视觉素材，如果需要，从可用素材里选一个最合适的，不要什么都配

# 媒体选择判断依据（按优先级）
- 学生明确要求"看图""演示""动画""3d""模拟"这类可视化诉求 → 优先满足学生的明确请求，选对应素材
- 问题涉及"运动过程""怎么动的""为什么能转/不能转"这类动态特性 → 优先选3D交互素材（如果manifest里有）
- 问题涉及"结构长什么样""杆件怎么连接""哪个是曲柄"这类静态结构辨认 → 优先选静态结构图
- mastery_level=已掌握 且 detail_level=低（学生只是想快速确认一下）→ 倾向none
- mastery_level=未学/薄弱 → 倾向配图或3D，降低单靠文字理解的门槛

如果讲解里要写数学公式，只用普通文字符号（比如 d = m × z、F = 3n - 2PL - PH），
不要用LaTeX语法（不要出现 \times \frac \( \) 这类反斜杠命令）——你的输出会被当成JSON
解析，反斜杠是JSON的转义符，LaTeX命令会导致解析失败、整条回复变成兜底占位内容，
公式写不出来反而更糟。

只输出以下JSON，不要输出多余文字：
{{
  "explanation": "按上面四步结构生成的讲解文本",
  "media": {{
    "content_id": "从manifest里选的素材id，或 none",
    "reason": "一句话说明为什么选（或不选）这个素材"
  }}
}}"""


# 这里故意没有列出JSON规范里全部合法的转义字符（"\\/bfnrtu"），只列了模型真实会有意
# 使用的几个（引号、反斜杠本身、换行）。原因：b/f/r/t/u 这几个字母恰好是LaTeX命令的
# 常见首字母——\times \frac \beta \rightarrow \underline——如果把它们也当"合法转义"
# 放过，json.loads会把"\t"解析成制表符、"\f"解析成换页符，模型原本想写的"times""frac"
# 这些字母反而从explanation里消失、换成看不见的控制字符，比留着反斜杠更难排查。所以这里
# 宁可"错杀"少数模型确实想用\t \r这类真实转义的场景（对话文本里本来就极少见），也要把
# b/f/r/t/u排除在信任范围外，统一按下面_fix_invalid_json_escapes()的"非法转义"分支处理
# （丢弃反斜杠、保留字母本身），这样\times会变成times，至少文字内容不会丢也不会插入乱码。
_VALID_JSON_ESCAPE_CHARS = set('"\\n')


def _fix_invalid_json_escapes(json_text: str) -> str:
    """兜底修复：prompt已经让模型别用LaTeX写公式（见PROMPT_TEMPLATE），但模型不一定
    每次都听话——真实测过一次"帮我画个图讲解连杆"，模型在explanation里混入了LaTeX命令，
    直接把 json.loads 干报错（"Invalid \\escape"），整条讲解生成失败、降级成完全不相关的
    MOCK占位内容，公式类/讲解类回答的可用性因此打了折扣。

    这里扫一遍文本，遇到"反斜杠+JSON合法转义字符"就把这两个字符当一个整体一起跳过，
    遇到"反斜杠+其他字符"（非法转义）就把这个反斜杠直接丢弃、只保留后面那个字符。
    必须按"整体跳过合法转义对"来处理，不能像早期版本那样逐字符扫、遇到非法反斜杠就
    多塞一个反斜杠回去——那样一旦文本里连续出现好几个反斜杠（LaTeX公式里很常见，比如
    "\\times \\frac \\(" ），前一对转义里补出来的反斜杠会被下一轮循环误当成新一轮转义的
    起点，导致后面本该合法的转义对也被错误地当成非法处理，级联出更多解析不出来的转义。
    丢弃非法反斜杠（而不是转义成双反斜杠）还有个好处：不会再引入新的反斜杠字符，从根上
    避免了这种级联误判。代价是LaTeX命令里的反斜杠会从最终讲解文本里消失（"\\times"变成
    "times"），不会被渲染成公式，但比整条回复被降级成不相关的MOCK内容要好得多。
    """
    result = []
    i, n = 0, len(json_text)
    while i < n:
        ch = json_text[i]
        if ch == "\\":
            if i + 1 < n and json_text[i + 1] in _VALID_JSON_ESCAPE_CHARS:
                result.append(ch)
                result.append(json_text[i + 1])
                i += 2
                continue
            # 非法转义，或反斜杠是最后一个字符——直接丢掉这个反斜杠，不产出新的反斜杠
            i += 1
            continue
        result.append(ch)
        i += 1
    return "".join(result)


def _extract_json(text: str) -> dict:
    """从模型输出里抠出JSON——即使模型多输出了几句废话也能兜底解析。"""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"未能从模型输出中解析出JSON：{text[:200]}")
    raw = match.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 最常见的诱因是模型讲数学公式时混入了LaTeX语法，先按这个假设修复一次转义再重试，
        # 而不是让整条讲解生成链路直接失败降级成不相关的MOCK内容
        return json.loads(_fix_invalid_json_escapes(raw))


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

    prompt = KC_TAGGING_PROMPT_TEMPLATE.format(candidates=_kp_candidates_text(), text=text)
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
该学生完整学情画像（供你判断"跨知识点的安排/判断类"诉求要不要利用已有数据回答，而不是
死板地当成"分类模块没认出来就是超纲"）：
{student_profile_summary}

学生刚发来这句话：
{message}

# 背景
分类模块判断这句话没有涉及课程范围内的任何**单个**知识点——但这本身可能对应好几种完全不同
的情况，不要机械地当成"只有一种可能"：
- 学生只是打招呼/寒暄/道谢/告别，压根没打算问知识点
- 学生问了课程范围外的东西（其他课程、生活闲聊、跟机械原理无关的内容）
- 学生问的是跨知识点的安排/判断（"给我列个复习计划""帮我梳理一下这门课""我该先学哪个"），
  不对应某一个具体知识点，但明确是课程相关的诉求
- 学生的话里其实带着知识点，只是分类模块没识别出来（比如用词很口语化、缩写、错别字，
  或者问的是这门课确实没覆盖到的细分领域）
- 学生的表达太模糊/不完整，看不出想问什么

# 任务
你自己判断这句话属于上面哪种情况，给出自然、简短、符合这种情况的回应：
- 打招呼/寒暄 -> 像正常人一样回应，顺带提一句你能帮上什么忙（讲知识点/3D演示/自测出题），
  不要机械地报菜单
- 真的超纲/无关 -> 委婉说明这不在你的服务范围内，不用逐条列举课程目录
- 跨知识点的安排/判断类诉求 -> 先看上面的学情画像和"之前的对话"能不能覆盖回答所需要的信息；
  缺的是画像/历史里已经有的（比如哪里薄弱），不用再问，直接结合已有数据用Markdown格式
  （## 标题分组、- [ ] 复选框列表）给一份方案；缺的是只有学生自己知道的信息（还有多久
  考试、每天能投入多少时间、想聚焦哪几章），先问清楚这一个最关键的缺口，不要直接假设/
  瞎猜给一个通用方案——反问的时候如果要给学生列举几个可选项（比如让学生挑章节/挑方向），
  把选项列成一行一个的列表（比如"- 凸轮机构\n- 齿轮传动\n- 连杆机构"），不要揉进一句话里
  读起来费劲，哪怕还在问澄清问题、没到最终出方案那一步，只要涉及列举选项就要用列表；
  如果"之前的对话"最后一轮就是你自己提的这类澄清问题，这轮学生的回答就是在答，直接结合
  画像出方案，不要再问一遍
- 看起来可能跟课程有关但你能理解意思（且是范围明确的具体问题）-> 直接尝试用你自己的知识
  回答，不要因为"分类模块没认出来"就拒绝回答，那样对学生很不友好；只在真的看不懂在问什么
  的时候才反问澄清
- 太模糊看不懂 -> 反问学生想问什么，不要瞎猜

不要提"分类""关键词""覆盖范围""知识点列表"这类技术性说法，学生感受不到、也不需要知道
你内部是怎么判断的。除非是"跨知识点的安排/判断类"诉求（不管是出最终方案还是还在反问阶段
列选项，见上面说明），其余情况不要用Markdown格式列表/标题，直接输出你的回复文本，不要
输出多余的解释或JSON。"""


def _mock_fallback_reply(message: str) -> str:
    """没配key时的降级占位——没法做语义判断，退化成最保守的一句通用回应，
    带[MOCK-LLM]前缀避免被误当成真实模型输出，跟本文件其他MOCK函数一致。"""
    return "[MOCK-LLM 占位输出] 这句话好像不属于《机械原理》《机械设计基础》的内容，能换个说法或者说明具体想问哪部分吗？"


def generate_fallback_reply(message: str, conversation_context: str = "", student_profile_summary: str = "") -> str:
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
    prompt = FALLBACK_REPLY_PROMPT_TEMPLATE.format(
        conversation_context_block=context_block,
        student_profile_summary=student_profile_summary or "（没有画像数据）",
        message=message,
    )
    try:
        return _call_llm(prompt).strip()
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        fallback = _mock_fallback_reply(message)
        return f"[LLM调用失败，已降级为占位输出：{e}] " + fallback


def _kp_candidates_text() -> str:
    """构造"候选知识点清单"文本，KC_TAGGING_PROMPT_TEMPLATE和下面几个新的意图判断
    prompt都要用到同一份候选清单，抽出来避免同样的拼接逻辑写三遍。"""
    return "\n".join(f"{kp.id}: {kp.name} - {'、'.join(kp.keywords)}" for kp in KNOWLEDGE_POINTS)


PENDING_ANSWER_CHECK_PROMPT_TEMPLATE = """刚才给学生出了一道题，学生现在回了一句话，判断这句话
是"在回答这道题"，还是"在问别的事情"（比如学生看不懂题目、想先弄懂相关知识点、或者干脆聊起了
别的）——这个判断很重要：如果误判成"在回答"，会把一句正常提问强行当成答案去判对错，体验很差。

题目：
{stem}

学生刚才回的话：
{student_message}

# 任务
只判断"这句话像不像是在尝试回答上面这道题"，不需要判断对错（对错是另一个环节的事）。
只要学生的话里包含了某种形式的作答尝试（哪怕答得不对、答得含糊），就算"在回答"；如果学生
明显是在问问题、要求讲解、表示不会/想先学、或者说的是完全无关的内容，就算"不在回答"。

只输出以下JSON，不要输出多余文字：
{{"is_answering": true 或 false}}"""


def _mock_is_answering_pending(question_type: str, student_message: str) -> bool:
    """没配key时的降级判断：退化成"这句话里有没有出现看起来像作答的痕迹"这种粗糙规则——
    选择题/判断题看有没有选项字母或对错词汇，其余情况（填空/简答）没有类似的字面线索
    可抓，保守地当作"在回答"（宁可误判成回答走一次可能不准的判分，也不要让填空题永远
    卡在pending_question出不去）。"""
    import re
    if question_type in ("single_choice", "multiple_choice"):
        return bool(re.search(r"[A-Ea-e]", student_message))
    if question_type == "true_false":
        lower = student_message.lower()
        return any(w in lower for w in ("对", "错", "正确", "错误", "true", "false"))
    return True


def is_answering_pending_question_llm(stem: str, question_type: str, student_message: str) -> bool:
    """判断学生这轮消息是不是在回答挂起的题，而不是在问别的——不用"看有没有选项字母"这种
    死板规则去判断（那样"我不知道选什么，A和B看着都像"这种夹杂了字母的疑问句会被误判成
    在回答），交给LLM理解语境。没配key/调用失败时降级成 _mock_is_answering_pending()。
    """
    if not QIANFAN_API_KEY:
        return _mock_is_answering_pending(question_type, student_message)

    prompt = PENDING_ANSWER_CHECK_PROMPT_TEMPLATE.format(stem=stem, student_message=student_message)
    try:
        raw_text = _call_llm(prompt)
        result = _extract_json(raw_text)
        return bool(result.get("is_answering", True))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, json.JSONDecodeError):
        return _mock_is_answering_pending(question_type, student_message)


QUIZ_REQUEST_PROMPT_TEMPLATE = """以下是本课程全部知识点的候选清单（id: 名称 - 关键词）：
{candidates}

学生这句话原文：
{message}

# 任务
判断学生是不是想让你**现在就**出一道具体的题给他做（比如"考考我""来道题""练习几道题"，
不管措辞多随意都算，只要是要马上开始做题）。

注意区分：学生如果是想要一份**复习安排/计划**（比如"我想复习这门课""帮我梳理一下复习
思路""考前该怎么复习"），这不算想现在做题——这类诉求应该判false，交给别的环节先跟学生
聊清楚复习的范围/时间再说，不要一上来就扔一道题打断这个过程。只有学生明确表达"要做题/
要被考"这个动作本身（哪怕带着"复习"这个词，比如"帮我复习一下，出几道题"），才判true。

如果判true，再看学生有没有指定想练哪个知识点/章节——指定了就从候选清单里选对应的id，
没指定（比如就说"随便考我"）就是null，不能编造候选清单里没有的id。

只输出以下JSON，不要输出多余文字：
{{"is_quiz_request": true 或 false, "target_knowledge_point_id": "候选id或null"}}"""


def _mock_detect_quiz_request(message: str) -> dict:
    """没配key时的降级判断：退化成关键词匹配（比纯粹返回false更有用，至少覆盖最常见的
    几种说法），没法做"学生有没有指定知识点"这种语义抽取，target_knowledge_point_id
    固定返回None——降级场景本来就是精度打折的，不强求做到完整功能。"""
    keywords = ("考考我", "来道题", "出一道题", "出道题", "自测", "测一下我", "做几道题", "随便考我", "给我出题", "复习一下")
    return {"is_quiz_request": any(kw in message for kw in keywords), "target_knowledge_point_id": None}


def detect_quiz_request_llm(message: str) -> dict:
    """判断学生是不是想自测出题，以及有没有指定知识点。不用关键词表——学生说"帮我复习一下"
    "想练几道题看看"这类没有事先枚举到的说法，关键词匹配会漏判，只有语义理解能兜住，跟
    classify_knowledge_points_llm是同一个理由。没配key/调用失败时降级成 _mock_detect_quiz_request()。

    返回 {"is_quiz_request": bool, "target_knowledge_point_id": Optional[str]}。
    """
    if not QIANFAN_API_KEY:
        return _mock_detect_quiz_request(message)

    prompt = QUIZ_REQUEST_PROMPT_TEMPLATE.format(candidates=_kp_candidates_text(), message=message)
    try:
        raw_text = _call_llm(prompt)
        result = _extract_json(raw_text)
        target = result.get("target_knowledge_point_id")
        # LLM偶尔会返回候选清单里没有的id（幻觉）或者把"没指定"写成空字符串而不是null，
        # 这里统一校验/归一化，跟其余分类函数"过滤幻觉id"的防线一致
        valid_ids = {kp.id for kp in KNOWLEDGE_POINTS}
        if target not in valid_ids:
            target = None
        return {"is_quiz_request": bool(result.get("is_quiz_request", False)), "target_knowledge_point_id": target}
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, json.JSONDecodeError):
        return _mock_detect_quiz_request(message)


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
                                    conversation_context: str = "", student_profile_summary: str = "") -> dict:
    """对外唯一入口：给定知识点+学生消息+学情状态，返回 {explanation, media:{content_id, reason}}。

    student_state 预期字段（暂时都给默认值，等表B/共享个性化层节点接入后传真实值）：
      mastery_level: 未学/学习中/薄弱/已掌握
      detail_level: 低/中/高
      encourage_level: 低/中/高

    conversation_context: conversation_memory.build_context_text() 生成的"之前聊了什么"文本，
      空字符串表示没有历史（第一次对话/本地缓冲还没有记录），此时对应的模板段落直接留空，
      不会误导模型以为"之前没聊过"就是"确定是新话题"——只是没有可参考的历史而已。

    student_profile_summary: mastery_model.format_profile_summary_text() 生成的"这个学生在
      全部已学知识点上的掌握情况"文本（不是只有当前kp这一条）——给PROMPT_TEMPLATE场景5
      （复习计划/跨知识点安排类诉求）判断"该不该反问"用：能从这份画像里看出来的就不用问学生，
      画像答不了的才需要问。留空表示调用方没传（不应该发生，server.py每次都会算好传进来），
      模板里对应段落会显示成空字符串，模型会看到"没有数据"从而倾向于反问，不算错误的降级。
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
        student_profile_summary=student_profile_summary or "（没有画像数据）",
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
