"""All on-screen numbers come from the scored run artifacts - never hardcode."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRACES = ROOT / "traces"
EXPORTS = ROOT / "exports"
RUN_LOG = ROOT / "runs" / "final_v2" / "action_log.jsonl"
HANDBOOK = ROOT / "config" / "policies" / "handbook_v1.yaml"
SELF_CHECK = ROOT / "eval" / "self_check_report.md"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load() -> dict:
    summary = json.loads((TRACES / "run_summary.json").read_text(encoding="utf-8"))
    totals = summary["totals"]
    traces = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(TRACES.glob("E-*.json"))}
    cats = Counter(t.get("ui_category") for t in traces.values())
    actionable = cats.get("delay", 0) + cats.get("outage", 0) + cats.get("quality", 0) + cats.get("compound", 0)
    noise = cats.get("noise", 0)
    escalated = cats.get("escalated", 0)
    assert actionable + noise + escalated == totals["events"]
    stats = json.loads((EXPORTS / "graph_stats.json").read_text(encoding="utf-8"))
    # pytest count
    proc = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    m = re.search(r"(\d+)\s+tests?\s+collected", proc.stdout + proc.stderr)
    tests = int(m.group(1)) if m else 0
    # self-check passes
    report = SELF_CHECK.read_text(encoding="utf-8") if SELF_CHECK.exists() else ""
    passes = len(re.findall(r"\|\s*PASS\s*\|", report))
    e09 = next(e for e in summary["events"] if e["event_id"] == "E-09")
    e01 = next(e for e in summary["events"] if e["event_id"] == "E-01")
    e03 = next(e for e in summary["events"] if e["event_id"] == "E-03")
    return {
        "events": totals["events"],
        "writes": totals["writes"],
        "reads": totals["reads"],
        "failed": totals["failed"],
        "escalations": totals["escalations"],
        "noise": totals["noise"],
        "incidents": totals["incidents"],
        "prompt_tokens": totals["prompt_tokens"],
        "completion_tokens": totals["completion_tokens"],
        "llm_calls": totals["llm_calls"],
        "model": summary["llm_model"],
        "actionable_events": actionable,
        "noise_events": noise,
        "escalated_events": escalated,
        "nodes": stats["nodes_total"],
        "edges": stats["edges_total"],
        "tests": tests,
        "self_check_pass": passes,
        "next_weekday": summary["config_snapshot"]["NEXT_WEEKDAY"],
        "e09_writes": e09["writes"],
        "e09_summary": e09["summary"],
        "e01_writes": e01["writes"],
        "e03_writes": e03["writes"],
        "e03_summary": e03["summary"],
        "handbook_sha": sha256(HANDBOOK),
        "action_log_sha": sha256(RUN_LOG),
        "cats": dict(cats),
    }


if __name__ == "__main__":
    print(json.dumps(load(), indent=2))
