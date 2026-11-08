#!/usr/bin/env python3
"""Build captions_source.json from run numbers. Digits only. No em/en dashes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.numbers import load

OUT = Path(__file__).resolve().parent / "out"
N = load()


def C(chapter: str, start: float, end: float, text: str) -> dict:
    if "—" in text or "–" in text or "−" in text:
        raise SystemExit(f"bad dash: {text}")
    return {"chapter": chapter, "start": start, "end": end, "text": text}


caps = [
    C("00_title", 0.2, 3.8, "Hack the Highway - Wacky Wheels Control Tower"),
    C("01_problem", 0.2, 3.8, "Just-in-time builds. Messy messages. Real operational risk."),
    C("02_architecture", 0.2, 3.8, "The LLM reads. Code decides."),
    C("03_official_run", 0.3, 4.0, f"Official pipeline on the {N['events']} scored events"),
    C("03_official_run", 4.2, 9.0, f"Self-check: {N['self_check_pass']}/{N['events']} green"),
    C("03_official_run", 9.2, 14.0, f"{N['writes']} writes. {N['failed']} failed calls. {N['tests']} tests."),
    C("04_event_ops_overview", 0.3, 4.0, f"{N['events']} events on the scored run"),
    C("04_event_ops_overview", 4.2, 9.5,
      f"{N['events']} = {N['actionable_events']} actionable + {N['escalated_events']} escalated + {N['noise_events']} noise"),
    C("04_event_ops_overview", 9.7, 14.0, f"{N['incidents']} incidents because E-01 is compound"),
    C("04_event_ops_overview", 14.2, 18.0, f"Model {N['model']}"),
    C("04_event_ops_overview", 18.2, 24.0, "Replay run - events arrive one by one"),
    C("05_e09_supplier_delay", 0.3, 4.0, "E-09 supplier delay - Orbit cameras to Huntsville"),
    C("05_e09_supplier_delay", 4.2, 9.0, "LLM copies phrases. Code resolves ids."),
    C("05_e09_supplier_delay", 9.2, 14.0, "Graph path and excluded orders - rule 10"),
    C("05_e09_supplier_delay", 14.2, 20.0, "Schedule before/after heatmap with blocked days"),
    C("05_e09_supplier_delay", 20.2, 26.0, f"Action log cites rules. {N['e09_writes']} writes on E-09."),
    C("05_e09_supplier_delay", 26.2, 32.0, "Verifier: plan checks and twin world checks, all green"),
    C("06_e01_compound", 0.3, 5.0, "E-01 compound: San Antonio outage + Princeton chip delay"),
    C("06_e01_compound", 5.2, 10.0, "next Friday resolves with NEXT_WEEKDAY = following_week"),
    C("06_e01_compound", 10.2, 15.0, "One slot ledger. One merged notify per dealer."),
    C("07_e03_quality", 0.3, 6.0, "E-03 quality hold - stop sale and owner contact"),
    C("07_e03_quality", 6.2, 12.0, f"E-03 writes {N['e03_writes']} hold, stop-sale, and notify actions"),
    C("08_e05_noise", 0.3, 5.0, "E-05 ignored - not operational (rule 7)"),
    C("08_e05_noise", 5.2, 9.0, "Action log empty - zero tool calls"),
    C("09_guardrail", 0.3, 6.0, "Guardrail: ungrounded LLM text rejected"),
    C("09_guardrail", 6.2, 11.0, "Code made the decision after the grounding check"),
    C("10_hitl_e02", 0.3, 5.0, "E-02 escalated - rule 8, missing fields"),
    C("10_hitl_e02", 5.2, 11.0, "Human review inbox: note + Approve (local only)"),
    C("11_knowledge_graph", 0.3, 6.0, f"Knowledge graph: {N['nodes']} nodes, {N['edges']} edges"),
    C("12_ask", 0.3, 6.0, "Ask the control tower - live read-only query"),
    C("13_live_desk", 0.3, 6.0, "Live Incident Desk - new message on the twin"),
    C("13_live_desk", 6.2, 11.0, "Simulation - nothing sent to the enterprise server"),
    C("14_whatif", 0.3, 5.0, "Scenario Lab, then What-if side by side"),
    C("14_whatif", 5.2, 12.0, "Two different scenarios. Simulation, not executed."),
    C("15_policy_studio", 0.3, 5.0, "handbook_v1 is the locked scored baseline"),
    C("15_policy_studio", 5.2, 11.0, "Preview impact on the twin. Publish a new version."),
    C("15_policy_studio", 11.2, 16.0, "Official run refuses edited profiles without --policy"),
    C("16_audit", 0.3, 6.0, "Audit trail filters by rule and dealer"),
    C("17_ops_health", 0.3, 6.0, "Per-stage timing from traces - failure count 0"),
    C("18_daily_briefing", 0.3, 6.0, "Daily briefing in plain business language"),
    C("18_daily_briefing", 6.2, 11.0, "Download the one-page PDF"),
    C("19_results", 0.3, 4.5,
      f"{N['self_check_pass']}/{N['events']} green | {N['writes']} writes | {N['failed']} failed | {N['tests']} tests"),
    C("20_close", 0.3, 3.8, "The LLM reads, code decides."),
]

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "captions_source.json").write_text(json.dumps(caps, indent=2), encoding="utf-8")
print("captions", len(caps))
