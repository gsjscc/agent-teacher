"""表A(学习信号记录表) / 表B(学生掌握度画像表) 的存储与打分逻辑。

对应 执行计划 中 8-23 重新设计的反馈闭环：
- 表A: learning_signals，原始流水账
- 表B: mastery_profiles，汇总画像，各车道"共享个性化层"实际读取的表

打分规则和状态阈值是简化版本（用条件判断代替真贝叶斯推断），
尚未用真实对话样本验证过，SCORE_RULES / STATE_THRESHOLDS 是当前的第一版取值，后续要跟着实测调整。
"""
import sqlite3
import time

# 信号类型
SIGNAL_TYPES = (
    "self_report",        # 显式自报（"我懂了"/"我还是不懂"）
    "proactive_question",  # 主动提问（问原理 vs 反复问同一点）
    "self_explanation",   # 自我解释质量（能否说出依据）
    "exploration",         # 可视化探索行为（有目的验证 vs 随意乱拖）
    "quiz_result",         # 做题结果
)

POLARITIES = ("positive", "negative", "neutral")

# 信号类型+极性 -> 分数变化，中性(neutral)一律不加分也不写入(由调用方决定是否记录)
SCORE_RULES = {
    ("self_report", "positive"): 1.0,
    ("self_report", "negative"): -1.0,
    ("proactive_question", "positive"): 0.5,
    ("proactive_question", "negative"): -1.0,
    ("self_explanation", "positive"): 0.5,
    ("self_explanation", "negative"): -1.0,
    ("exploration", "positive"): 0.5,
    ("exploration", "negative"): -0.5,
    ("quiz_result", "positive"): 0.5,
    ("quiz_result", "negative"): -0.5,
}

# 累计分 -> 掌握状态。未产生任何信号时状态固定为"未学"，不查这张表。
STATE_THRESHOLDS = (
    (-2.0, "薄弱"),   # score <= -2.0
    (3.0, "学习中"),  # -2.0 < score < 3.0
)
STATE_MASTERED = "已掌握"  # score >= 3.0
STATE_NEW = "未学"


def score_to_state(score: float) -> str:
    for upper, state in STATE_THRESHOLDS:
        if score <= upper:
            return state
    return STATE_MASTERED


def get_conn(path: str = "data/signals.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS learning_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            knowledge_point_id TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            polarity TEXT NOT NULL,
            evidence TEXT,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mastery_profiles (
            student_id TEXT NOT NULL,
            knowledge_point_id TEXT NOT NULL,
            state TEXT NOT NULL,
            score REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (student_id, knowledge_point_id)
        )
        """
    )
    conn.commit()


def insert_signal(
    conn: sqlite3.Connection,
    student_id: str,
    knowledge_point_id: str,
    signal_type: str,
    polarity: str,
    evidence: str = "",
) -> dict:
    if signal_type not in SIGNAL_TYPES:
        raise ValueError(f"unknown signal_type: {signal_type}")
    if polarity not in POLARITIES:
        raise ValueError(f"unknown polarity: {polarity}")

    now = time.time()
    conn.execute(
        """
        INSERT INTO learning_signals
            (student_id, knowledge_point_id, signal_type, polarity, evidence, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (student_id, knowledge_point_id, signal_type, polarity, evidence, now),
    )

    delta = SCORE_RULES.get((signal_type, polarity), 0.0)
    row = conn.execute(
        "SELECT score FROM mastery_profiles WHERE student_id = ? AND knowledge_point_id = ?",
        (student_id, knowledge_point_id),
    ).fetchone()
    prev_score = row["score"] if row else 0.0
    new_score = prev_score + delta
    new_state = score_to_state(new_score) if (row or delta != 0.0) else STATE_NEW

    conn.execute(
        """
        INSERT OR REPLACE INTO mastery_profiles
            (student_id, knowledge_point_id, state, score, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (student_id, knowledge_point_id, new_state, new_score, now),
    )
    conn.commit()

    return {
        "student_id": student_id,
        "knowledge_point_id": knowledge_point_id,
        "signal_type": signal_type,
        "polarity": polarity,
        "evidence": evidence,
        "created_at": now,
        "profile": {"state": new_state, "score": new_score},
    }


def get_profile(conn: sqlite3.Connection, student_id: str, knowledge_point_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM mastery_profiles WHERE student_id = ? AND knowledge_point_id = ?",
        (student_id, knowledge_point_id),
    ).fetchone()
    if row is None:
        return {
            "student_id": student_id,
            "knowledge_point_id": knowledge_point_id,
            "state": STATE_NEW,
            "score": 0.0,
            "updated_at": None,
        }
    return dict(row)


def get_profiles_for_student(conn: sqlite3.Connection, student_id: str) -> list:
    rows = conn.execute(
        "SELECT * FROM mastery_profiles WHERE student_id = ? ORDER BY knowledge_point_id",
        (student_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_signals(conn: sqlite3.Connection, student_id: str, knowledge_point_id: str = None) -> list:
    if knowledge_point_id:
        rows = conn.execute(
            """
            SELECT * FROM learning_signals
            WHERE student_id = ? AND knowledge_point_id = ?
            ORDER BY created_at
            """,
            (student_id, knowledge_point_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM learning_signals WHERE student_id = ? ORDER BY created_at",
            (student_id,),
        ).fetchall()
    return [dict(r) for r in rows]
