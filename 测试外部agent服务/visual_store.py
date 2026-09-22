#!/usr/bin/env python3
"""
出题时LLM动态决定的视觉内容（选中的机构库content_id+抽取的参数，或者runtime生成的
scene JSON）存在这里，用一个短id占位——因为/viewer是学生这边【嵌入】节点稍后单独发起
的一次GET请求，跟出题时那次LLM调用不是同一个HTTP请求，参数/JSON没地方带，只能先存起来
用id取。跟conversation_memory的pending_question是类似的"先存状态、稍后按id/student_id
取回"的思路，但这里的key是随机id而不是student_id，因为同一学生可能同时挂着多道题的
图（不常见但没必要假设不会发生）。

进程内存储，重启进程会清空——可以接受：这类视觉内容只在"刚出的这道题"的展示窗口里有用，
不需要跨重启持久化，跟pending_question目前的实现（也是进程内存，见conversation_memory.py）
一致，没必要为了这个引入额外的存储依赖。
"""

import secrets
from typing import Optional

_STORE = {}  # type: dict


def store_visual(payload: dict) -> str:
    """存一份动态视觉内容，返回content_id（格式v_<12位hex>，跟quiz_/linkage_3d等
    固定前缀区分开，server.py靠这个前缀识别该走这条动态查找路径）。"""
    content_id = f"v_{secrets.token_hex(6)}"
    _STORE[content_id] = payload
    return content_id


def get_visual(content_id: str) -> Optional[dict]:
    return _STORE.get(content_id)
