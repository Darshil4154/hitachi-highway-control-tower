"""Read-only views over traces/: operations health and the daily briefing."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

STAGES = ("extract", "resolve", "gate", "plan", "verify", "twin", "execute", "readback")
STAGE_LABEL = {
    "extract": "Extract", "resolve": "Resolve", "gate": "Gate", "plan": "Plan",
    "verify": "Verify", "twin": "Twin", "execute": "Execute", "readback": "Read-back",
}
TYPE_LABEL = {
    "delay": "Supplier delay", "outage": "Plant outage", "quality": "Quality hold",
    "noise": "Not operational", "escalated": "Waiting on a person", "compound": "More than one problem",
}
TOOL_LABEL = {
    "mes.reschedule": "Builds moved to another day",
    "mes.transfer": "Builds sent to another plant",
    "dealer.notify": "Dealers told about a delay",
    "crm.assign_loaner": "Loaners assigned",
    "quality.hold_lot": "Lots placed on hold",
    "dealer.stop_sale": "Vehicles stopped from sale",
    "crm.notify_customer": "Owners contacted",
    "escalate": "Handed to a person",
}
REAL_TYPES = {"supplier_delay", "plant_outage", "quality_hold"}


def health_from_traces(traces: dict) -> dict:
    rows = []
    hits = misses = 0
    failed = reads = writes = tokens = 0
    models = []
    stage_totals = {name: 0.0 for name in STAGES}
    has_stages = False
    for eid, trace in traces.items():
        metrics = trace.get("metrics") or {}
        stages = metrics.get("stages_s") or {}
        if any(stages.get(name) for name in STAGES):
            has_stages = True
        for name in STAGES:
            stage_totals[name] += float(stages.get(name) or 0.0)
        cached = metrics.get("llm_cached")
        if metrics.get("cache") == "hit" or cached is True:
            hits += 1
        elif metrics.get("cache") == "miss" or cached is False:
            misses += 1
        failed += int(metrics.get("failed") or 0)
        reads += int(metrics.get("reads") or 0)
        writes += int(metrics.get("writes") or 0)
        tokens += int(metrics.get("prompt_tokens") or 0) + int(metrics.get("completion_tokens") or 0)
        model = metrics.get("llm_model") or ""
        if model and model not in models:
            models.append(model)
        runtime = float(metrics.get("runtime_s") or 0.0)
        stage_sum = sum(float(stages.get(name) or 0.0) for name in STAGES)
        rows.append({
            "event": eid, "type": TYPE_LABEL.get(trace.get("ui_category"), trace.get("ui_category") or ""),
            "runtime_s": runtime, "stage_sum_s": round(stage_sum, 4),
            "stages_s": {name: float(stages.get(name) or 0.0) for name in STAGES},
            "tokens": int(metrics.get("prompt_tokens") or 0) + int(metrics.get("completion_tokens") or 0),
            "cache": "hit" if (metrics.get("cache") == "hit" or cached is True) else (
                "miss" if (metrics.get("cache") == "miss" or cached is False) else "—"),
            "reads": int(metrics.get("reads") or 0), "writes": int(metrics.get("writes") or 0),
            "failed": int(metrics.get("failed") or 0), "model": model,
        })
    called = hits + misses
    slowest = sorted(rows, key=lambda r: (r["stage_sum_s"] or r["runtime_s"]), reverse=True)
    return {
        "events": len(rows), "rows": rows, "has_stages": has_stages,
        "stage_totals": {name: round(stage_totals[name], 4) for name in STAGES},
        "stage_labels": STAGE_LABEL, "slowest": slowest[:5],
        "cache_hits": hits, "cache_misses": misses,
        "cache_hit_rate": (hits / called) if called else None,
        "failed": failed, "reads": reads, "writes": writes, "tokens": tokens,
        "models": models,
    }


def _plant_name(plant_id: str | None) -> str:
    if not plant_id:
        return "a plant"
    try:
        from .data_loader import get_store
        plant = get_store().plants.get(plant_id)
    except Exception:
        plant = None
    return plant.name if plant else plant_id


def _tier_of(customer_id: str) -> str:
    try:
        from .data_loader import get_store
        person = get_store().customers.get(customer_id)
    except Exception:
        person = None
    return person.tier if person else ""


def _why(reason: str) -> str:
    low = (reason or "").lower()
    if "hedge" in low or "unconfirmed" in low or "not confirmed" in low or "firm" in low:
        return "the message was not firm enough to act on"
    if "verifier" in low:
        return "the checker blocked the plan"
    if "no slot" in low or "no feasible" in low:
        return "a build had no open day left"
    if "validation" in low or "shipment" in low or "lot" in low:
        return "a shipment or lot could not be confirmed"
    return "it needs a person to decide"


def build_briefing(traces: dict) -> dict:
    by_type: Counter[str] = Counter()
    tool_counts: Counter[str] = Counter()
    customers: set[str] = set()
    platinum = gold = 0
    loaners_assigned = loaners_requested = 0
    protected_platinum = protected_gold = 0
    lots: set[str] = set()
    vins: set[str] = set()
    open_items = []
    failed = 0
    handled = 0
    noise = 0
    largest = None
    for eid, trace in traces.items():
        label = TYPE_LABEL.get(trace.get("ui_category"), trace.get("ui_category") or "Other")
        by_type[label] += 1
        metrics = trace.get("metrics") or {}
        failed += int(metrics.get("failed") or 0)
        gate = (trace.get("classification") or {}).get("gate")
        if gate == "noise" or trace.get("ui_category") == "noise":
            noise += 1
        if (trace.get("escalation") or {}).get("escalated"):
            open_items.append({"event": eid, "why": _why((trace.get("escalation") or {}).get("reason") or "")})
        for action in trace.get("actions") or []:
            if action.get("kind") == "read" or not action.get("ok", True):
                continue
            tool_counts[action.get("tool") or "other"] += 1
            if action.get("tool") == "quality.hold_lot":
                lot = (action.get("args") or {}).get("lot_id")
                if lot:
                    lots.add(lot)
            if action.get("tool") == "dealer.stop_sale":
                for vin in (action.get("args") or {}).get("vins") or []:
                    vins.add(vin)
        if gate != "incident":
            continue
        for item in trace.get("incidents") or []:
            if item.get("type") not in REAL_TYPES:
                continue
            handled += 1
            affected = item.get("affected") or {}
            weight = len(affected.get("customer_orders") or []) or len(affected.get("production_orders") or [])
            weight = max(weight, len(affected.get("vehicles_unsold") or []) + len(affected.get("vehicles_sold") or []))
            plant = _plant_name((item.get("disruption") or {}).get("plant_id"))
            kind = {"supplier_delay": "supplier delay", "plant_outage": "plant outage",
                    "quality_hold": "quality hold"}.get(item.get("type"), "disruption")
            noun = "vehicles" if kind == "quality hold" else "orders"
            if largest is None or weight > largest["weight"]:
                largest = {"weight": weight, "plant": plant, "kind": kind, "event": eid, "noun": noun}
            for cid in affected.get("customers") or []:
                if cid in customers:
                    continue
                customers.add(cid)
                tier = _tier_of(cid)
                if tier == "Platinum":
                    platinum += 1
                elif tier == "Gold":
                    gold += 1
            for row in (item.get("decisions") or {}).get("loaners") or []:
                if row.get("decision") not in ("assigned", "skipped"):
                    continue
                loaners_requested += 1
                if row.get("decision") == "assigned":
                    loaners_assigned += 1
                    if row.get("tier") == "Platinum":
                        protected_platinum += 1
                    elif row.get("tier") == "Gold":
                        protected_gold += 1
    actions = [{"tool": tool, "label": TOOL_LABEL.get(tool, tool), "count": count}
               for tool, count in tool_counts.most_common()]
    if largest and largest["weight"]:
        big = (f"The largest disruption was a {largest['kind']} at {largest['plant']}, "
               f"touching {largest['weight']} {largest.get('noun', 'orders')} ({largest['event']}).")
    else:
        big = "No handled incident moved an order in this record."
    short = loaners_requested - loaners_assigned
    if loaners_requested == 0:
        loans = "No Platinum or Gold customer needed a loaner in this record."
    elif short <= 0:
        loans = (f"Every requested loaner was assigned: {loaners_assigned} for Platinum and Gold "
                 f"({protected_platinum} Platinum, {protected_gold} Gold).")
    else:
        loans = (f"We assigned {loaners_assigned} loaners of {loaners_requested} requested "
                 f"({protected_platinum} Platinum, {protected_gold} Gold). "
                 f"{short} eligible customers waited because the dealer pool was empty.")
    if failed == 0:
        quiet = (f"No call failed. {noise} messages were set aside as not operational. "
                 f"{len(open_items)} items are still waiting for a person.")
    else:
        quiet = (f"{failed} calls failed. {noise} messages were set aside as not operational. "
                 f"{len(open_items)} items are still waiting for a person.")
    return {
        "events_received": len(traces),
        "by_type": [{"type": name, "count": count} for name, count in by_type.most_common()],
        "incidents_handled": handled,
        "actions": actions,
        "customers_affected": len(customers),
        "platinum": platinum, "gold": gold,
        "platinum_gold_protected": protected_platinum + protected_gold,
        "protected_platinum": protected_platinum, "protected_gold": protected_gold,
        "loaners_assigned": loaners_assigned, "loaners_requested": loaners_requested,
        "lots_held": len(lots), "vehicles_stopped": len(vins),
        "open_escalations": open_items, "failed": failed, "noise": noise,
        "highlights": [big, loans, quiet],
    }


def to_markdown(briefing: dict) -> str:
    lines = [
        "# Daily briefing",
        "",
        "This note is read from the recorded run. It does not send anything.",
        "",
        "## What came in",
        "",
        f"{briefing['events_received']} messages.",
    ]
    for row in briefing["by_type"]:
        lines.append(f"- {row['count']} {row['type'].lower()}")
    lines += ["", "## What was handled", "",
              f"{briefing['incidents_handled']} incidents were handled.", ""]
    if briefing["actions"]:
        lines.append("Actions:")
        for row in briefing["actions"]:
            lines.append(f"- {row['count']} — {row['label']}")
    else:
        lines.append("No operational action was recorded.")
    lines += [
        "", "## Customers", "",
        f"{briefing['customers_affected']} customers were in the path of a handled incident "
        f"({briefing['platinum']} Platinum, {briefing['gold']} Gold).",
        f"Platinum and Gold protected with a loaner: {briefing['platinum_gold_protected']} "
        f"({briefing['protected_platinum']} Platinum, {briefing['protected_gold']} Gold).",
        f"Loaners assigned {briefing['loaners_assigned']} of {briefing['loaners_requested']} requested.",
        "", "## Quality", "",
        f"{briefing['lots_held']} lots held. {briefing['vehicles_stopped']} vehicles stopped from sale.",
        "", "## Waiting on a person", "",
    ]
    if briefing["open_escalations"]:
        for item in briefing["open_escalations"]:
            lines.append(f"- {item['event']}: {item['why']}.")
    else:
        lines.append("Nothing is waiting.")
    lines += ["", "## Calls", ""]
    if briefing["failed"] == 0:
        lines.append("0 failed calls.")
    else:
        lines.append(f"{briefing['failed']} failed calls.")
    lines += ["", "## Three things worth saying", ""]
    for i, line in enumerate(briefing["highlights"], 1):
        lines.append(f"{i}. {line}")
    lines.append("")
    return "\n".join(lines)


def to_pdf(briefing: dict) -> bytes:
    """One page. The same sentences as the Markdown note, set tighter."""
    from fpdf import FPDF

    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    pdf.set_margins(16, 14, 16)
    width = pdf.epw

    def paragraph(text: str, size: int = 9, bold: bool = False) -> None:
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B" if bold else "", size)
        pdf.multi_cell(width, 4.6 if size < 12 else 7, text)

    paragraph("Daily briefing", 16, True)
    paragraph("Read from the recorded run. Nothing in this note was sent.")
    paragraph("What came in", 11, True)
    bits = ", ".join(f"{row['count']} {row['type'].lower()}" for row in briefing["by_type"])
    paragraph(f"{briefing['events_received']} messages. {bits}.")
    paragraph("What was handled", 11, True)
    paragraph(f"{briefing['incidents_handled']} incidents were handled.")
    for row in briefing["actions"]:
        paragraph(f"- {row['count']}  {row['label']}")
    paragraph("Customers", 11, True)
    paragraph(f"{briefing['customers_affected']} customers in the path "
              f"({briefing['platinum']} Platinum, {briefing['gold']} Gold). "
              f"Loaners assigned {briefing['loaners_assigned']} of {briefing['loaners_requested']} requested. "
              f"Platinum and Gold given a loaner: {briefing['platinum_gold_protected']}.")
    paragraph("Quality", 11, True)
    paragraph(f"{briefing['lots_held']} lots held. {briefing['vehicles_stopped']} vehicles stopped from sale.")
    paragraph("Waiting on a person", 11, True)
    if briefing["open_escalations"]:
        for item in briefing["open_escalations"]:
            paragraph(f"- {item['event']}: {item['why']}.")
    else:
        paragraph("Nothing is waiting.")
    paragraph("Calls", 11, True)
    paragraph("0 failed calls." if briefing["failed"] == 0 else f"{briefing['failed']} failed calls.")
    paragraph("Three things worth saying", 11, True)
    for i, line in enumerate(briefing["highlights"], 1):
        paragraph(f"{i}. {line}")
    return bytes(pdf.output())


def splice_stage_metrics(trace_path: Path, stages_s: dict, cache: str) -> None:
    """Insert stage timings into one trace file without rewriting the rest of it."""
    text = trace_path.read_text(encoding="utf-8")
    data = json.loads(text)
    metrics = data.get("metrics") or {}
    metrics["stages_s"] = {name: round(float(stages_s.get(name, 0.0)), 4) for name in STAGES}
    metrics["cache"] = cache
    dumped = json.dumps(metrics, indent=2)
    indented = "\n".join("  " + line for line in dumped.splitlines())
    replacement = '  "metrics": ' + indented[2:] + ","
    start = text.index('  "metrics":')
    end = text.index('  "ui_category"')
    trace_path.write_text(text[:start] + replacement + "\n" + text[end:], encoding="utf-8")
