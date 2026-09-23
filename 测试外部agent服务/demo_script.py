#!/usr/bin/env python3
"""
录制演示视频用的"剧本"命中表——跟正常教学逻辑（LLM分类/出题/讲解）完全并行的一条快捷通道。

背景：提交材料要求按固定脚本录一段视频，不能出现LLM每次判断都可能不一样导致的随机性
（这次配了图下次没配、这次问A那次问B）。真实教学场景下这种随机性是合理的（学生每次问法
不完全一样，答案也不该是死的），但录视频这个场景要的是"念一句台词、永远拿到同一个画面"，
两者诉求根本不同，所以不去改主链路的判断逻辑，而是在它前面加一道纯字符串匹配的短路——
命中了直接把剧本里写死的reply/content_id返回，不调用任何LLM、不查题库、不进mastery_model，
从根上消除随机性。

匹配方式：对学生消息做strip()后精确比较SCRIPT里的trigger；精确不命中再退化成"trigger是
message的子串"兜底（照着台词念但多打了几个字/标点也能命中，避免因为一个空格录制失败重来）。
按用户明确要求，不引入"按对话轮次推进"的状态机——同一句trigger在整个剧本里只应该出现一次，
写重复的trigger是脚本编写错误，不是这里要兼容的场景。

content_id留空字符串或"none"就是纯文字回复，不配图；否则跟主链路一样，交给server.py的
_embed_media_markdown()去决定怎么把这个content_id变成学生能看到的链接/图片——真实教材图片
（IMAGE_MANIFEST里的id）、机构库3D模拟器（mechanism_library.LIBRARY里的id，比如"linkage_3d"）
都可以直接填，跟平时出题/讲解走的是同一套渲染规则，不用重新发明一遍。
"""

from typing import Optional

# 每条是 {"trigger": str, "reply": str, "content_id": str} 这样的字典，不用TypedDict/
# list[...]这类新版本类型语法——线上环境Python版本没问题，但本地开发环境装的是较老的
# Anaconda Python（3.7，没有TypedDict），写成纯dict/list能两边都跑。
#
# 按录制顺序往下加即可，谁在前谁在后不影响匹配（匹配只看trigger文本，不看列表顺序/历史）。
# trigger留空的条目会被_validate()挡掉，防止手滑写出一条"匹配任何消息"的空字符串规则。
SCRIPT = [
    # 示例——录制前替换成真实台词，一句台词对应一条固定回复+固定配图/3D：
    # {
    #     "trigger": "帮我讲一下转动副",
    #     "reply": "转动副是……（写死的讲解文案，跟视频脚本逐字对应）",
    #     "content_id": "img_dof_revolute",
    # },
    # {
    #     "trigger": "给我看一下四连杆的3D模型",
    #     "reply": "好，这是四连杆机构的3D模拟器，你可以拖动滑块观察运动规律。",
    #     "content_id": "linkage_3d",
    # },
]


def _validate():
    seen = set()
    for i, step in enumerate(SCRIPT):
        trigger = step.get("trigger", "").strip()
        if not trigger:
            raise ValueError(f"demo_script.SCRIPT[{i}] 的 trigger 不能为空字符串")
        if trigger in seen:
            raise ValueError(f"demo_script.SCRIPT 里 trigger 重复：{trigger!r}，同一句台词只应该出现一次")
        seen.add(trigger)


_validate()


def match_script(message: str) -> Optional[dict]:
    """精确匹配优先，退化成子串匹配兜底。不命中返回None，调用方按原有逻辑继续走。"""
    text = (message or "").strip()
    if not text:
        return None

    for step in SCRIPT:
        if step["trigger"] == text:
            return step

    for step in SCRIPT:
        if step["trigger"] in text:
            return step

    return None
