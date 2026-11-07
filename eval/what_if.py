"""What-if analysis for the open interpretation questions.

Re-plans all 15 events in the digital twin (no server) once per alternative switch value, diffs the write actions
against the default run, and grades every variant with the independent self-check. Nothing is written to traces/.

python eval/what_if.py [--out docs/what_if_report.md]
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import sys
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from control_tower import config  # noqa: E402
from control_tower.agents.coordinator import Coordinator  # noqa: E402
from control_tower.tools_client import ToolsClient  # noqa: E402

_spec = importlib.util.spec_from_file_location("self_check", ROOT / "eval" / "self_check.py")
self_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(self_check)

WRITES = self_check.WRITES

VARIANTS = [
    ("TRANSFER_LOWER_BOUND", "restart", "Transfer day must be on/after the end of the disruption"),
    ("TRANSFER_SEARCH", "plant_first", "Transfers go plant by plant (first plant in plants.csv with any free slot)"),
    ("SLOT_PRIORITY", "promised_date", "Contested slots go to the order with the earliest customer promise date"),
    ("NOTIFY_SCOPE", "per_incident", "Compound event: one dealer.notify per incident instead of per event"),
    ("COMPOUND_ORDER", "earliest_disruption_first", "Compound event: plan the earliest disruption first"),
    ("NEXT_WEEKDAY", "nearest_upcoming", '"next Friday" = the nearest upcoming Friday (Mar 12)'),
    ("NO_SLOT_ACTION", "skip", "Order with no slot anywhere: skip instead of escalate"),
]


def run_all(events: list[dict]) -> dict[str, dict]:
    client = ToolsClient(dry_run=True)
    coord = Coordinator(client)
    out = {}
    with redirect_stdout(io.StringIO()):
        for e in events:
            t = coord.handle(e)
            calls = client.calls_for(e["event_id"])
            out[e["event_id"]] = {"trace": t, "calls": calls,
                                  "score": self_check.score_event(e["event_id"], calls, t)}
    return out


def write_key(c: dict) -> str:
    """Identity of a write decision; free-text message fields are compared separately."""
    args = {k: v for k, v in c["args"].items() if k != "message"}
    return f"{c['tool']} {json.dumps(args, sort_keys=True)}"


def text_changes(base: dict, alt: dict, eid: str) -> int:
    msg = lambda run: {write_key(c): c["args"].get("message") for c in run[eid]["calls"] if c["tool"] in WRITES}
    b, a = msg(base), msg(alt)
    return sum(1 for k in b.keys() & a.keys() if b[k] != a[k])


def describe(c: dict) -> str:
    a = c["args"]
    if c["tool"] in ("mes.reschedule", "mes.transfer"):
        return f"{c['tool']} {a['production_order_id']} -> {a.get('to_plant_id', 'same plant')} {a['new_date']}"
    if c["tool"] == "dealer.notify":
        return f"dealer.notify {a['dealer_id']} ({len(a['customer_order_ids'])} orders)"
    if c["tool"] == "crm.assign_loaner":
        return f"crm.assign_loaner {a['customer_order_id']}"
    return f"{c['tool']} {json.dumps(a, sort_keys=True)[:80]}"


def diff(base: dict, alt: dict) -> list[tuple[str, list[str], list[str], int]]:
    rows = []
    for eid in base:
        b = Counter(write_key(c) for c in base[eid]["calls"] if c["tool"] in WRITES)
        a = Counter(write_key(c) for c in alt[eid]["calls"] if c["tool"] in WRITES)
        texts = text_changes(base, alt, eid)
        if a != b or texts:
            by_key = {write_key(c): c for r in (base, alt) for c in r[eid]["calls"]}
            removed = sorted(describe(by_key[k]) for k in (b - a).elements())
            added = sorted(describe(by_key[k]) for k in (a - b).elements())
            rows.append((eid, removed, added, texts))
    return rows


def green(run: dict) -> int:
    return sum(1 for r in run.values() if all(r["score"]["checks"].values()) and not r["score"]["failed"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "what_if_report.md"))
    args = ap.parse_args()
    events = json.loads(config.EVENTS_PATH.read_text(encoding="utf-8"))
    base = run_all(events)
    n_writes = sum(1 for r in base.values() for c in r["calls"] if c["tool"] in WRITES)
    lines = ["# What-if report: open interpretation questions", "",
             "Each row re-plans all 15 events in the digital twin with one switch flipped "
             "(`control_tower/config.py`) and compares the write calls with the default run. "
             "Every variant is also graded by the independent self-check (`eval/self_check.py`), "
             "which follows the same switch.", "",
             f"Default run: {n_writes} writes, {green(base)}/15 events green.", "",
             "\"Decisions changed\" counts write calls whose target or arguments differ (which order moves where, "
             "which dealer is notified about which orders, who gets a loaner). \"Message text only\" counts "
             "dealer notifications that go to the same dealer about the same orders but quote different new dates.",
             "",
             "| switch | alternative | meaning | decisions changed | message text only | events | self-check |",
             "|---|---|---|---|---|---|---|"]
    details = []
    for name, value, meaning in VARIANTS:
        old = getattr(config, name)
        setattr(config, name, value)
        try:
            alt = run_all(events)
        finally:
            setattr(config, name, old)
        rows = diff(base, alt)
        changed = sum(len(r) for _, r, _, _ in rows)
        texts = sum(t for *_, t in rows)
        lines.append(f"| `{name}` | `{value}` (default `{old}`) | {meaning} | {changed} | {texts} | "
                     f"{', '.join(r[0] for r in rows) or '-'} | {green(alt)}/15 green |")
        if rows:
            details += ["", f"### `{name} = {value}`", ""]
            for eid, removed, added, t in rows:
                details.append(f"- **{eid}**: {len(removed)} decision(s) replaced by {len(added)}, "
                               f"{t} notification text(s) changed")
                details += [f"  - default: {r}" for r in removed]
                details += [f"  - alternative: {a}" for a in added]
    lines += ["", "## Differences", *(details or ["", "None."])]
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
