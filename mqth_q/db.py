# core tables: users, exams, questions, attemps
# usamos pequeñas funciones que reutilizamos en app_streamlit.py y 4_llm.py
#       - get_user_id() - crear usuario si no existe y devolver user_id
#       - fetch_question() - obtener datos de una pregunta por exercise_id | text + metada por un ejercicio
#       - list_unseen() - listar preguntas no intentadas por un usuario
#       - get_attempts() - obtener dataframe con intentos de un usuario
#       - save_attempt() - guardar intento de un usuario

from __future__ import annotations
import sqlite3, json, time, os
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

from .config import DB_PATH, SQLITE_JOURNAL_MODE, SQLITE_SYNCHRONOUS

# --------------------------- Connection helpers ---------------------------
def connect() -> sqlite3.Connection:
    # Create directory if it doesn't exist
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    # timeout evita que cuelgue si hay lock (mejor falla rápido)
    con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=2.0)
    con.row_factory = sqlite3.Row
    return con

@contextmanager
def _con():
    con = connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()

# --------------------------- Schema init ---------------------------
def init_db() -> None:
    with _con() as con:
        cur = con.cursor()
        cur.execute(f"PRAGMA journal_mode={SQLITE_JOURNAL_MODE};")
        cur.execute(f"PRAGMA synchronous={SQLITE_SYNCHRONOUS};")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
          user_id   INTEGER PRIMARY KEY AUTOINCREMENT,
          username  TEXT NOT NULL UNIQUE
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS exams(
          exam_id    TEXT PRIMARY KEY,
          exam_type  TEXT,
          date       TEXT,     -- YYYY-MM-DD
          year       INTEGER
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS questions(
          exercise_id TEXT PRIMARY KEY,
          exam_id     TEXT,
          question    TEXT,
          solution    TEXT,
          topic_pred  TEXT,
          FOREIGN KEY (exam_id) REFERENCES exams(exam_id)
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS attempts(
          attempt_id        INTEGER PRIMARY KEY AUTOINCREMENT,
          ts                REAL DEFAULT (strftime('%s','now')),
          user_id           INTEGER NOT NULL,
          exercise_id       TEXT    NOT NULL,
          score             REAL,
          correct           INTEGER,
          cosine            REAL,
          jaccard           REAL,
          missing_keywords  TEXT,   -- JSON array
          student_answer    TEXT,
          reasons           TEXT,
          hint              TEXT,
          feedback_json     TEXT,
          FOREIGN KEY (user_id)     REFERENCES users(user_id),
          FOREIGN KEY (exercise_id) REFERENCES questions(exercise_id)
        );
        """)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_attempts_ex   ON attempts(exercise_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_topic ON questions(topic_pred);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_exams_date ON exams(date);")

# --------------------------- Users ---------------------------
def get_user_id(username: str) -> int:
    with _con() as con:
        cur = con.cursor()
        cur.execute("INSERT OR IGNORE INTO users(username) VALUES(?)", (username,))
        cur.execute("SELECT user_id FROM users WHERE username=?", (username,))
        return int(cur.fetchone()["user_id"])

# --------------------------- Questions / Exams ---------------------------
def fetch_question(exercise_id: str) -> Optional[Dict[str, Any]]:
    with _con() as con:
        cur = con.cursor()
        cur.execute("""
          SELECT q.exercise_id, q.question, q.solution, q.topic_pred AS topic,
                 e.exam_id, e.exam_type, e.date, e.year
          FROM questions q
          LEFT JOIN exams e ON e.exam_id = q.exam_id
          WHERE q.exercise_id = ?
        """, (exercise_id,))
        row = cur.fetchone()
        return dict(row) if row else None

def list_unseen(user_id: int, k: int = 20) -> List[Dict[str, Any]]:
    with _con() as con:
        cur = con.cursor()
        cur.execute("""
          SELECT q.exercise_id, q.topic_pred AS topic, e.date, e.exam_type
          FROM questions q
          LEFT JOIN exams e ON e.exam_id = q.exam_id
          WHERE q.exercise_id NOT IN (
            SELECT exercise_id FROM attempts WHERE user_id = ?
          )
          ORDER BY e.date ASC
          LIMIT ?
        """, (user_id, k))
        return [dict(r) for r in cur.fetchall()]

# --- NEW: topics list + pick by topic (unseen / any) ---
def list_topics() -> List[str]:
    with _con() as con:
        cur = con.cursor()
        cur.execute("SELECT DISTINCT topic_pred FROM questions WHERE topic_pred IS NOT NULL AND topic_pred <> '' ORDER BY topic_pred ASC;")
        return [r[0] for r in cur.fetchall()]

def pick_unseen_by_topic(user_id: int, topic: str) -> Optional[Dict[str, Any]]:
    with _con() as con:
        cur = con.cursor()
        cur.execute("""
          SELECT q.exercise_id, q.topic_pred AS topic, e.date, e.exam_type
          FROM questions q
          LEFT JOIN exams e ON e.exam_id = q.exam_id
          WHERE q.topic_pred = ?
            AND q.exercise_id NOT IN (SELECT exercise_id FROM attempts WHERE user_id = ?)
          ORDER BY e.date ASC
          LIMIT 1;
        """, (topic, user_id))
        row = cur.fetchone()
        return dict(row) if row else None

def pick_any_by_topic(topic: str) -> Optional[Dict[str, Any]]:
    with _con() as con:
        cur = con.cursor()
        cur.execute("""
          SELECT q.exercise_id, q.topic_pred AS topic, e.date, e.exam_type
          FROM questions q
          LEFT JOIN exams e ON e.exam_id = q.exam_id
          WHERE q.topic_pred = ?
          ORDER BY e.date ASC
          LIMIT 1;
        """, (topic,))
        row = cur.fetchone()
        return dict(row) if row else None

# --------------------------- Attempts ---------------------------
def save_attempt(user_id: int, exercise_id: str, result: Dict[str, Any], student_answer: str) -> None:
    score  = float(result.get("score", 0.0))
    correct = 1 if bool(result.get("correct", False)) else 0
    cosine = result.get("cosine")
    jaccard = result.get("jaccard")
    missing = json.dumps(result.get("missing_keywords", []))
    reasons = result.get("reasons", "")
    hint    = result.get("hint", "")
    feedback_json = json.dumps({k: v for k, v in result.items() if k not in {"missing_keywords"}})

    with _con() as con:
        cur = con.cursor()
        cur.execute("""
          INSERT INTO attempts(
            ts, user_id, exercise_id, score, correct,
            cosine, jaccard, missing_keywords, student_answer,
            reasons, hint, feedback_json
          )
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """, (time.time(), user_id, exercise_id, score, correct,
              cosine, jaccard, missing, student_answer, reasons, hint, feedback_json))

def get_attempts(user_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    with _con() as con:
        cur = con.cursor()
        cur.execute("""
          SELECT a.attempt_id, a.ts, a.exercise_id, a.score, a.correct,
                 a.reasons, a.hint,
                 q.topic_pred AS topic, e.date, e.exam_type
          FROM attempts a
          JOIN questions q ON q.exercise_id = a.exercise_id
          LEFT JOIN exams e  ON e.exam_id    = q.exam_id
          WHERE a.user_id = ?
          ORDER BY a.ts DESC
          LIMIT ?
        """, (user_id, limit))
        return [dict(r) for r in cur.fetchall()]
