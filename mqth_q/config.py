from __future__ import annotations
import os, json
from typing import Any, Dict, Optional

# ---------- Environment variable helpers ----------
def env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def env_json(name: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raw = os.getenv(name)
    if not raw:
        return default or {}
    try:
        return json.loads(raw)
    except Exception:
        return default or {}
    
# ------------- core knobs -------------
# SQLite database with your questions/attempts
# Use forward slashes for cross-platform compatibility (works on both Windows and Linux)
DB_PATH: str = os.getenv("DB_PATH", "data/temporal/exams.db")

# LLM endpoint (Ollama by default).
# Note: inside Docker, you’ll often set OLLAMA_URL=http://host.docker.internal:11434
OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")

# Local model tag to use with Ollama
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

# Optional per-call options for Ollama (context window, GPU offloading, etc.)
# You can override with: export LLM_OPTIONS='{"num_ctx":1024,"num_gpu":0}'
LLM_OPTIONS: Dict[str, Any] = env_json("LLM_OPTIONS", {"num_ctx": 1024})

# Grading cutoff for correct/incorrect (used by baseline & LLM paths)
GRADE_THRESHOLD: float = float(os.getenv("GRADE_THRESHOLD", "0.6"))

# Default number of recommendations to fetch
RECS_K: int = int(os.getenv("RECS_K", "5"))

# SQLite pragmas (we’ll apply these in db.py)
SQLITE_JOURNAL_MODE: str = os.getenv("SQLITE_JOURNAL", "WAL")
SQLITE_SYNCHRONOUS: str = os.getenv("SQLITE_SYNC", "NORMAL")

# Handy one-liner to print current config (useful when debugging containers)
def explain() -> str:
    return (
        f"DB={DB_PATH} | OLLAMA={OLLAMA_MODEL}@{OLLAMA_URL} | "
        f"THRESH={GRADE_THRESHOLD} | LLM_OPTIONS={LLM_OPTIONS}"
    )