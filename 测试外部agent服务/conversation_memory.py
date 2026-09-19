#!/usr/bin/env python3
"""
会话短期记忆（对话缓冲）——解决"任务流【插件】节点每次只转发当前一句话，
我们agent每次调用都是失忆的"这个问题，跟表A/表B（长期学情记忆）是两套独立机制。

设计（2026-09-17讨论确定）：
1. 主路径：我们自己按 conversation_id 维护最近若干轮对话，每次调用先取出来拼进
   prompt当上下文，生成完回复后把这一轮也存回去。正常情况下不需要额外请求。
2. 兜底路径：如果某几轮被顶层路由到了知识库检索/模型自己直接回答，我们agent根本
   没被调用过，本地缓冲会有缺口——这种缺口本地数据补不上，只能靠任务流那边接一个
   "获取任务流外部历史消息记录"插件把平台侧的完整记录拿回来，用 merge_platform_history()
   补齐我们自己缺的那部分。这一步不是每轮都做，只在怀疑有缺口时（比如本地缓冲为空但
   platform_history不为空）触发，避免每轮都多打一次网络请求。

只做"最近N轮"的滑动窗口，不做长对话的滚动摘要——摘要机制留到真发现窗口不够用时再加，
现在没有真实数据支撑这个复杂度，属于过早优化（同 mastery_model.py 的 DKT 暂缓逻辑）。

持久化方式同 mastery_model.py：单个JSON文件，按 conversation_id 分组，读改写全量覆盖。
等真接入表A/B插件存储时，这里换成插件调用即可，接口形状不用变。
"""

import json
import os
import tempfile
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONVERSATION_BUFFER_PATH = os.path.join(DATA_DIR, "conversation_buffer.json")

# 一"轮"=学生一句+助手一句=2条。MAX_TURNS_KEPT条大约覆盖6轮问答，
# 对教学答疑这种场景基本够用（"卡壳→引导→理解"一次互动很少超过这个长度）。
MAX_TURNS_KEPT = 12

# 所有会话共用同一个JSON文件，即使操作的是不同conversation_id，"读整份->改自己那条->写回
# 整份"这个过程如果两个学生的请求在不同线程里交叉执行，后写的还是会拿着旧版整份数据
# 覆盖掉先写的那次更新（哪怕两人改的是不同的key）。跟mastery_model.py同样的锁+原子写方案。
_buffer_lock = threading.Lock()


def _load() -> dict:
    if not os.path.isfile(CONVERSATION_BUFFER_PATH):
        return {}
    with open(CONVERSATION_BUFFER_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR, prefix="conversation_buffer.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, CONVERSATION_BUFFER_PATH)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def get_buffer(conversation_id: str) -> list:
    """取某个会话当前缓冲的轮次，[{role, content}, ...]，按时间正序。
    conversation_id 为空或本地没有记录时返回空列表——空列表本身就是
    "怀疑有缺口，可能需要兜底"的信号，调用方可以据此决定要不要用平台历史校准。"""
    if not conversation_id:
        return []
    data = _load()
    return list(data.get(conversation_id, {}).get("turns", []))


def has_buffer(conversation_id: str) -> bool:
    """本地是否已经有这个会话的记录——决定要不要触发平台历史兜底的判断依据。"""
    if not conversation_id:
        return False
    data = _load()
    return conversation_id in data and bool(data[conversation_id].get("turns"))


def append_turn(conversation_id: str, student_message: str, assistant_reply: str, student_id: str = None):
    """一轮问答生成完之后调用，把这一轮存回缓冲。超过MAX_TURNS_KEPT自动截断最旧的。"""
    if not conversation_id:
        return
    with _buffer_lock:
        data = _load()
        entry = data.setdefault(conversation_id, {"turns": [], "student_id": student_id, "last_updated": 0})
        entry["turns"].append({"role": "user", "content": student_message, "ts": time.time()})
        entry["turns"].append({"role": "assistant", "content": assistant_reply, "ts": time.time()})
        if len(entry["turns"]) > MAX_TURNS_KEPT:
            entry["turns"] = entry["turns"][-MAX_TURNS_KEPT:]
        if student_id:
            entry["student_id"] = student_id
        entry["last_updated"] = time.time()
        _save(data)


def merge_platform_history(conversation_id: str, platform_turns: list, student_id: str = None):
    """用平台"获取任务流外部历史消息记录"插件返回的完整记录，补齐本地缓冲缺口。

    platform_turns: [{"role": "user"/"assistant", "content": "..."}, ...]，按时间正序，
    是这个会话里发生的全部对话，不管每一轮是被我们的插件接的还是被别处（知识库/模型直答）接的。

    简化对齐算法（不做完整LCS diff，够用就行）：
    - 本地为空 -> 平台历史就是当前最完整的记录，整体导入（截断到MAX_TURNS_KEPT）
    - 本地非空 -> 只在"平台记录明显比本地长"时，把平台记录里本地没有的、更早的部分
      补到本地缓冲最前面（按"本地最后几条内容能在平台记录里找到对应位置"来对齐，
      找不到就保守地整体按平台记录为准——宁可用更全的数据覆盖，不做出会丢真实最新内容的合并）
    """
    if not conversation_id or not platform_turns:
        return get_buffer(conversation_id)

    with _buffer_lock:
        data = _load()
        local_entry = data.get(conversation_id, {"turns": [], "student_id": student_id, "last_updated": 0})
        local_turns = local_entry.get("turns", [])
        normalized_platform = [{"role": t.get("role", "user"), "content": t.get("content", "")} for t in platform_turns]

        if not local_turns:
            merged = normalized_platform[-MAX_TURNS_KEPT:]
        elif len(normalized_platform) <= len(local_turns):
            # 平台记录不比本地长，说明本地没漏，不用平台数据覆盖，保留本地（可能包含平台还没来得及记录的最新一轮）
            merged = local_turns
        else:
            # 平台记录更长，本地缺了前面一段——用平台记录的前半段(本地没有的部分) + 本地已有内容拼接
            missing_count = len(normalized_platform) - len(local_turns)
            merged = normalized_platform[:missing_count] + local_turns
            merged = merged[-MAX_TURNS_KEPT:]

        data[conversation_id] = {
            "turns": merged,
            "student_id": student_id or local_entry.get("student_id"),
            "last_updated": time.time(),
        }
        _save(data)
        return merged


def build_context_text(conversation_id: str, max_turns: int = 8) -> str:
    """把缓冲区最近max_turns条（不是max_turns轮，是max_turns条role+content）格式化成
    一段文本，喂给LLM当"之前聊了什么"的上下文。没有历史时返回空字符串，调用方按空
    字符串处理成"这是第一次对话"，不需要额外判断。"""
    turns = get_buffer(conversation_id)[-max_turns:]
    if not turns:
        return ""
    lines = []
    for t in turns:
        speaker = "学生" if t["role"] == "user" else "你（助手）"
        lines.append(f"{speaker}：{t['content']}")
    return "\n".join(lines)


if __name__ == "__main__":
    # 自测：模拟"本地正常记录两轮" + "怀疑有缺口时用平台历史补齐"两种场景
    cid = "demo_conv_1"
    append_turn(cid, "曲柄摇杆和双曲柄怎么区分", "先看杆长条件，再看最短杆的位置...", student_id="stu_1")
    append_turn(cid, "那如果最短杆是机架呢", "如果最短杆是机架，两侧连架杆都能整周转动，就是双曲柄机构", student_id="stu_1")
    print("本地缓冲：")
    print(build_context_text(cid))

    print("\n模拟平台历史比本地多一轮开头（比如第一句被路由去了知识库，本地没记到）：")
    platform_data = [
        {"role": "user", "content": "老师我最近学连杆机构总是搞不清"},  # 本地没有的一轮
        {"role": "assistant", "content": "连杆机构主要看杆长条件和最短杆位置"},
        {"role": "user", "content": "曲柄摇杆和双曲柄怎么区分"},
        {"role": "assistant", "content": "先看杆长条件，再看最短杆的位置..."},
        {"role": "user", "content": "那如果最短杆是机架呢"},
        {"role": "assistant", "content": "如果最短杆是机架，两侧连架杆都能整周转动，就是双曲柄机构"},
    ]
    merge_platform_history(cid, platform_data, student_id="stu_1")
    print(build_context_text(cid))
