"""Twin-only what-if. The scored planner and verifier run; nothing is sent to a server."""
from __future__ import annotations

from datetime import date, timedelta

from . import policy_model, verifier
from .agents.coordinator import Coordinator
from .data_loader import TODAY, DataStore, get_store
from .tools_client import ToolsClient

BANNER = "simulation, not executed"
KINDS = ("plant_outage", "supplier_delay", "quality_hold")
KIND_LABEL = {"plant_outage": "Plant outage", "supplier_delay": "Supplier delay", "quality_hold": "Quality hold"}


def date_choices(start: date | None = None, days: int = 76) -> list[str]:
    start = start or (TODAY - timedelta(days=7))
    return [(start + timedelta(days=i)).isoformat() for i in range(days)]


def catalogs(ds: DataStore | None = None) -> dict:
    ds = ds or get_store()
    plants = [{"id": p.plant_id, "label": f"{p.name} ({p.plant_id})"} for p in ds.plants.values()]
    plants.sort(key=lambda r: r["label"])
    parts = [{"id": p.part_id, "label": f"{p.name} ({p.part_id})"} for p in ds.parts.values()]
    parts.sort(key=lambda r: r["label"])
    suppliers = [{"id": s.supplier_id, "label": f"{s.name} ({s.supplier_id})"} for s in ds.suppliers.values()]
    suppliers.sort(key=lambda r: r["label"])
    shipments = []
    for sh in ds.shipments.values():
        part = ds.parts[sh.part_id].name
        shipments.append({
            "id": sh.shipment_id, "part_id": sh.part_id, "plant_id": sh.plant_id,
            "supplier_id": sh.supplier_id, "eta": sh.eta_date.isoformat(),
            "label": f"{sh.shipment_id} · {part} to {ds.plants[sh.plant_id].name} due {sh.eta_date.isoformat()}",
        })
    shipments.sort(key=lambda r: (r["eta"], r["label"]))
    lots = []
    for lot in ds.part_lots.values():
        lots.append({
            "id": lot.lot_id, "part_id": lot.part_id, "plant_id": lot.plant_id,
            "supplier_id": lot.supplier_id,
            "window_from": lot.first_build_date.isoformat(), "window_to": lot.last_build_date.isoformat(),
            "label": (f"{lot.lot_id} · {ds.parts[lot.part_id].name} at {ds.plants[lot.plant_id].name}, "
                      f"{lot.first_build_date.isoformat()} to {lot.last_build_date.isoformat()}"),
        })
    lots.sort(key=lambda r: r["label"])
    return {"plants": plants, "parts": parts, "suppliers": suppliers, "shipments": shipments,
            "lots": lots, "dates": date_choices()}


def _parse(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _message(kind: str, fields: dict) -> str:
    """A sentence that contains every id and date the resolver is asked to accept."""
    if kind == "supplier_delay":
        bits = ["What-if supplier delay."]
        if fields.get("shipment_id"):
            bits.append(f"Shipment {fields['shipment_id']}.")
        bits.append(f"Part {fields['part_id']} from supplier {fields['supplier_id']} to plant {fields['plant_id']}.")
        bits.append(f"Original {fields['original_eta']} now {fields['new_eta']}.")
        return " ".join(bits)
    if kind == "plant_outage":
        return f"What-if plant outage. Plant {fields['plant_id']} is down from {fields['start']} through {fields['end']}."
    return (f"What-if quality hold. Lot {fields['lot_id']} part {fields['part_id']} "
            f"supplier {fields['supplier_id']} plant {fields['plant_id']} "
            f"from {fields['window_from']} through {fields['window_to']}.")


def _resolve(spec: dict, ds: DataStore) -> tuple[dict | None, str | None]:
    kind = spec.get("kind")
    if kind not in KINDS:
        return None, "Pick a scenario type: plant outage, supplier delay, or quality hold."
    if kind == "plant_outage":
        plant, start, end = spec.get("plant_id"), _parse(spec.get("start")), _parse(spec.get("end"))
        if plant not in ds.plants or not start or not end:
            return None, "Choose a plant, a start date, and an end date."
        if end < start:
            return None, "The outage end is before the start."
        raw = {"type": kind, "is_confirmed": True, "plant_mention": plant,
               "start_phrase": start.isoformat(), "end_phrase": end.isoformat()}
        fields = {"plant_id": plant, "start": start.isoformat(), "end": end.isoformat()}
    elif kind == "supplier_delay":
        ship = ds.shipments.get(spec.get("shipment_id") or "")
        part = ship.part_id if ship else spec.get("part_id")
        plant = ship.plant_id if ship else spec.get("plant_id")
        sup = ship.supplier_id if ship else spec.get("supplier_id")
        orig = ship.eta_date if ship else _parse(spec.get("original_eta"))
        new = _parse(spec.get("new_eta"))
        if not part or plant not in ds.plants or not orig or not new:
            return None, "Choose a part, a plant, the original arrival, and a later arrival. A shipment fills the first three."
        if sup and sup not in ds.suppliers:
            return None, "That supplier is not in the table."
        if part not in ds.parts:
            return None, "That part is not in the table."
        if new <= orig:
            return None, "The new arrival has to be after the original arrival."
        raw = {"type": kind, "is_confirmed": True, "part_mention": part, "plant_mention": plant,
               "supplier_mention": sup, "shipment_id": ship.shipment_id if ship else None,
               "original_eta_phrase": orig.isoformat(), "new_eta_phrase": new.isoformat()}
        fields = {"part_id": part, "plant_id": plant, "supplier_id": sup or "",
                  "shipment_id": ship.shipment_id if ship else "",
                  "original_eta": orig.isoformat(), "new_eta": new.isoformat()}
    else:
        lot = ds.part_lots.get(spec.get("lot_id") or "")
        if lot is None:
            return None, "Choose a lot from the table."
        part = spec.get("part_id") or lot.part_id
        plant = spec.get("plant_id") or lot.plant_id
        sup = spec.get("supplier_id") or lot.supplier_id
        wf = _parse(spec.get("window_from")) or lot.first_build_date
        wt = _parse(spec.get("window_to")) or lot.last_build_date
        raw = {"type": kind, "is_confirmed": True, "lot_id": lot.lot_id, "part_mention": part,
               "plant_mention": plant, "supplier_mention": sup,
               "window_from_phrase": wf.isoformat(), "window_to_phrase": wt.isoformat()}
        fields = {"lot_id": lot.lot_id, "part_id": part, "plant_id": plant, "supplier_id": sup,
                  "window_from": wf.isoformat(), "window_to": wt.isoformat()}
    from .resolvers import resolve_incident
    resolved = resolve_incident(raw, _message(kind, fields), ds)
    return resolved, None


def _plant(ds: DataStore, plant_id: str | None) -> str:
    if not plant_id:
        return ""
    plant = ds.plants.get(plant_id)
    return f"{plant.name} ({plant_id})" if plant else plant_id


def _customer(ds: DataStore, customer_id: str) -> str:
    person = ds.customers.get(customer_id)
    if not person:
        return customer_id
    return f"{person.name}, {person.tier}"


def _present(trace: dict, ds: DataStore, label: str) -> dict:
    plan = list(trace.get("plan") or [])
    blocked = False
    if not plan and trace.get("plan_rejected"):
        plan = list(trace["plan_rejected"])
        blocked = True
    incidents = trace.get("incidents") or []
    orders, customers, dealers = [], [], []
    for item in incidents:
        affected = item.get("affected") or {}
        orders.extend(affected.get("production_orders") or [])
        customers.extend(affected.get("customers") or [])
        dealers.extend(affected.get("dealers") or [])
    orders = list(dict.fromkeys(orders))
    customers = list(dict.fromkeys(customers))
    moved: dict[str, date] = {}
    transfers = []
    notify = []
    for action in plan:
        tool, args = action.get("tool"), action.get("args") or {}
        if tool in ("mes.reschedule", "mes.transfer"):
            moved[args["production_order_id"]] = date.fromisoformat(args["new_date"])
        if tool == "mes.transfer":
            po = ds.production_orders[args["production_order_id"]]
            transfers.append({
                "order": po.production_order_id, "units": po.units,
                "from": _plant(ds, po.plant_id), "to": _plant(ds, args.get("to_plant_id")),
                "date": args.get("new_date"),
            })
        if tool == "dealer.notify":
            dealer = ds.dealers.get(args.get("dealer_id"))
            notify.append(dealer.name if dealer else args.get("dealer_id"))
    units = sum(ds.production_orders[po].units for po in orders if po in ds.production_orders)
    tier_counts = {"Platinum": 0, "Gold": 0, "Standard": 0}
    named = []
    for cid in customers:
        person = ds.customers.get(cid)
        tier = person.tier if person else ""
        if tier in tier_counts:
            tier_counts[tier] += 1
        named.append(_customer(ds, cid))
    loaners = [d for item in incidents for d in (item.get("decisions") or {}).get("loaners") or []]
    eligible = [d for d in loaners if d.get("decision") in ("assigned", "skipped")]
    assigned = [d for d in eligible if d["decision"] == "assigned"]
    pools: dict[str, int] = {}
    for row in eligible:
        pools.setdefault(row["dealer"], ds.loaners.get(row["dealer"], 0))
    misses = []
    seen_co: set[str] = set()
    co_ids = []
    for item in incidents:
        co_ids.extend((item.get("affected") or {}).get("customer_orders") or [])
    if not co_ids:
        for po in orders:
            co_ids.extend(co.customer_order_id for co in ds.customer_orders_by_po.get(po, []))
    for co_id in co_ids:
        if co_id in seen_co or co_id not in ds.customer_orders:
            continue
        seen_co.add(co_id)
        co = ds.customer_orders[co_id]
        po = ds.production_orders.get(co.production_order_id)
        if po is None:
            continue
        build = moved.get(po.production_order_id, po.build_date)
        dealer = ds.dealers[co.dealer_id]
        arrive = build + timedelta(days=dealer.transit_days)
        if arrive > co.promised_date:
            misses.append({
                "order": co.customer_order_id, "customer": _customer(ds, co.customer_id),
                "dealer": dealer.name, "promised": co.promised_date.isoformat(),
                "arrival": arrive.isoformat(), "build": build.isoformat(),
            })
    checks = (trace.get("verifier") or {}).get("plan_checks", []) + (trace.get("verifier") or {}).get("world_checks", [])
    failed_checks = [c["name"] for c in checks if not c.get("ok") and c.get("blocking", True)]
    paths = [((item.get("graph_path") or {}).get("text") or "").strip() for item in incidents]
    paths = [p for p in paths if p]
    order_rows = []
    for po_id in orders:
        po = ds.production_orders.get(po_id)
        if po is None:
            continue
        order_rows.append({
            "order": po_id, "plant": _plant(ds, po.plant_id), "units": po.units,
            "build": po.build_date.isoformat(),
            "new_build": moved[po_id].isoformat() if po_id in moved else po.build_date.isoformat(),
        })
    return {
        "ok": True, "banner": BANNER, "label": label, "kind": incidents[0]["type"] if incidents else "",
        "kind_label": KIND_LABEL.get(incidents[0]["type"], "") if incidents else "",
        "summary": trace.get("summary") or "",
        "verifier_ok": bool(checks) and not failed_checks and not blocked,
        "verifier_blocked": blocked or bool(failed_checks),
        "failed_checks": failed_checks,
        "affected_orders": len(orders), "order_rows": order_rows, "units": units,
        "customers": len(customers), "customer_names": named, "tiers": tier_counts,
        "platinum_gold": tier_counts["Platinum"] + tier_counts["Gold"],
        "dealers": list(dict.fromkeys(notify)) or [ds.dealers[d].name for d in dict.fromkeys(dealers) if d in ds.dealers],
        "loaners_needed": len(eligible), "loaners_assigned": len(assigned),
        "loaners_available": sum(pools.values()),
        "transfers": transfers, "promise_misses": misses,
        "graph_path": "\n".join(paths),
        "escalated": bool((trace.get("escalation") or {}).get("escalated")),
    }


def simulate(spec: dict, ds: DataStore | None = None, label: str = "What-if") -> dict:
    """Run the handbook planner and verifier on a dry-run twin. No HTTP."""
    ds = ds or get_store()
    resolved, error = _resolve(spec, ds)
    if error:
        return {"ok": False, "banner": BANNER, "label": label, "error": error, "summary": error}
    eid = "WHATIF-" + "".join(ch for ch in label if ch.isalnum())[:12] or "WHATIF"
    client = ToolsClient(dry_run=True)
    client.mark(eid, "incident")
    coord = Coordinator(client, ds)
    trace = {"incidents": [], "plan": [], "verifier": {"plan_checks": [], "world_checks": []},
             "actions": [], "escalation": {"escalated": False, "reason": "", "missing_fields": []},
             "schedule": None}
    with policy_model.using(policy_model.load("handbook_v1")):
        coord._handle_incidents(eid, "what-if simulation", [resolved], trace, simulate=True)
    trace.pop("_stages", None)
    trace.pop("_clock", None)
    if any(not c["ok"] for c in client.calls):
        # A dry-run read can fail closed. Surface it; do not pretend the twin applied a write.
        pass
    report = _present(trace, ds, label)
    report["calls"] = len(client.calls)
    report["server_calls"] = 0
    return report


def comparison_rows(left: dict | None, right: dict | None) -> list[dict]:
    def val(report: dict | None, key: str, default: str = "—"):
        if not report or not report.get("ok"):
            if report and report.get("error") and key == "kind_label":
                return "Could not run"
            return default
        if key == "dealers":
            return len(report.get("dealers") or [])
        if key == "transfers":
            return len(report.get("transfers") or [])
        if key == "promise_misses":
            return len(report.get("promise_misses") or [])
        if key == "platinum_gold":
            tiers = report.get("tiers") or {}
            return f"{tiers.get('Platinum', 0)} Platinum, {tiers.get('Gold', 0)} Gold"
        if key == "loaners":
            return f"{report.get('loaners_needed', 0)} needed, {report.get('loaners_available', 0)} available"
        return report.get(key, default)

    labels = [
        ("Scenario", "kind_label"), ("Affected orders", "affected_orders"), ("Units delayed", "units"),
        ("Customers", "customers"), ("Platinum / Gold", "platinum_gold"),
        ("Dealers to notify", "dealers"), ("Loaners", "loaners"), ("Transfers", "transfers"),
        ("Promise misses", "promise_misses"), ("Verifier clear", "verifier_ok"),
    ]
    rows = []
    for title, key in labels:
        rows.append({"Metric": title, "A": val(left, key), "B": val(right, key)})
    return rows
