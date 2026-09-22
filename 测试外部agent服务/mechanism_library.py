#!/usr/bin/env python3
"""
离线做好、检查过、存进仓库的机构3D模拟器目录——server.py和llm_client.py共同依赖这份注册表，
但彼此不直接依赖对方，保持quiz.py模块docstring里提到的"server.py只依赖quiz.py"这种边界原则：
llm_client.py用它拼给LLM看的"封闭菜单"+校验LLM选的content_id/参数没有幻觉，server.py用它
把content_id映射到磁盘上的模拟器文件夹、并把LLM抽取出的参数钳制在滑块允许范围内再拼进
iframe地址——两边都不该各自维护一份，写错一个数字就会关联不上或者把动画搞崩。

每个条目：
  folder: 相对项目根目录的模拟器文件夹路径（index.html所在目录）
  title: 给LLM看的机构名称，帮它判断题目是否匹配
  params: {滑块id: (min, max)}，直接抄自各模拟器index.html里<input type="range">的min/max，
          LLM抽取出的数值会按这个范围钳制，抽不出的字段就不传，模拟器自己有默认值兜底
"""

LIBRARY = {
    "linkage_3d": {
        "folder": "四连杆3D模拟器",
        "title": "四连杆机构（杆长条件、连杆运动轨迹）",
        "params": {"d": (0.6, 3), "a": (0.3, 2.5), "b": (0.3, 2.5), "c": (0.3, 2.5)},
    },
    "gear_drive": {
        "folder": "3d动画/第五章_齿轮传动",
        "title": "一对外啮合直齿圆柱齿轮传动（齿数、模数、传动比、中心距）",
        "params": {"z1": (10, 30), "z2": (10, 40), "m": (0.15, 0.35), "speed": (0.3, 2.5)},
    },
    "gear_train": {
        "folder": "3d动画/第六章_轮系",
        "title": "行星轮系（太阳轮、行星轮、传动比）",
        "params": {"zs": (10, 24), "zp": (8, 20), "speed": (0.3, 2.5)},
    },
    "intermittent_motion": {
        "folder": "3d动画/第七章_间歇运动机构",
        "title": "间歇运动机构（槽轮机构/棘轮机构）",
        "params": {"n": (4, 8), "speed": (0.3, 2)},
    },
    "thread_key_pin": {
        "folder": "3d动画/第十章_螺纹键销连接",
        "title": "螺纹连接/键连接/销连接（装配与分解示意）",
        "params": {"explode": (0, 1)},
    },
    "worm_drive": {
        "folder": "3d动画/第十二章_蜗杆传动",
        "title": "蜗杆蜗轮传动（蜗杆头数、蜗轮齿数、传动比）",
        "params": {"z1": (1, 4), "z2": (20, 60), "speed": (0.5, 3)},
    },
    "belt_chain_drive": {
        "folder": "3d动画/第十三章_带链传动",
        "title": "带传动/链传动（带轮半径、打滑率）",
        "params": {"r1": (0.3, 0.7), "r2": (0.3, 1.0), "slip": (0, 20), "speed": (0.3, 2.5)},
    },
    "rolling_bearing": {
        "folder": "3d动画/第十五章_滚动轴承",
        "title": "滚动轴承（滚动体公转与自转）",
        "params": {"n": (6, 14), "speed": (0.3, 3)},
    },
    "sliding_bearing": {
        "folder": "3d动画/第十六章_滑动轴承",
        "title": "滑动轴承（偏心率、油膜）",
        "params": {"eps": (0, 0.9), "speed": (0.3, 2.5)},
    },
    "clutch": {
        "folder": "3d动画/第十七章_离合器",
        "title": "离合器（接合/分离、摩擦式打滑过渡）",
        "params": {"speed": (0.5, 3)},
    },
    "spring": {
        "folder": "3d动画/第十八章_弹簧",
        "title": "圆柱螺旋弹簧（压缩/伸长、圈数）",
        "params": {"h0": (1.5, 2.5), "n": (4, 10), "speed": (0.3, 2)},
    },
    "cam_mechanism": {
        "folder": "3d动画/第四章_凸轮机构",
        "title": "凸轮机构（推程-远休-回程-近休运动规律、从动件位移）",
        "params": {"r0": (0.5, 1.2), "h": (0.2, 1.0), "speed": (0.2, 2)},
    },
}


def menu_text() -> str:
    """拼给LLM看的封闭菜单：content_id、标题、可选参数名+范围。LLM只能从这里面选，
    选不中任何一条就必须老实说"不匹配"，不能编一个不存在的content_id。"""
    lines = []
    for content_id, entry in LIBRARY.items():
        param_desc = "、".join(f"{name}∈[{lo},{hi}]" for name, (lo, hi) in entry["params"].items())
        lines.append(f"- {content_id}：{entry['title']}（可选参数：{param_desc}）")
    return "\n".join(lines)


def clamp_params(content_id: str, raw_params: dict) -> dict:
    """把LLM抽取出的参数钳制在该机构滑块允许的min/max范围内，只保留注册表里认识的参数名——
    防止LLM给一个不存在的参数名或者超出滑块范围的值，把动画渲染坏或者干脆没反应。"""
    entry = LIBRARY.get(content_id)
    if not entry or not isinstance(raw_params, dict):
        return {}
    clamped = {}
    for name, (lo, hi) in entry["params"].items():
        if name not in raw_params:
            continue
        try:
            value = float(raw_params[name])
        except (TypeError, ValueError):
            continue
        clamped[name] = max(lo, min(hi, value))
    return clamped
