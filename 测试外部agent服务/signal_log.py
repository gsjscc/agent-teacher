#!/usr/bin/env python3
"""
表A「学习信号记录表」的实现。

对应 [教学智能体方案讨论.md 9.5](../教学智能体方案讨论.md) 的原始设计：
  学生ID（INNER_userId）、知识点ID、信号类型（自报/提问/自我解释/可视化探索/做题）、
  极性（正/负/中）、证据摘录（一句话）、时间戳 —— 四条车道每轮对话都可能写一行，不只是车道A/C。

这是之前缺的一块：mastery_model.py（表B）之前直接从"对/错"跳到Elo评分，跳过了表A这一层，
丢失了"这次更新到底是因为什么信号"的可追溯记录，也没法支持自报/自我解释/可视化探索这几种
非做题类信号。现在补上：所有信号先写表A（原始事实，不隐藏证据），再由 mastery_model.py
读表A的信号去更新表B（聚合画像）——这样表B的每一次变化都能倒查回表A里的具体依据。

设计原则（9.5原文）："只有识别出与知识点理解相关的信号才写入表A，纯操作性对话
（如"怎么关掉这个模拟器"）不产生信号"——调用方（各车道的信号提炼节点/judge节点）
负责判断"这轮对话算不算一个信号"，本模块不做这层过滤，只负责记录和读取。

没有真实数据库（同 mastery_model.py 的处境），这里用追加写入的JSONL文件模拟表A的持久化，
JSONL（而不是一次性读写整个JSON数组）是因为表A是只增不改的事实日志，追加写不需要每次
读回全量数据再整体重写，更符合"日志表"的读写模式；等接入真表插件时，这里换成INSERT即可。
"""

import json
import os
import time
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SIGNAL_LOG_PATH = os.path.join(DATA_DIR, "learning_signals.jsonl")  # 表A，追加写

SIGNAL_TYPES = {"自报", "提问", "自我解释", "可视化探索", "做题"}
POLARITIES = {"正", "负", "中"}

# 9.5原文的简化打分规则里，"反复问同一知识点"要判负分，这里的判定口径：
# 同一学生对同一知识点的"提问"类信号，如果在时间窗口内已经出现过 REPEAT_QUESTION_THRESHOLD 次
# 以上（不含本次），本次自动判定为"反复提问"，极性强制覆盖成"负"，不管调用方传的是什么。
REPEAT_QUESTION_WINDOW_SECONDS = 24 * 3600
REPEAT_QUESTION_THRESHOLD = 2


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _read_all() -> list:
    if not os.path.isfile(SIGNAL_LOG_PATH):
        return []
    rows = []
    with open(SIGNAL_LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _append(row: dict):
    _ensure_data_dir()
    with open(SIGNAL_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _count_recent_questions(student_id: str, knowledge_point_id: str, before_ts: float) -> int:
    window_start = before_ts - REPEAT_QUESTION_WINDOW_SECONDS
    count = 0
    for row in _read_all():
        if (row["student_id"] == student_id and row["knowledge_point_id"] == knowledge_point_id
                and row["signal_type"] == "提问" and window_start <= row["timestamp"] < before_ts):
            count += 1
    return count


def record_signal(student_id: str, knowledge_point_id: str, signal_type: str,
                   polarity: str, evidence: str = "") -> dict:
    """写一行表A。这是唯一的写入口——所有信号（做题/自报/提问/自我解释/可视化探索）
    都从这里进来，保证表A格式统一、不会有的车道走了不同的字段结构。

    返回写入的完整记录（含自动生成的时间戳、以及"提问"类信号是否被判定为反复提问）。
    """
    if signal_type not in SIGNAL_TYPES:
        raise ValueError(f"未知信号类型：{signal_type}，必须是 {SIGNAL_TYPES} 之一")
    if polarity not in POLARITIES:
        raise ValueError(f"未知极性：{polarity}，必须是 {POLARITIES} 之一")

    now = time.time()
    repeated_question = False
    effective_polarity = polarity

    if signal_type == "提问":
        prior_count = _count_recent_questions(student_id, knowledge_point_id, now)
        if prior_count >= REPEAT_QUESTION_THRESHOLD:
            repeated_question = True
            effective_polarity = "负"  # 对应9.5"反复问同一知识点 -1"，不管调用方原本传的极性是什么

    row = {
        "student_id": student_id,
        "knowledge_point_id": knowledge_point_id,
        "signal_type": signal_type,
        "polarity": polarity,          # 调用方原始判断（如果是普通提问，这里通常是"中"）
        "effective_polarity": effective_polarity,  # 表B更新实际使用的极性（反复提问会被覆盖成"负"）
        "evidence": evidence,
        "repeated_question": repeated_question,
        "timestamp": now,
    }
    _append(row)
    return row


def get_signals(student_id: str, knowledge_point_id: Optional[str] = None, limit: int = 50) -> list:
    """读表A，主要给调试/教师端"查看某学生某知识点的原始信号历史"用。
    按时间倒序，最近的信号排前面。"""
    rows = [r for r in _read_all() if r["student_id"] == student_id]
    if knowledge_point_id:
        rows = [r for r in rows if r["knowledge_point_id"] == knowledge_point_id]
    rows.sort(key=lambda r: r["timestamp"], reverse=True)
    return rows[:limit]


if __name__ == "__main__":
    # 自测：模拟同一学生对同一知识点连续问3次问题，看第3次是否被判定为"反复提问"
    sid, kp = "demo_student_a", "lever_condition"
    for i in range(3):
        r = record_signal(sid, kp, "提问", "中", evidence=f"第{i+1}次问同一个问题")
        print(f"第{i+1}次提问：effective_polarity={r['effective_polarity']}, repeated_question={r['repeated_question']}")

    print("\n自报已懂信号：")
    r = record_signal(sid, kp, "自报", "正", evidence="我懂了，就是最短杆和最长杆之和那个条件")
    print(r)

    print("\n最近5条信号：")
    for row in get_signals(sid, kp, limit=5):
        print(f"  [{row['signal_type']}] {row['effective_polarity']} - {row['evidence']}")
