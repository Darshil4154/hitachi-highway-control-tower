"""Run the control tower end to end.

python -m control_tower.run [--dry-run] [--events E-08,E-12] [--server http://127.0.0.1:8000]
--dry-run uses only the local digital twin (no server needed).
"""
from __future__ import annotations

import argparse
import json

from . import config, trace
from .agents.coordinator import Coordinator
from .tools_client import ToolsClient


def main() -> int:
    ap = argparse.ArgumentParser(description="Wacky Wheels control tower")
    ap.add_argument("--dry-run", action="store_true", help="use the local twin instead of the server")
    ap.add_argument("--events", default=None, help="comma-separated event ids (default: all)")
    ap.add_argument("--server", default=config.SERVER_URL)
    ap.add_argument("--traces", default=str(config.TRACES_DIR))
    args = ap.parse_args()

    client = ToolsClient(args.server, dry_run=args.dry_run)
    if args.dry_run:
        events = json.loads(config.EVENTS_PATH.read_text(encoding="utf-8"))
    else:
        events = client.get_events()
    if args.events:
        wanted = set(args.events.split(","))
        events = [e for e in events if e["event_id"] in wanted]

    coord = Coordinator(client)
    traces = []
    for e in events:
        t = coord.handle(e)
        trace.write(t, args.traces)
        traces.append(t)
        print(f"  {e['event_id']} {t['ui_category']:9} writes={t['metrics']['writes']:3} "
              f"failed={t['metrics']['failed']}  {t['summary'][:110]}", flush=True)
    if not args.events:
        trace.write_run(traces, "dry-run" if args.dry_run else "server", args.server, args.traces)

    print()
    print(f"{'event':6} {'category':10} {'writes by tool':72} {'failed':6} verifier")
    total_failed = 0
    for t in traces:
        writes: dict[str, int] = {}
        for a in t["actions"]:
            if a["kind"] != "read":
                writes[a["tool"]] = writes.get(a["tool"], 0) + 1
        checks = [c for c in t["verifier"]["plan_checks"] + t["verifier"]["world_checks"] if c.get("blocking", True)]
        verdict = "-" if not checks else ("green" if all(c["ok"] for c in checks) else "RED")
        warn = [c["name"] for c in t["verifier"]["plan_checks"] if not c["ok"] and not c.get("blocking", True)]
        total_failed += t["metrics"]["failed"]
        w = ", ".join(f"{k}={v}" for k, v in writes.items()) or "(none)"
        print(f"{t['event']['event_id']:6} {t['ui_category']:10} {w:72} {t['metrics']['failed']:<6} {verdict}"
              + (f"  warn: {warn}" if warn else ""))
    print(f"\n{len(traces)} events, {total_failed} failed calls, model {config.LLM_MODEL}")
    return 1 if total_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
