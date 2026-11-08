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
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:3b-instruct")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "ollama")
LLM_TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "120"))
LLM_DISABLED = os.environ.get("LLM_DISABLED", "0") == "1"

# --- Interpretation switches (default first; alternatives in comments) ---
NEXT_WEEKDAY = "following_week"  # | "nearest_upcoming"
TRANSFER_LOWER_BOUND = "restart"  # | "today"
# day_first: earliest day across every eligible plant (plants.csv order breaks ties on a day).
# plant_first: go plant by plant in plants.csv order and take the first plant that has any free slot.
TRANSFER_SEARCH = "day_first"  # | "plant_first"
PLANT_TIEBREAK = "plants_csv_order"  # | "plant_id_alpha"
# Which affected order gets a contested slot first: original build date, or earliest customer promise date.
SLOT_PRIORITY = "build_date"  # | "promised_date"
COMPOUND_ORDER = "message_order"  # | "earliest_disruption_first"
NOTIFY_SCOPE = "per_event"  # | "per_incident"
NO_SLOT_ACTION = "escalate"  # | "skip"
ESCALATE_NOISE = False

FUZZY_THRESHOLD = 90


def snapshot() -> dict:
    return {
        "NEXT_WEEKDAY": NEXT_WEEKDAY,
        "TRANSFER_LOWER_BOUND": TRANSFER_LOWER_BOUND,
        "TRANSFER_SEARCH": TRANSFER_SEARCH,
        "PLANT_TIEBREAK": PLANT_TIEBREAK,
        "SLOT_PRIORITY": SLOT_PRIORITY,
        "COMPOUND_ORDER": COMPOUND_ORDER,
        "NOTIFY_SCOPE": NOTIFY_SCOPE,
        "NO_SLOT_ACTION": NO_SLOT_ACTION,
        "ESCALATE_NOISE": ESCALATE_NOISE,
        "FUZZY_THRESHOLD": FUZZY_THRESHOLD,
        "LLM_MODEL": LLM_MODEL,
    }
