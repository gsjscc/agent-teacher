#!/usr/bin/env python3
"""
车道A/C「出题-判分」逻辑。

对应 [执行计划.md] 里长期挂着的待办："车道A/C的判断节点目前只输出judge/signal两个字段，
还没有在判断出对错后实际调用 POST /answer"——这里不走"在超星任务流里另外搭一套判断题目
对错的专门节点"这条路（那条路需要重新设计题目怎么呈现、判分逻辑放哪、跟现有转发链路怎么
拼接，工作量和风险都不小），而是直接复用已经打通、稳定运行的 /agent 转发链路：出题、
收学生作答、判分、更新表B（调 mastery_model.record_answer）全部在 server.py 这一层完成。
对超星平台来说，出题和平时讲解走的是同一套"发消息->等回复"交互，不需要多搭任何节点。

状态怎么维护：出题之后，把"这道题的id、类型、正确答案"存进 conversation_memory 这次对话的
pending_question字段（见conversation_memory.py）——学生下一轮不管说什么，server.py先检查
这个字段在不在，在的话就不再走"知识点讲解"那条路，改走这里的judge_answer()判分，判完清掉
这个字段，避免学生下一句正常提问被误判成"在回答上一道题"。

题型与判分方式的对应关系（题库.json 1220题实测统计）：
  single_choice（599题）  answer是单个字母，如 "D"           -> 精确比对，程序判断，不用LLM
  true_false（256题）     answer是Python布尔值 True/False    -> 精确比对，程序判断，不用LLM
  multiple_choice（101题）answer是字母列表，如 ["A","B","C"] -> 精确比对（集合比较），不用LLM
  fill_blank（62题）      answer是字符串列表，如 ["6","3","3"]-> 学生是自由文本作答，没法逐空
                                                                 位置对齐比对，走LLM语义判断
  short_answer（202题）   answer字段普遍是空字符串——题库里根本没有可比对的标准答案，这类题
                                                                 不适合自动判分，出题时直接排除
"""

import random
import re
from typing import Optional

from mastery_model import get_question, iter_questions, get_due_for_review
from llm_client import judge_fill_blank_llm, detect_quiz_request_llm, is_answering_pending_question_llm

# 出题只从"有真实标准答案、能自动判分"的题型里选，short_answer被排除在外（见上面模块docstring）。
AUTO_GRADABLE_TYPES = {"single_choice", "true_false", "multiple_choice", "fill_blank"}


def detect_quiz_request(message: str) -> dict:
    """判断学生是不是想自测出题、有没有指定知识点——直接转发给 llm_client.detect_quiz_request_llm()，
    不用关键词表：关键词只能覆盖"考考我""来道题"这类提前想到的说法，学生说"帮我复习一下"
    "想练几道题看看"照样是出题请求，但命中不了任何写死的关键词，只有语义理解能兜住，
    跟 llm_client.classify_knowledge_points_llm() 是同一个理由。这里单独包一层是为了让
    server.py 只依赖 quiz.py 这一个模块，不用同时import llm_client，边界更清晰。

    返回 {"is_quiz_request": bool, "target_knowledge_point_id": Optional[str]}。
    """
    return detect_quiz_request_llm(message)


def looks_like_answering(q: dict, student_message: str) -> bool:
    """判断学生这轮消息看起来像不像是在回答挂着的题q——同样不用"有没有出现选项字母/
    对错词"这种死板规则去猜（那样"我不确定选A还是B，能先讲讲这个知识点吗"这种其实是在
    问问题的话会被误判成在作答），交给LLM理解语境。"""
    return is_answering_pending_question_llm(q["stem"], q.get("type", ""), student_message)


def pick_question(student_id: str, target_knowledge_point_id: Optional[str] = None) -> Optional[dict]:
    """挑一道题给学生练。

    target_knowledge_point_id：学生自己指定要练哪个知识点时（比如"帮我出一道关于杆长条件的题"），
    优先级最高——尊重学生的明确诉求，不要因为"系统算法认为你更该练别的"就无视掉。
    没指定时，优先挑"该复习"的薄弱知识点（借 mastery_model.get_due_for_review() 的遗忘曲线
    判断——哪个知识点估算记忆保持率跌得最狠就优先练哪个），没有薄弱知识点数据可用时
    （比如新学生表B还是空的，或者没传student_id）随机挑一道可自动判分的题兜底。

    返回题目原始dict（题库.json的一行），找不到可选的题时返回None。
    """
    if target_knowledge_point_id:
        candidates = [
            q for q in iter_questions()
            if q.get("knowledge_point_id") == target_knowledge_point_id and q.get("type") in AUTO_GRADABLE_TYPES
        ]
        if candidates:
            return random.choice(candidates)
        # 学生指定的知识点没有能自动判分的题——不要静默地当作"没指定"随便挑一道别的题，
        # 那样学生会觉得答非所问；往下走随机兜底，是"总比完全不出题好"的最后防线，
        # 调用方（server.py）如果想更精确地告诉学生"这个知识点暂时没题"，可以自己
        # 先检查一遍这个条件，这里只负责挑题本身。

    due = get_due_for_review(student_id)["due_for_review"] if student_id else []
    if due:
        target_kp = due[0]["knowledge_point_id"]
        candidates = [
            q for q in iter_questions()
            if q.get("knowledge_point_id") == target_kp and q.get("type") in AUTO_GRADABLE_TYPES
        ]
        if candidates:
            return random.choice(candidates)

    # 没有薄弱知识点数据可用（新学生）——随机挑一道可自动判分的题，聊胜于无，
    # 不因为"还没攒够数据算出该复习什么"就完全没法出题
    fallback = [q for q in iter_questions() if q.get("type") in AUTO_GRADABLE_TYPES]
    return random.choice(fallback) if fallback else None


def format_question_for_display(q: dict) -> str:
    """把题目格式化成发给学生看的文本——选择题/多选题带完整选项列表，判断题/填空题只有题干，
    题目本身要不要配图（stem_images）由 server.py 决定 content_id，这里只管文字部分。"""
    lines = [q["stem"]]
    if q.get("options"):
        for opt in q["options"]:
            lines.append(f"{opt['label']}. {opt['text']}")
    return "\n".join(lines)


def question_display_content_id(q: dict) -> str:
    """题目如果带插图，返回 server.py /viewer 路由认得的 content_id（quiz_<question_id>_<index>
    格式，复用 server.py 里 _render_quiz_image() 已经实现好的渲染逻辑），没有插图就是"none"。
    只取第一张图——多图题目这里暂不处理，够用即可，等真遇到多图题库反馈效果不好再扩展。"""
    if q.get("stem_images"):
        return f"quiz_{q['id']}_0"
    return "none"


# 单选/多选从学生自由文本回答里抠选项字母用——比如学生说"我选A"、"应该是B吧"、"AC"，
# 都要能抠出里面的选项字母，不要求学生必须一字不差地只回复字母本身。
_OPTION_LETTER_RE = re.compile(r"[A-E]")
_TRUE_WORDS = ("对", "正确", "true", "对的", "√", "是的")
_FALSE_WORDS = ("错", "错误", "false", "不对", "×", "不是")


def judge_answer(q: dict, student_message: str) -> bool:
    """判断学生这轮回答是否正确。客观题（单选/判断/多选）用字符串精确比对——这几种题型的
    "对不对"本身没有语义模糊空间，程序判断比走LLM更快、更可靠、也不会有"LLM偶尔判错"的
    风险；只有fill_blank这种自由文本填空题，没法用简单的位置对齐比对，才降级成LLM语义判断
    （见 quiz.py 模块docstring顶部的题型判分方式对照表）。
    """
    qtype = q.get("type")
    correct_answer = q.get("answer")
    upper_msg = student_message.upper()

    if qtype == "single_choice":
        letters = _OPTION_LETTER_RE.findall(upper_msg)
        return bool(letters) and letters[0] == str(correct_answer).upper()

    if qtype == "multiple_choice":
        letters = set(_OPTION_LETTER_RE.findall(upper_msg))
        correct_letters = {str(x).upper() for x in (correct_answer or [])}
        return bool(letters) and letters == correct_letters

    if qtype == "true_false":
        lower_msg = student_message.lower()
        says_true = any(w in lower_msg for w in _TRUE_WORDS)
        says_false = any(w in lower_msg for w in _FALSE_WORDS)
        if says_true == says_false:
            # 两种表述都没出现，或者自相矛盾地同时出现了——判不出学生的真实意思，
            # 保守地判错（不能瞎猜蒙对，会污染表B）
            return False
        return says_true == bool(correct_answer)

    if qtype == "fill_blank":
        return judge_fill_blank_llm(q["stem"], correct_answer or [], student_message)

    # short_answer 等没有标准答案的题型理论上不会被 pick_question() 选中（AUTO_GRADABLE_TYPES
    # 已经排除），这里只是防御性兜底，避免万一 pending_question 里存的题id指向了这类题时崩掉
    return False


def format_feedback(q: dict, correct: bool) -> str:
    """判完分之后生成给学生看的反馈文本。优先用题库自带的explanation字段（如果有），
    没有就退化成"公布正确答案"——总要让学生知道自己错在哪、正确答案是什么，而不是只说
    一句"回答错误"就完事，那样学不到东西，跟本项目"强化思维而非替代思维"的原则不冲突：
    这里是判完客观对错之后的反馈环节，不是引导思考的环节，直给答案没问题。"""
    verdict = "回答正确！" if correct else "这次没答对。"
    explanation = (q.get("explanation") or "").strip()
    if explanation:
        return f"{verdict}\n{explanation}"

    qtype = q.get("type")
    answer = q.get("answer")
    if qtype == "true_false":
        answer_text = "正确" if answer else "错误"
    elif isinstance(answer, list):
        answer_text = "、".join(str(a) for a in answer)
    else:
        answer_text = str(answer)
    return f"{verdict}\n正确答案：{answer_text}"
