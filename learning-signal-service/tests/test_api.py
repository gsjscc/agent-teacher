"""HTTP API 层的集成测试：起一个临时端口的真实 server，用标准库 urllib 打请求。"""
import json
import os
import sys
import threading
import time
import unittest
from http.server import HTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_API_KEY = "test-key-do-not-use-in-prod"
os.environ["LEARNING_SIGNAL_API_KEY"] = TEST_API_KEY

import server as server_module

TEST_PORT = 8799
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"


def request(method, path, body=None, api_key=TEST_API_KEY):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(f"{BASE_URL}{path}", data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if api_key is not None:
        req.add_header("X-Api-Key", api_key)
    try:
        with urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_db_path = os.path.join(os.path.dirname(__file__), "_test_api.db")
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
        server_module.DB_PATH = test_db_path
        cls.httpd = HTTPServer(("127.0.0.1", TEST_PORT), server_module.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.thread.join()
        if os.path.exists(server_module.DB_PATH):
            os.remove(server_module.DB_PATH)

    def test_health_does_not_require_api_key(self):
        status, body = request("GET", "/health", api_key=None)
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    def test_missing_api_key_returns_401(self):
        status, body = request("GET", "/profiles?student_id=stu_api", api_key=None)
        self.assertEqual(status, 401)
        self.assertFalse(body["ok"])

    def test_wrong_api_key_returns_401(self):
        status, body = request(
            "POST",
            "/signals",
            {"student_id": "x", "knowledge_point_id": "y", "signal_type": "quiz_result", "polarity": "positive"},
            api_key="wrong-key",
        )
        self.assertEqual(status, 401)
        self.assertFalse(body["ok"])

    def test_post_signal_then_read_profile(self):
        status, body = request(
            "POST",
            "/signals",
            {
                "student_id": "stu_api",
                "knowledge_point_id": "kp_lever",
                "signal_type": "self_report",
                "polarity": "positive",
                "evidence": "我理解了平面连杆机构的自由度公式",
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(body["data"]["profile"]["score"], 1.0)

        status, body = request("GET", "/profile?student_id=stu_api&knowledge_point_id=kp_lever")
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["state"], "学习中")

    def test_missing_fields_returns_400(self):
        status, body = request("POST", "/signals", {"student_id": "stu_api"})
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])

    def test_profiles_lists_all_knowledge_points_for_student(self):
        request(
            "POST",
            "/signals",
            {
                "student_id": "stu_multi",
                "knowledge_point_id": "kp_a",
                "signal_type": "quiz_result",
                "polarity": "positive",
            },
        )
        request(
            "POST",
            "/signals",
            {
                "student_id": "stu_multi",
                "knowledge_point_id": "kp_b",
                "signal_type": "quiz_result",
                "polarity": "negative",
            },
        )
        status, body = request("GET", "/profiles?student_id=stu_multi")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["data"]), 2)


if __name__ == "__main__":
    unittest.main()
