#!/usr/bin/env python3
"""
机械小助手 - 外部agent测试后端。

架构：robot.chaoxing.com 任务流【插件】节点 POST /agent 过来 -> 这里做
"知识点分类 -> 讲解生成+媒体决策(LLM) -> 返回reply+content_id"
-> 任务流【嵌入】节点用 content_id 拼 /viewer?content=xxx 的iframe地址动态渲染。

分类逻辑见 knowledge_base.py，LLM调用（含API key未配时的占位mock）见 llm_client.py。
"""

import json
import logging
import mimetypes
import os
from logging.handlers import RotatingFileHandler
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from knowledge_base import classify_knowledge_point, KNOWLEDGE_POINTS
from llm_client import generate_explanation_and_media
from mastery_model import record_answer, record_qualitative_signal, get_profile, get_due_for_review, get_question
from signal_log import get_signals, SIGNAL_TYPES, POLARITIES
import conversation_memory
import quiz

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SIM_DIR = os.path.join(BASE_DIR, "..", "四连杆3D模拟器")
TEXTBOOK_IMG_DIR = os.path.join(BASE_DIR, "..", "教材图片")
QUIZ_DIR = os.path.join(BASE_DIR, "..", "题库")
QUIZ_IMAGES_DIR = os.path.join(QUIZ_DIR, "images")
QUIZ_BANK_PATH = os.path.join(QUIZ_DIR, "题库.json")

# 请求/响应审计日志——用来排查"任务流插件节点实际发过来的内容 vs 我们本地curl测试"
# 之间的差异（比如message被截断、conversation_id/student_id绑错变量等），这类问题只看
# journalctl的access log（只有路径和状态码）根本查不出来，必须把请求体和分类结果落盘。
# 日志文件本身跟其他 data/*.log 一样走 .gitignore（测试外部agent服务/*.log），不进版本库，
# 进版本库的只有这段记录逻辑代码本身。
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
audit_logger = logging.getLogger("agent_audit")
audit_logger.setLevel(logging.INFO)
_audit_handler = RotatingFileHandler(
    os.path.join(LOG_DIR, "agent_audit.log"), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_audit_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
audit_logger.addHandler(_audit_handler)
audit_logger.propagate = False  # 不重复往 journalctl 里再灌一份，那边已经有 log_message() 的访问日志


def _log_agent_call(direction, payload):
    """direction: 'in'（任务流插件节点发来的原始请求体）或 'out'（我们回给它的响应体）。
    整个payload原样落盘成一行JSON，不做字段裁剪——排查问题时最怕的就是恰好少记了那个关键字段。"""
    try:
        audit_logger.info("%s %s", direction, json.dumps(payload, ensure_ascii=False))
    except Exception as e:
        audit_logger.info("%s <log serialization failed: %s>", direction, e)


def _load_quiz_bank():
    """题库.json里的题图（本地提取的161张+超星CDN外链）要在出题时能展示出来，
    content_id格式约定为 quiz_<question_id>_<image_index>，比如 quiz_q_0040_0。
    这里启动时加载一次到内存做id->题目的查找表，避免每次请求都读文件。"""
    try:
        with open(QUIZ_BANK_PATH, encoding="utf-8") as f:
            bank = json.load(f)
        return {item["id"]: item for item in bank}
    except FileNotFoundError:
        return {}


QUIZ_BANK = _load_quiz_bank()

# content_id -> 教材原图文件名（相对 TEXTBOOK_IMG_DIR）。只收录这些是真实存在的素材，
# 防止 LLM 幻觉出的 id 被当真去读文件。对应关系见 [图片-知识点映射表.md](../教材图片/图片-知识点映射表.md)，
# 2026-09-17 从"只有第三章3张图"扩展到24张（覆盖9个知识点），file字段带上章节子目录。
IMAGE_MANIFEST = {
    # 第三章·连杆机构
    "kp_linkage_diagram": {
        "file": "第三章图/image1.png",
        "title": "四连杆机构基本结构简图",
    },
    "kp_quick_return_diagram": {
        "file": "第三章图/image2.png",
        "title": "急回特性示意图（极限位置C1/C2、快行程/慢行程）",
    },
    "kp_pressure_angle_diagram": {
        "file": "第三章图/image3.png",
        "title": "压力角与传动角示意图",
    },
    # 第二章·运动副
    "img_dof_revolute": {"file": "第二章图/image1.png", "title": "转动副示意图"},
    "img_dof_prismatic": {"file": "第二章图/image2.png", "title": "移动副示意图"},
    "img_dof_higher_pair": {"file": "第二章图/image3.png", "title": "高副示意图"},
    # 第四章·凸轮机构
    "img_cam_pressure_angle": {"file": "第四章图/image1.png", "title": "直动从动件盘形凸轮机构的压力角"},
    # 第五章·齿轮传动
    "img_gear_involute_separable": {"file": "第五章图/image1.png", "title": "渐开线齿廓啮合具有可分性"},
    "img_gear_tooth_parts": {"file": "第五章图/image2.png", "title": "外齿轮各部分名称"},
    # 第七章·间歇运动机构
    "img_ratchet_mechanism": {"file": "第七章图/image1.png", "title": "外啮合棘轮机构"},
    "img_geneva_mechanism": {"file": "第七章图/image2.png", "title": "单圆销槽轮机构"},
    # 第十章·键、销连接
    "img_key_flat": {"file": "第十章图/image1.png", "title": "普通平键"},
    "img_key_guide": {"file": "第十章图/image2.png", "title": "导向平键"},
    "img_key_sliding": {"file": "第十章图/image3.png", "title": "滑键"},
    "img_key_woodruff": {"file": "第十章图/image4.png", "title": "半圆键"},
    "img_pin_cylindrical": {"file": "第十章图/image5.png", "title": "圆柱销"},
    "img_pin_taper": {"file": "第十章图/image6.png", "title": "圆锥销"},
    "img_pin_cotter": {"file": "第十章图/image7.png", "title": "开口销"},
    # 第十二章·蜗杆传动
    "img_worm_gear_force": {"file": "第十二章图/image1.png", "title": "蜗杆传动的受力分析"},
    # 第十三章·带传动/链传动
    "img_belt_friction": {"file": "第十三章图/image1.png", "title": "摩擦型带传动"},
    "img_belt_meshing": {"file": "第十三章图/image2.png", "title": "啮合型带传动"},
    "img_chain_drive": {"file": "第十三章图/image3.png", "title": "链传动"},
    "img_chain_roller_structure": {"file": "第十三章图/image4.png", "title": "滚子链的结构图"},
    "img_chain_silent": {"file": "第十三章图/image5.png", "title": "齿形链"},
}


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status, html):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, full_path):
        if not os.path.isfile(full_path):
            self._send_json(404, {"error": "not found"})
            return
        ctype, _ = mimetypes.guess_type(full_path)
        ctype = ctype or "application/octet-stream"
        with open(full_path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static_under(self, base_dir, rel_path):
        safe_path = os.path.normpath(rel_path).lstrip("/\\")
        full_path = os.path.normpath(os.path.join(base_dir, safe_path))
        if not full_path.startswith(os.path.normpath(base_dir)):
            self._send_json(404, {"error": "not found"})
            return
        self._send_file(full_path)

    def _render_quiz_image(self, content_id):
        """content_id格式：quiz_<question_id>_<image_index>，如 quiz_q_0040_0。
        question_id本身带下划线（如q_0040），所以从右边切一次分离出index。"""
        rest = content_id[len("quiz_"):]
        question_id, _, idx_str = rest.rpartition("_")
        question = QUIZ_BANK.get(question_id)
        if not question or not idx_str.isdigit():
            self._send_json(404, {"error": "unknown quiz image id"})
            return
        images = question.get("stem_images", [])
        idx = int(idx_str)
        if idx >= len(images):
            self._send_json(404, {"error": "image index out of range"})
            return
        img = images[idx]

        if img["type"] == "url":
            # 超星CDN外链本身就是公网可访问的图片地址，直接跳转过去即可，不需要我们代理
            self.send_response(302)
            self.send_header("Location", img["value"])
            self.end_headers()
            return

        if img["type"] == "local_file":
            filename = os.path.basename(img["value"])
            title = f"题目 {question_id} 配图"
            html = f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
body {{ margin:0; font-family:-apple-system,sans-serif; background:#14161c; color:#fff;
  display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; }}
img {{ max-width:90%; max-height:80vh; background:#fff; border-radius:8px; padding:8px; }}
.tag {{ font-size:11px; opacity:.6; margin-top:6px; }}
</style></head>
<body>
  <img src="/quiz-media/{filename}" alt="{title}">
  <div class="tag">{title} · content_id={content_id}</div>
</body></html>"""
            self._send_html(200, html)
            return

        self._send_json(404, {"error": "image type not displayable"})

    # ------------------------------------------------------------------
    # POST /agent：任务流【插件】节点调这个接口
    # ------------------------------------------------------------------
    def do_POST(self):
        if self.path == "/answer":
            self._handle_answer()
            return
        if self.path == "/signal":
            self._handle_signal()
            return
        if self.path != "/agent":
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        _log_agent_call("in_raw", {"content_length": length, "raw": raw.decode("utf-8", errors="replace")})
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            data = {}

        message = data.get("message", "")
        # conversation_id/student_id 都是可选的：任务流【插件】节点的"输入"要额外绑定
        # {{开始-INNER_conversationId}}/{{开始-INNER_userId}} 才会真正传过来；没传时退化
        # 成无记忆的旧行为（向后兼容，不会因为这两个字段缺失就报错断链路）。
        conversation_id = data.get("conversation_id", "")
        student_id = data.get("student_id", "")
        # platform_history：任务流那边如果接了"获取任务流外部历史消息记录"插件，可以把
        # 结果的 data 数组原样传进来，仅在"怀疑本地缓冲有缺口"时用于补齐（见 conversation_memory.py
        # 顶部说明）。这里不强制要求每次都传，传了才会触发一次校准合并。
        platform_history = data.get("platform_history") or None

        if platform_history:
            conversation_memory.merge_platform_history(conversation_id, platform_history, student_id)
        conversation_context = conversation_memory.build_context_text(conversation_id)

        # ------------------------------------------------------------------
        # 车道A/C「出题-判分」分支：不走"在超星任务流里另搭判断节点"这条路，出题和收
        # 学生作答复用的是同一条 /agent 转发链路（见 quiz.py 模块顶部说明）。这段必须
        # 放在"知识点讲解"分支之前判断——学生这一轮如果是在回答上一轮出的题，内容本身
        # 大概率匹配不到任何知识点关键词（比如学生就回一个"A"或"对"），会被误判成
        # "问题不在覆盖范围内"，所以要先看有没有挂着一道等答案的题，再决定走哪条路。
        # ------------------------------------------------------------------
        pending = conversation_memory.get_pending_question(conversation_id)
        if pending:
            q = get_question(pending["question_id"])
            if q is None:
                # 极端情况：题库文件被换了/题目id失效，防御性地清掉这个挂死的状态，
                # 避免以后每一轮都卡在这个查不到的pending_question上
                conversation_memory.clear_pending_question(conversation_id)
            else:
                correct = quiz.judge_answer(q, message)
                record_answer(student_id or "匿名学生", q["id"], correct)
                reply = quiz.format_feedback(q, correct)
                conversation_memory.clear_pending_question(conversation_id)
                conversation_memory.append_turn(conversation_id, message, reply, student_id)
                response_payload = {
                    "reply": reply,
                    "content_id": "none",
                    "knowledge_point": q.get("knowledge_point_id"),
                }
                _log_agent_call("in_parsed", {
                    "message": message, "conversation_id": conversation_id, "student_id": student_id,
                    "quiz_judge": {"question_id": q["id"], "correct": correct},
                })
                _log_agent_call("out", response_payload)
                self._send_json(200, response_payload)
                return

        if quiz.is_quiz_intent(message):
            q = quiz.pick_question(student_id)
            if q is None:
                reply = "题库里暂时没有能自动判分的题可以出给你，先聊点别的吧。"
                content_id = "none"
                knowledge_point_id = None
            else:
                reply = quiz.format_question_for_display(q)
                content_id = quiz.question_display_content_id(q)
                knowledge_point_id = q.get("knowledge_point_id")
                # 记下这道题，等学生下一轮作答时才能判分——正确答案原样存题库里的格式，
                # judge_answer() 按question_type知道该怎么解读这个字段
                conversation_memory.set_pending_question(conversation_id, q["id"], q["type"], q.get("answer"))
            conversation_memory.append_turn(conversation_id, message, reply, student_id)
            response_payload = {
                "reply": reply,
                "content_id": content_id,
                "knowledge_point": knowledge_point_id,
            }
            _log_agent_call("in_parsed", {
                "message": message, "conversation_id": conversation_id, "student_id": student_id,
                "quiz_asked": response_payload["knowledge_point"],
            })
            _log_agent_call("out", response_payload)
            self._send_json(200, response_payload)
            return

        kp = classify_knowledge_point(message)
        if kp is None:
            reply = "这个问题好像不在《机械设计基础》已覆盖的知识点范围内，能换个说法或者说明具体想问哪部分吗？"
            conversation_memory.append_turn(conversation_id, message, reply, student_id)
            response_payload = {
                "reply": reply,
                "content_id": "none",
                "knowledge_point": None,
            }
            _log_agent_call("in_parsed", {
                "message": message, "conversation_id": conversation_id, "student_id": student_id,
                "has_platform_history": bool(platform_history), "classified_kp": None,
            })
            _log_agent_call("out", response_payload)
            self._send_json(200, response_payload)
            return

        # 学情字段跟表B真正联动：按 student_id + 本轮命中的知识点id，去表B里查这个学生在
        # 这个知识点上的当前掌握状态。放在这里（分类出kp之后）而不是分类之前，是因为表B是
        # 按"学生-知识点"这个组合维度存的，没有具体kp就查不出针对性的那一行；student_id为空
        # （没绑定系统变量，或访客未登录）时退化成"未学"，不报错断链路，跟conversation_id
        # 的向后兼容策略一致。detail_level/encourage_level 表B目前没有对应字段，暂时保持默认值。
        mastery_level = "未学"
        if student_id:
            profile_rows = get_profile(student_id).get("knowledge_points", [])
            matched_row = next((r for r in profile_rows if r["knowledge_point_id"] == kp.id), None)
            if matched_row:
                mastery_level = matched_row["mastery_state"]
        student_state = {
            "mastery_level": mastery_level,
            "detail_level": data.get("detail_level", "中"),
            "encourage_level": data.get("encourage_level", "中"),
        }

        result = generate_explanation_and_media(kp, message, student_state, conversation_context)
        media = result.get("media", {}) or {}
        reply = result.get("explanation", "")
        conversation_memory.append_turn(conversation_id, message, reply, student_id)
        response_payload = {
            "reply": reply,
            "content_id": media.get("content_id", "none"),
            "media_reason": media.get("reason", ""),
            "knowledge_point": kp.id,
        }
        _log_agent_call("in_parsed", {
            "message": message, "conversation_id": conversation_id, "student_id": student_id,
            "has_platform_history": bool(platform_history), "classified_kp": kp.id,
            "mastery_level": mastery_level,
        })
        _log_agent_call("out", response_payload)
        self._send_json(200, response_payload)

    # ------------------------------------------------------------------
    # POST /answer：车道A/C的判断节点判完对错后调这个接口，按CDM(Q矩阵)+Elo
    # 更新表B（见 mastery_model.py，对应 执行计划.md "表B更新规则 v2"）
    # ------------------------------------------------------------------
    def _handle_answer(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            data = {}

        student_id = data.get("student_id")
        question_id = data.get("question_id")
        correct = data.get("correct")
        if not student_id or not question_id or not isinstance(correct, bool):
            self._send_json(400, {"error": "need student_id, question_id, correct(bool)"})
            return

        result = record_answer(student_id, question_id, correct)
        self._send_json(200, result)

    # ------------------------------------------------------------------
    # POST /signal：车道B(主动学习)/车道D(可视化探索)之前完全不产生数据，
    # 靠这个接口接入统一的表A/表B——自报/提问/自我解释/可视化探索四种非做题信号
    # 都从这里进来（做题信号走 /answer，因为需要题目难度信息做Elo更新）
    # ------------------------------------------------------------------
    def _handle_signal(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            data = {}

        student_id = data.get("student_id")
        knowledge_point_id = data.get("knowledge_point_id")
        signal_type = data.get("signal_type")
        polarity = data.get("polarity")
        evidence = data.get("evidence", "")

        if not student_id or not knowledge_point_id:
            self._send_json(400, {"error": "need student_id, knowledge_point_id"})
            return
        if signal_type not in SIGNAL_TYPES - {"做题"}:
            self._send_json(400, {"error": f"signal_type must be one of {SIGNAL_TYPES - {'做题'}}（做题信号请用 /answer）"})
            return
        if polarity not in POLARITIES:
            self._send_json(400, {"error": f"polarity must be one of {POLARITIES}"})
            return

        try:
            result = record_qualitative_signal(student_id, knowledge_point_id, signal_type, polarity, evidence)
        except ValueError as e:
            self._send_json(400, {"error": str(e)})
            return
        self._send_json(200, result)

    # ------------------------------------------------------------------
    # GET：/viewer 渲染、/3d 静态托管3D模拟器、/media 静态托管教材配图、
    # /profile 表B读接口（GET /profile?student_id=xxx）、
    # /signals 表A原始信号读接口（GET /signals?student_id=xxx&knowledge_point_id=可选）
    # ------------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/profile":
            qs = parse_qs(parsed.query)
            student_id = qs.get("student_id", [None])[0]
            if not student_id:
                self._send_json(400, {"error": "need student_id"})
                return
            self._send_json(200, get_profile(student_id))
            return

        if parsed.path == "/signals":
            qs = parse_qs(parsed.query)
            student_id = qs.get("student_id", [None])[0]
            knowledge_point_id = qs.get("knowledge_point_id", [None])[0]
            if not student_id:
                self._send_json(400, {"error": "need student_id"})
                return
            self._send_json(200, {
                "student_id": student_id,
                "signals": get_signals(student_id, knowledge_point_id),
            })
            return

        if parsed.path == "/due_review":
            # 对应 表B更新规则v3(遗忘曲线) 里借SM-2思路判断"该不该提醒复习"，
            # 给5.2教师端学情推送/车道C自测触发器用
            qs = parse_qs(parsed.query)
            student_id = qs.get("student_id", [None])[0]
            if not student_id:
                self._send_json(400, {"error": "need student_id"})
                return
            self._send_json(200, get_due_for_review(student_id))
            return

        if parsed.path == "/3d" or parsed.path == "/3d/":
            self._send_static_under(SIM_DIR, "index.html")
            return
        if parsed.path.startswith("/3d/"):
            self._send_static_under(SIM_DIR, parsed.path[len("/3d/"):])
            return

        if parsed.path.startswith("/media/"):
            content_id = parsed.path[len("/media/"):]
            item = IMAGE_MANIFEST.get(content_id)
            if not item:
                self._send_json(404, {"error": "unknown media id"})
                return
            self._send_static_under(TEXTBOOK_IMG_DIR, item["file"])
            return

        if parsed.path.startswith("/quiz-media/"):
            # 只服务题库/images/下真实存在的文件，靠 _send_static_under 的路径规范化防止目录穿越
            filename = parsed.path[len("/quiz-media/"):]
            self._send_static_under(QUIZ_IMAGES_DIR, filename)
            return

        if parsed.path == "/viewer":
            qs = parse_qs(parsed.query)
            content_id = qs.get("content", ["none"])[0]

            if content_id == "linkage_3d":
                self.send_response(302)
                self.send_header("Location", "/3d/index.html")
                self.end_headers()
                return

            if content_id.startswith("quiz_"):
                self._render_quiz_image(content_id)
                return

            if content_id in IMAGE_MANIFEST:
                title = IMAGE_MANIFEST[content_id]["title"]
                html = f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
body {{ margin:0; font-family:-apple-system,sans-serif; background:#14161c; color:#fff;
  display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; }}
img {{ max-width:85%; max-height:70vh; background:#fff; border-radius:8px; padding:12px; }}
h1 {{ font-size:14px; font-weight:500; margin:14px 0 4px; }}
.tag {{ font-size:11px; opacity:.6; margin-top:6px; }}
</style></head>
<body>
  <img src="/media/{content_id}" alt="{title}">
  <h1>{title}</h1>
  <div class="tag">由 agent 动态决定展示内容：content_id={content_id}</div>
</body></html>"""
                self._send_html(200, html)
                return

            # content_id == "none" 或其他未识别值：不配图的兜底页
            html = """<!doctype html>
<html><head><meta charset="utf-8"><style>
body { margin:0; font-family:-apple-system,sans-serif; background:#14161c; color:#7d818c;
  display:flex; align-items:center; justify-content:center; height:100vh; font-size:13px; }
</style></head>
<body>（本轮回答无需配图）</body></html>"""
            self._send_html(200, html)
            return

        self._send_json(200, {
            "status": "ok",
            "note": "POST /agent with {\"message\": ...}",
            "knowledge_points": [kp.id for kp in KNOWLEDGE_POINTS],
        })

    def log_message(self, fmt, *args):
        print("[server]", fmt % args)


if __name__ == "__main__":
    port = 8899
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"listening on :{port}")
    httpd.serve_forever()
