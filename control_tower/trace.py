"""Trace writer: traces/<event_id>.json (SPEC section 7), run_summary.json and audit_log.csv."""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from . import config

REQUIRED_KEYS = ["event", "classification", "incidents", "plan", "verifier", "actions", "escalation", "summary",
                 "metrics", "config_snapshot"]


def _default(o):
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(f"not serializable: {type(o)}")


def validate(trace: dict) -> list[str]:
    errs = [f"missing key {k}" for k in REQUIRED_KEYS if k not in trace]
    for it in trace.get("incidents", []):
        for k in ("incident_id", "type", "evidence_quote", "extracted", "validation", "graph_path", "affected",
                  "excluded", "decisions"):
            if k not in it:
                errs.append(f"incident missing {k}")
    for a in trace.get("plan", []):
        for k in ("seq", "agent", "tool", "args", "rule_id", "reason", "evidence_path", "incident_id"):
            if k not in a:
                errs.append(f"plan action missing {k}")
    return errs


def category_label(trace: dict) -> str:
    gate = trace["classification"]["gate"]
    if gate == "noise":
        return "noise"
    if gate in ("unconfirmed", "needs_review") or not trace["plan"]:
        return "escalated"
    types = {i["type"] for i in trace["incidents"]}
    if len(trace["incidents"]) > 1:
        return "compound"
    return {"supplier_delay": "delay", "plant_outage": "outage", "quality_hold": "quality"}.get(next(iter(types)), "?")


def write(trace: dict, out_dir: Path | None = None) -> Path:
    out = Path(out_dir or config.TRACES_DIR)
    out.mkdir(parents=True, exist_ok=True)
    trace["ui_category"] = category_label(trace)
    trace["schema_errors"] = validate(trace)
    p = out / f"{trace['event']['event_id']}.json"
    p.write_text(json.dumps(trace, indent=2, default=_default, ensure_ascii=False), encoding="utf-8")
    return p


def write_run(traces: list[dict], mode: str, server: str, out_dir: Path | None = None) -> None:
    out = Path(out_dir or config.TRACES_DIR)
    rows = []
    for t in traces:
        writes: dict[str, int] = {}
        for a in t["actions"]:
            if a["kind"] != "read":
                writes[a["tool"]] = writes.get(a["tool"], 0) + 1
        ok_checks = [c for c in t["verifier"]["plan_checks"] + t["verifier"]["world_checks"] if c.get("blocking", True)]
        rows.append({
            "event_id": t["event"]["event_id"], "source": t["event"]["source"],
            "received_at": t["event"]["received_at"], "category": t["ui_category"],
            "llm_category": t["classification"]["category"], "gate": t["classification"]["gate"],
            "incident_types": [i["type"] for i in t["incidents"]],
            "writes_by_tool": writes, "writes": t["metrics"]["writes"], "reads": t["metrics"]["reads"],
            "escalations": t["metrics"]["escalations"], "failed": t["metrics"]["failed"],
            "verifier_ok": all(c["ok"] for c in ok_checks) if ok_checks else None,
            "summary": t["summary"],
        })
    summary = {"mode": mode, "server": server, "config_snapshot": config.snapshot(),
               "llm_model": traces[0]["metrics"]["llm_model"] if traces else config.LLM_MODEL,
               "totals": {"events": len(rows), "writes": sum(r["writes"] for r in rows),
                          "reads": sum(r["reads"] for r in rows), "failed": sum(r["failed"] for r in rows),
                          "escalations": sum(r["escalations"] for r in rows),
                          "noise": sum(1 for r in rows if r["category"] == "noise"),
                          "incidents": sum(len(r["incident_types"]) for r in rows if r["category"] not in
                                           ("noise", "escalated")),
                          "prompt_tokens": sum(t["metrics"]["prompt_tokens"] for t in traces),
                          "completion_tokens": sum(t["metrics"]["completion_tokens"] for t in traces),
                          "llm_calls": sum(t["metrics"]["llm_calls"] for t in traces)},
               "events": rows}
    (out / "run_summary.json").write_text(json.dumps(summary, indent=2, default=_default), encoding="utf-8")
    with (out / "audit_log.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["event_id", "seq", "agent", "tool", "kind", "target", "rule_id", "reason", "ok", "error", "ts"])
        for t in traces:
            plan = {a["seq"]: a for a in t["plan"]}
            for a in t["actions"]:
                p = plan.get(a["seq"], {}) if a["seq"] is not None else {}
                args = a["args"]
                target = (args.get("production_order_id") or args.get("dealer_id") or args.get("customer_order_id")
                          or args.get("customer_id") or args.get("lot_id") or "")
                if a["tool"] == "mes.transfer":
                    target = f"{target} -> {args['to_plant_id']} {args['new_date']}"
                elif a["tool"] == "mes.reschedule":
                    target = f"{target} -> {args['new_date']}"
                elif a["tool"] == "mes.get_schedule":
                    target = f"{args['plant_id']} {args['date']}"
                reason = p.get("reason") or (args.get("reason") if a["tool"] == "escalate" else
                                             "read-only check (free)" if a["kind"] == "read" else "")
                rule = p.get("rule_id") or (t.get("decision_rule") if a["tool"] == "escalate" else "")
                w.writerow([t["event"]["event_id"], a["seq"] or "", a["agent"], a["tool"], a["kind"], target,
                            rule or "", reason, a["ok"], a["error"] or "", a["ts"]])
