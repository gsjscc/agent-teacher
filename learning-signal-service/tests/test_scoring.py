"""表A写入 / 表B打分逻辑的单元测试，直接对内存数据库测试，不需要启动 server。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db


class ScoringTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.get_conn(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_no_signal_is_new(self):
        profile = db.get_profile(self.conn, "stu1", "kp1")
        self.assertEqual(profile["state"], db.STATE_NEW)
        self.assertEqual(profile["score"], 0.0)

    def test_self_report_positive_moves_to_learning(self):
        result = db.insert_signal(self.conn, "stu1", "kp1", "self_report", "positive", "我懂了")
        self.assertEqual(result["profile"]["score"], 1.0)
        self.assertEqual(result["profile"]["state"], "学习中")

    def test_repeated_negative_signals_reach_weak(self):
        db.insert_signal(self.conn, "stu1", "kp1", "proactive_question", "negative", "反复问同一点")
        db.insert_signal(self.conn, "stu1", "kp1", "self_explanation", "negative", "说不出依据")
        result = db.insert_signal(self.conn, "stu1", "kp1", "quiz_result", "negative", "做错")
        self.assertEqual(result["profile"]["score"], -2.5)
        self.assertEqual(result["profile"]["state"], "薄弱")

    def test_accumulated_positive_reaches_mastered(self):
        db.insert_signal(self.conn, "stu1", "kp1", "self_report", "positive")
        db.insert_signal(self.conn, "stu1", "kp1", "quiz_result", "positive")
        db.insert_signal(self.conn, "stu1", "kp1", "self_explanation", "positive")
        result = db.insert_signal(self.conn, "stu1", "kp1", "proactive_question", "positive")
        self.assertEqual(result["profile"]["score"], 2.5)
        self.assertEqual(result["profile"]["state"], "学习中")
        result2 = db.insert_signal(self.conn, "stu1", "kp1", "self_report", "positive")
        self.assertEqual(result2["profile"]["score"], 3.5)
        self.assertEqual(result2["profile"]["state"], db.STATE_MASTERED)

    def test_signals_are_isolated_per_knowledge_point(self):
        db.insert_signal(self.conn, "stu1", "kp1", "self_report", "positive")
        profile_kp2 = db.get_profile(self.conn, "stu1", "kp2")
        self.assertEqual(profile_kp2["state"], db.STATE_NEW)

    def test_invalid_signal_type_raises(self):
        with self.assertRaises(ValueError):
            db.insert_signal(self.conn, "stu1", "kp1", "not_a_type", "positive")

    def test_get_signals_returns_history_in_order(self):
        db.insert_signal(self.conn, "stu1", "kp1", "self_report", "positive", "第一次")
        db.insert_signal(self.conn, "stu1", "kp1", "quiz_result", "negative", "第二次")
        history = db.get_signals(self.conn, "stu1", "kp1")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["evidence"], "第一次")
        self.assertEqual(history[1]["evidence"], "第二次")

    def test_get_profiles_for_student_lists_all_knowledge_points(self):
        db.insert_signal(self.conn, "stu1", "kp1", "self_report", "positive")
        db.insert_signal(self.conn, "stu1", "kp2", "quiz_result", "negative")
        profiles = db.get_profiles_for_student(self.conn, "stu1")
        self.assertEqual(len(profiles), 2)
        kp_ids = {p["knowledge_point_id"] for p in profiles}
        self.assertEqual(kp_ids, {"kp1", "kp2"})


if __name__ == "__main__":
    unittest.main()
