import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send_json({"ok": True, "msg": "test agent server alive", "ts": time.time()})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            data = {"_raw": raw.decode("utf-8", errors="replace")}

        user_msg = data.get("message") or data.get("query") or data.get("input") or ""
        reply = f"[本地测试agent已收到] 你说的是: {user_msg!r} | 收到时间戳: {time.time():.0f}"
        print(f"[{time.strftime('%H:%M:%S')}] POST /agent body={data}")
        self._send_json({"reply": reply})

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    port = 8787
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"test agent server listening on 0.0.0.0:{port}")
    server.serve_forever()
