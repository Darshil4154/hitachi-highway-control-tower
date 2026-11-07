"""All tunable interpretations of ambiguous handbook points (SPEC section 9) plus paths and LLM settings."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTERPRISE_DIR = ROOT / "enterprise"
DATA_DIR = ENTERPRISE_DIR / "data"
EVENTS_PATH = DATA_DIR / "events.json"
TRACES_DIR = ROOT / "traces"
EXPORTS_DIR = ROOT / "exports"
CACHE_DIR = ROOT / "cache" / "llm"
RUNS_DIR = ROOT / "runs"

SERVER_URL = os.environ.get("SERVER_URL", "http://127.0.0.1:8000")

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:7b-instruct")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "ollama")
LLM_TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "120"))
LLM_DISABLED = os.environ.get("LLM_DISABLED", "0") == "1"

# --- Interpretation switches (default first; alternatives in comments) ---
NEXT_WEEKDAY = "following_week"  # | "nearest_upcoming"
TRANSFER_LOWER_BOUND = "today"  # | "restart"
PLANT_TIEBREAK = "plants_csv_order"  # | "plant_id_alpha"
COMPOUND_ORDER = "message_order"  # | "earliest_disruption_first"
NOTIFY_SCOPE = "per_event"  # | "per_incident"
NO_SLOT_ACTION = "escalate"  # | "skip"
QUALITY_DEALER_NOTIFY = False  # | True
ESCALATE_NOISE = False

FUZZY_THRESHOLD = 90


def snapshot() -> dict:
    return {
        "NEXT_WEEKDAY": NEXT_WEEKDAY,
        "TRANSFER_LOWER_BOUND": TRANSFER_LOWER_BOUND,
        "PLANT_TIEBREAK": PLANT_TIEBREAK,
        "COMPOUND_ORDER": COMPOUND_ORDER,
        "NOTIFY_SCOPE": NOTIFY_SCOPE,
        "NO_SLOT_ACTION": NO_SLOT_ACTION,
        "QUALITY_DEALER_NOTIFY": QUALITY_DEALER_NOTIFY,
        "ESCALATE_NOISE": ESCALATE_NOISE,
        "FUZZY_THRESHOLD": FUZZY_THRESHOLD,
        "LLM_MODEL": LLM_MODEL,
    }
