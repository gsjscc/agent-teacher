#!/usr/bin/env python3
"""
出题时LLM动态决定的视觉内容（选中的机构库content_id+抽取的参数，或者runtime生成的
scene JSON）存在这里，用一个短id占位——因为/viewer是学生这边【嵌入】节点稍后单独发起
的一次GET请求，跟出题时那次LLM调用不是同一个HTTP请求，参数/JSON没地方带，只能先存起来
用id取。跟conversation_memory的pending_question是类似的"先存状态、稍后按id/student_id
取回"的思路，但这里的key是随机id而不是student_id，因为同一学生可能同时挂着多道题的
图（不常见但没必要假设不会发生）。

落盘持久化（而不是纯进程内存）：实测发现服务器重启（比如部署新代码）会导致之前挂在
visual_store里的content_id全部失效——已经发给学生、还显示在聊天记录里的3D嵌入链接，
重启后再打开就是"找不到内容"，表现成一直空白，跟"平台不支持嵌入渲染"这个真正的bug
长得一模一样，排查时把两者搞混过一次。这类历史消息里的链接可能过很久还会被学生翻出来点，
不能假设"用完即弃"，所以改成跟mastery_model.py同样的本地JSON文件+原子写方案。
"""

import json
import os
import secrets
import tempfile
import threading
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
VISUAL_STORE_PATH = os.path.join(DATA_DIR, "visual_store.json")

_lock = threading.Lock()


def _load_json(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: str, data: dict):
    """原子写入，做法和理由跟mastery_model.py里的_save_json完全一致：先写临时文件再
    os.replace()换名，避免进程被杀在写到一半时留下截断的坏JSON。"""
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


def store_visual(payload: dict) -> str:
    """存一份动态视觉内容，返回content_id（格式v_<12位hex>，跟quiz_/linkage_3d等
    固定前缀区分开，server.py靠这个前缀识别该走这条动态查找路径）。"""
    content_id = f"v_{secrets.token_hex(6)}"
    with _lock:
        store = _load_json(VISUAL_STORE_PATH)
        store[content_id] = payload
        _save_json(VISUAL_STORE_PATH, store)
    return content_id


def get_visual(content_id: str) -> Optional[dict]:
    with _lock:
        store = _load_json(VISUAL_STORE_PATH)
    return store.get(content_id)
