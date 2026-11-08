"""Sandbox runs for Policy Studio. The digital twin only: nothing is written to traces/ or the server.

The 15 scored events are replayed with the real (cached) extraction. Scenario Lab sentences are classified
by the policy's keywords, the same rule extractor the gate uses when the model is down, so a new event type
is visible without waiting on the model.
"""
from __future__ import annotations

import json
from collections import Counter

from . import config, llm
from .agents.coordinator import Coordinator
from .policy_model import Policy, load, using
from .tools_client import ToolsClient

SCENARIOS = [
    {"id": "S-weather", "name": "Weather closure",
     "text": "Weather closure: the Texas plant is down from 2027-03-26 through 2027-03-30."},
    {"id": "S-rumor", "name": "Unconfirmed rumor",
     "text": "Someone mentioned the seat foam might be late sometime. Nothing confirmed."},
    {"id": "S-brochure", "name": "Brochure request",
     "text": "Please send the spring brochure and the price list to the front desk."},
]


def _events() -> list[dict]:
    return json.loads(config.EVENTS_PATH.read_text(encoding="utf-8"))


def _force_rules(text: str) -> dict:
    return {"extraction": llm.rule_extract(text), "llm_model": "rule-extract", "llm_fallback": True,
            "llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached": False, "error": None}


def run_events(policy: Policy, events: list[dict] | None = None, *, force_rules: bool = False) -> dict[str, dict]:
    events = events if events is not None else _events()
    out: dict[str, dict] = {}
    real = llm.extract
    if force_rules:
        llm.extract = _force_rules
    try:
        with using(policy):
            client = ToolsClient(dry_run=True)
            coord = Coordinator(client)
            for e in events:
                out[e["event_id"]] = coord.handle(e)
    finally:
        llm.extract = real
    return out


def handle_text(text: str, policy: Policy, event_id: str = "LAB", *, force_rules: bool = False) -> dict:
    event = {"event_id": event_id, "source": "sandbox", "received_at": "", "text": text}
    return run_events(policy, [event], force_rules=force_rules)[event_id]


def _sig(action: dict) -> tuple[str, str]:
    args = {k: v for k, v in action.get("args", {}).items() if k != "message"}
    return action.get("tool", ""), json.dumps(args, sort_keys=True, default=str)


def _describe(action: dict) -> str:
    tool, args = action.get("tool"), action.get("args") or {}
    if tool in ("mes.reschedule", "mes.transfer"):
        return f"{tool} {args.get('production_order_id')} -> {args.get('to_plant_id', 'same plant')} {args.get('new_date')}"
    if tool == "dealer.notify":
        return f"dealer.notify {args.get('dealer_id')} ({len(args.get('customer_order_ids') or [])} orders)"
    if tool == "crm.assign_loaner":
        return f"crm.assign_loaner {args.get('customer_order_id')}"
    if tool == "escalate":
        return "escalate"
    return f"{tool} {json.dumps({k: v for k, v in args.items() if k != 'message'}, sort_keys=True, default=str)[:80]}"


def diff_plans(base: list[dict], alt: list[dict]) -> dict:
    b, a = Counter(_sig(x) for x in base), Counter(_sig(x) for x in alt)
    by_key = {_sig(x): x for x in list(base) + list(alt)}
    removed, added = [], []
    for key in sorted(set(b) | set(a), key=lambda k: (k[0], k[1])):
        gap = b[key] - a[key]
        if gap > 0:
            removed.extend([_describe(by_key[key])] * gap)
        gap = a[key] - b[key]
        if gap > 0:
            added.extend([_describe(by_key[key])] * gap)
    return {"added": added, "removed": removed, "changed": bool(added or removed)}


def blocking_green(trace: dict) -> bool:
    checks = [c for c in trace["verifier"]["plan_checks"] + trace["verifier"]["world_checks"]
              if c.get("blocking", True)]
    return all(c["ok"] for c in checks)


def preview_impact(draft: Policy) -> dict:
    """Replay the 15 events and the Scenario Lab. Restores the previous policy when it returns."""
    handbook = load("handbook_v1")
    events = _events()
    base = run_events(handbook, events)
    alt = run_events(draft, events)
    rows = []
    for eid in (e["event_id"] for e in events):
        delta = diff_plans(base[eid]["plan"], alt[eid]["plan"])
        if delta["changed"]:
            rows.append({"event": eid, "added": delta["added"], "removed": delta["removed"]})
    base_lab = run_events(handbook, _scenario_events(), force_rules=True)
    alt_lab = run_events(draft, _scenario_events(), force_rules=True)
    lab = []
    for s in SCENARIOS:
        delta = diff_plans(base_lab[s["id"]]["plan"], alt_lab[s["id"]]["plan"])
        lab.append({"id": s["id"], "name": s["name"],
                    "baseline_gate": base_lab[s["id"]]["classification"]["gate"],
                    "draft_gate": alt_lab[s["id"]]["classification"]["gate"],
                    "draft_type": (alt_lab[s["id"]]["incidents"] or [{}])[0].get("type"),
                    "added": delta["added"], "removed": delta["removed"]})
    green = sum(1 for t in alt.values() if blocking_green(t))
    return {"rows": rows, "robustness": green / len(alt) if alt else 0.0, "robust_n": green,
            "robust_of": len(alt), "scenarios": lab,
            "baseline_writes": sum(t["metrics"]["writes"] for t in base.values()),
            "draft_writes": sum(t["metrics"]["writes"] for t in alt.values())}


def _scenario_events() -> list[dict]:
    return [{"event_id": s["id"], "source": "scenario-lab", "received_at": "", "text": s["text"]} for s in SCENARIOS]
