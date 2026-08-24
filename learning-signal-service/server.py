"""表A/表B 的本地 HTTP API 服务，供任务流"插件"节点调用。

路由:
    POST /signals              写入一条学习信号(表A)，同时更新对应画像(表B)
        body: {student_id, knowledge_point_id, signal_type, polarity, evidence?}
    GET  /signals?student_id=&knowledge_point_id=(可选)
        返回表A原始记录
    GET  /profile?student_id=&knowledge_point_id=
        返回单个知识点的画像(表B)
    GET  /profiles?student_id=
        返回该学生所有知识点的画像(表B)，用于 Open Learner Model 查询
    GET  /health

仅用标准库(http.server + sqlite3)实现，本地运行不需要额外安装依赖。

鉴权：除 /health 外的所有接口都要求请求头 `X-Api-Key` 匹配服务端密钥。
密钥来源：环境变量 LEARNING_SIGNAL_API_KEY，没设置的话首次启动会自动生成一个
并写入 api_key.txt（该文件不进git，见 .gitignore），之后重启会复用同一个值。
"""
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import db

DB_PATH = "data/signals.db"
API_KEY_FILE = "api_key.txt"


def load_api_key() -> str:
    env_key = os.environ.get("LEARNING_SIGNAL_API_KEY")
    if env_key:
        return env_key
    if os.path.exists(API_KEY_FILE):
        with open(API_KEY_FILE, "r", encoding="utf-8") as f:
            key = f.read().strip()
            if key:
                return key
    key = secrets.token_urlsafe(32)
    with open(API_KEY_FILE, "w", encoding="utf-8") as f:
        f.write(key)
    return key


API_KEY = load_api_key()


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code, message):
        self._send_json({"ok": False, "error": message}, code)

    def _authorized(self) -> bool:
        provided = self.headers.get("X-Api-Key", "")
        return secrets.compare_digest(provided, API_KEY)

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path != "/health" and not self._authorized():
            return self._error(401, "invalid or missing X-Api-Key")
        conn = db.get_conn(DB_PATH)
        try:
            if parsed.path == "/health":
                self._send_json({"ok": True})
            elif parsed.path == "/signals":
                student_id = (qs.get("student_id") or [None])[0]
                if not student_id:
                    return self._error(400, "student_id is required")
                kp_id = (qs.get("knowledge_point_id") or [None])[0]
                self._send_json({"ok": True, "data": db.get_signals(conn, student_id, kp_id)})
            elif parsed.path == "/profile":
                student_id = (qs.get("student_id") or [None])[0]
                kp_id = (qs.get("knowledge_point_id") or [None])[0]
                if not student_id or not kp_id:
                    return self._error(400, "student_id and knowledge_point_id are required")
                self._send_json({"ok": True, "data": db.get_profile(conn, student_id, kp_id)})
            elif parsed.path == "/profiles":
                student_id = (qs.get("student_id") or [None])[0]
                if not student_id:
                    return self._error(400, "student_id is required")
                self._send_json({"ok": True, "data": db.get_profiles_for_student(conn, student_id)})
            else:
                self._error(404, "not found")
        finally:
            conn.close()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/signals":
            return self._error(404, "not found")
        if not self._authorized():
            return self._error(401, "invalid or missing X-Api-Key")

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return self._error(400, "invalid JSON body")

        required = ("student_id", "knowledge_point_id", "signal_type", "polarity")
        missing = [k for k in required if not payload.get(k)]
        if missing:
            return self._error(400, f"missing fields: {', '.join(missing)}")

        conn = db.get_conn(DB_PATH)
        try:
            result = db.insert_signal(
                conn,
                student_id=payload["student_id"],
                knowledge_point_id=payload["knowledge_point_id"],
                signal_type=payload["signal_type"],
                polarity=payload["polarity"],
                evidence=payload.get("evidence", ""),
            )
            self._send_json({"ok": True, "data": result}, 201)
        except ValueError as e:
            self._error(400, str(e))
        finally:
            conn.close()

    def log_message(self, fmt, *args):
        pass


def run(port: int = 8788):
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"learning-signal-service listening on 0.0.0.0:{port}")
    print(f"API key (put this in the plugin's X-Api-Key header): {API_KEY}")
    server.serve_forever()


if __name__ == "__main__":
    run()
