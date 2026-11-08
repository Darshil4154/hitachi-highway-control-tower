"""Build Agent World state from traces and a live sandbox feed."""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACES = ROOT / "traces"
LIVE = ROOT / "ui" / "static" / "agent_world" / "live_state.json"
EXPORTS = ROOT / "exports"

AGENTS = [
    {"id": "coordinator", "name": "Coordinator", "role": "Routes every event", "color": "#38bdf8",
     "x": 0, "z": 0, "kind": "hub"},
    {"id": "llm", "name": "LLM Reader", "role": "Classifies and copies phrases", "color": "#a78bfa",
     "x": -7.5, "z": -5.5, "kind": "station"},
    {"id": "supply_chain", "name": "Supply Chain Planner", "role": "Reschedule and transfer", "color": "#f59e0b",
     "x": 7.5, "z": -5.5, "kind": "worker"},
    {"id": "dealer", "name": "Dealer Network", "role": "Notify dealers and stop sale", "color": "#34d399",
     "x": 8.5, "z": 3.5, "kind": "worker"},
    {"id": "care", "name": "Customer Care & Quality", "role": "Loaners, holds, owners", "color": "#f472b6",
     "x": -8.5, "z": 3.5, "kind": "worker"},
    {"id": "verifier", "name": "Verifier", "role": "Plan and twin checks", "color": "#22c55e",
     "x": 0, "z": 8.5, "kind": "tower"},
    {"id": "twin", "name": "Digital Twin", "role": "Dry-run before the server", "color": "#06b6d4",
     "x": -4.5, "z": 7.0, "kind": "dome"},
    {"id": "server", "name": "Enterprise Gate", "role": "Real writes leave here", "color": "#ef4444",
     "x": 4.5, "z": 7.0, "kind": "gate"},
]

STAGE_AGENTS = {
    "extract": ["llm", "coordinator"],
    "resolve": ["llm", "coordinator"],
    "gate": ["coordinator"],
    "plan": ["supply_chain", "dealer", "care", "coordinator"],
    "verify": ["verifier"],
    "twin": ["twin", "verifier"],
    "execute": ["server", "coordinator"],
    "readback": ["verifier", "coordinator"],
}

TOOL_AGENT = {
    "mes.reschedule": "supply_chain", "mes.transfer": "supply_chain", "mes.get_schedule": "supply_chain",
    "dealer.notify": "dealer", "dealer.stop_sale": "dealer",
    "crm.assign_loaner": "care", "crm.notify_customer": "care", "crm.loaner_availability": "care",
    "quality.hold_lot": "care", "escalate": "coordinator",
}


def _plants_from_store() -> list[dict]:
    try:
        from .data_loader import get_store
        ds = get_store()
        out = []
        for i, (pid, plant) in enumerate(ds.plants.items()):
            angle = (i / max(1, len(ds.plants))) * 6.283
            out.append({"id": pid, "name": plant.name, "x": 14 * __import__("math").cos(angle),
                        "z": 14 * __import__("math").sin(angle), "kind": "plant"})
        return out
    except Exception:
        return []


def _event_brief(trace: dict) -> dict:
    metrics = trace.get("metrics") or {}
    stages = metrics.get("stages_s") or {}
    plan = trace.get("plan") or []
    tools = {}
    for a in plan:
        tools[a.get("tool") or "other"] = tools.get(a.get("tool") or "other", 0) + 1
    active = []
    for tool in tools:
        aid = TOOL_AGENT.get(tool)
        if aid and aid not in active:
            active.append(aid)
    return {
        "event_id": (trace.get("event") or {}).get("event_id"),
        "category": trace.get("ui_category"),
        "summary": (trace.get("summary") or "")[:280],
        "gate": (trace.get("classification") or {}).get("gate"),
        "writes": metrics.get("writes", 0),
        "reads": metrics.get("reads", 0),
        "failed": metrics.get("failed", 0),
        "stages_s": stages,
        "tools": tools,
        "active_agents": active,
        "escalated": bool((trace.get("escalation") or {}).get("escalated")),
    }


def build_replay_playlist() -> list[dict]:
    summary_path = TRACES / "run_summary.json"
    order = []
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        order = [e["event_id"] for e in summary.get("events") or []]
    if not order:
        order = sorted(p.stem for p in TRACES.glob("E-*.json"))
    playlist = []
    for eid in order:
        path = TRACES / f"{eid}.json"
        if not path.exists():
            continue
        playlist.append(_event_brief(json.loads(path.read_text(encoding="utf-8"))))
    return playlist


def world_bootstrap() -> dict:
    stats = {}
    sp = EXPORTS / "graph_stats.json"
    if sp.exists():
        stats = json.loads(sp.read_text(encoding="utf-8"))
    playlist = build_replay_playlist()
    return {
        "generated_at": time.time(),
        "agents": AGENTS,
        "plants": _plants_from_store(),
        "stage_agents": STAGE_AGENTS,
        "playlist": playlist,
        "graph": {"nodes": stats.get("nodes_total"), "edges": stats.get("edges_total")},
        "live": read_live(),
    }


def publish_live(payload: dict) -> None:
    LIVE.parent.mkdir(parents=True, exist_ok=True)
    payload = {**payload, "ts": time.time(), "mode": "live"}
    LIVE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_live() -> dict | None:
    if not LIVE.exists():
        return None
    try:
        return json.loads(LIVE.read_text(encoding="utf-8"))
    except Exception:
        return None


def clear_live() -> None:
    if LIVE.exists():
        LIVE.unlink()


def publish_from_trace_like(label: str, summary: str, plan: list[dict], stages: dict | None = None,
                            banner: str = "") -> None:
    tools = {}
    active = []
    for a in plan or []:
        tool = a.get("tool") or "other"
        tools[tool] = tools.get(tool, 0) + 1
        aid = TOOL_AGENT.get(tool)
        if aid and aid not in active:
            active.append(aid)
    stage = "plan"
    if stages:
        # pick the last non-zero stage name as current
        for name in ("readback", "execute", "twin", "verify", "plan", "gate", "resolve", "extract"):
            if float((stages or {}).get(name) or 0) > 0:
                stage = name
                break
    publish_live({
        "label": label,
        "summary": summary[:400],
        "banner": banner or "Live sandbox",
        "stage": stage,
        "tools": tools,
        "active_agents": active or STAGE_AGENTS.get(stage, ["coordinator"]),
        "writes": sum(1 for a in plan or [] if a.get("tool") not in ("mes.get_schedule", "crm.loaner_availability")),
    })
