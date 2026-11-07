"""Ask the control tower: read-only questions over the knowledge graph and the traces.

The LLM only picks one function and its arguments (OpenAI tool calling). Answers are rendered by code from the
function result, with the graph path. Nothing here calls /act. If the LLM is unavailable, a deterministic
keyword/id router picks the function instead.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

from . import config
from .data_loader import get_store
from .ontology import get_graph, nid

EXAMPLES = [
    "Who is affected by E-09?",
    "Which dealers were notified for E-01?",
    "Which customers at D20 got a loaner after E-01, and who was skipped?",
    "What is scheduled at P_AL on 2027-04-01?",
    "Which vehicles are in lot LOT-0191?",
    "How is CAM-360 connected to D25?",
]


def _trace(event_id: str) -> dict | None:
    p = Path(config.TRACES_DIR) / f"{event_id}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ------------------------------------------------------------------ read-only query functions
def who_is_affected(event_id: str) -> dict:
    t = _trace(event_id)
    if not t:
        return {"error": f"no trace for {event_id}"}
    out = {"event_id": event_id, "category": t["ui_category"], "incidents": []}
    for it in t["incidents"]:
        a = it.get("affected") or {}
        out["incidents"].append({"incident_id": it["incident_id"], "type": it["type"],
                                 **{k: a.get(k, []) for k in ("production_orders", "customer_orders", "dealers",
                                                              "customers", "lots", "vehicles_unsold", "vehicles_sold")},
                                 "path": (it.get("graph_path") or {}).get("text", "")})
    return out


def dealers_for_event(event_id: str) -> dict:
    t = _trace(event_id)
    if not t:
        return {"error": f"no trace for {event_id}"}
    notes = [{"dealer_id": a["args"]["dealer_id"], "customer_order_ids": a["args"]["customer_order_ids"]}
             for a in t["plan"] if a["tool"] == "dealer.notify"]
    stops = [{"dealer_id": a["args"]["dealer_id"], "vins": a["args"]["vins"]}
             for a in t["plan"] if a["tool"] == "dealer.stop_sale"]
    return {"event_id": event_id, "notified": notes, "stop_sale": stops}


def loaners_for_dealer(dealer_id: str, event_id: str | None = None) -> dict:
    ds = get_store()
    if dealer_id not in ds.dealers:
        return {"error": f"unknown dealer {dealer_id}"}
    rows = []
    events = [event_id] if event_id else sorted(p.stem for p in Path(config.TRACES_DIR).glob("E-*.json"))
    for eid in events:
        t = _trace(eid)
        for it in (t or {}).get("incidents", []):
            for d in it.get("decisions", {}).get("loaners", []):
                if d["dealer"] == dealer_id:
                    rows.append({"event_id": eid, **{k: d[k] for k in ("co", "customer", "tier", "promised", "rank",
                                                                         "decision", "reason")}})
    return {"dealer_id": dealer_id, "initial_pool": ds.loaners.get(dealer_id, 0), "decisions": rows}


def orders_at_plant_day(plant_id: str, day: str) -> dict:
    kg = get_graph()
    d = date.fromisoformat(day)
    pos, path = kg.orders_at_plant(plant_id, d, d)
    ds = get_store()
    return {"plant_id": plant_id, "date": day, "capacity": ds.plants[plant_id].slots_per_day,
            "orders": [{"production_order_id": p, "model": ds.production_orders[p].model} for p in pos],
            "path": kg.explain_path(path) if path else "", "note": "original schedule (before any event)"}


def vehicles_in_lot(lot_id: str) -> dict:
    kg, ds = get_graph(), get_store()
    if lot_id not in ds.part_lots:
        return {"error": f"unknown lot {lot_id}"}
    vins, _ = kg.vehicles_for_lot(lot_id)
    lot = ds.part_lots[lot_id]
    return {"lot_id": lot_id, "part_id": lot.part_id, "plant_id": lot.plant_id,
            "window": f"{lot.first_build_date}..{lot.last_build_date}",
            "unsold": [v for v in vins if ds.vehicles[v].status == "in_stock"],
            "sold": [v for v in vins if ds.vehicles[v].status == "sold"]}


_PREFIX = [(r"^P_[A-Z]{2}$", "Plant"), (r"^SUP-\d{2}$", "Supplier"), (r"^SH-\d{4}$", "Shipment"),
           (r"^LOT-\d{4}$", "PartLot"), (r"^PO-\d{4}$", "ProductionOrder"), (r"^CO-\d{5}$", "CustomerOrder"),
           (r"^C\d{4}$", "Customer"), (r"^D\d{2}$", "Dealer"), (r"^[A-Z]{3}\d{7}$", "Vehicle")]


def node_of(entity_id: str) -> str | None:
    ds = get_store()
    if entity_id in ds.parts:
        return nid("Part", entity_id)
    if entity_id.upper() in ds.models:
        return nid("Model", entity_id.upper())
    for pat, kind in _PREFIX:
        if re.match(pat, entity_id):
            return nid(kind, entity_id)
    return None


def path_between(a: str, b: str) -> dict:
    kg = get_graph()
    na, nb = node_of(a), node_of(b)
    if not na or not nb:
        return {"error": f"cannot map {a if not na else b} to a graph node"}
    edges = kg.path_between(na, nb)
    return {"from": na, "to": nb, "edges": edges, "path": kg.explain_path(edges, limit=20, ordered=True)}


FUNCTIONS = {f.__name__: f for f in (who_is_affected, dealers_for_event, loaners_for_dealer, orders_at_plant_day,
                                     vehicles_in_lot, path_between)}

TOOLS = [
    {"type": "function", "function": {"name": "who_is_affected", "description": "Affected production orders, "
     "customer orders and vehicles of an event (not for 'which dealers were notified').", "parameters": {"type": "object", "properties": {"event_id": {"type": "string"}},
                                                 "required": ["event_id"]}}},
    {"type": "function", "function": {"name": "dealers_for_event", "description": "Which dealers were notified "
     "(dealer.notify) or got a stop-sale for an event.", "parameters": {"type": "object", "properties": {"event_id": {"type": "string"}},
                                               "required": ["event_id"]}}},
    {"type": "function", "function": {"name": "loaners_for_dealer", "description": "Loaner decisions (assigned / "
     "skipped / standard) at a dealer, optionally for one event.", "parameters": {"type": "object", "properties": {
         "dealer_id": {"type": "string"}, "event_id": {"type": "string"}}, "required": ["dealer_id"]}}},
    {"type": "function", "function": {"name": "orders_at_plant_day", "description": "Production orders at a plant "
     "on a date (YYYY-MM-DD).", "parameters": {"type": "object", "properties": {"plant_id": {"type": "string"},
                                                                                "day": {"type": "string"}},
                                               "required": ["plant_id", "day"]}}},
    {"type": "function", "function": {"name": "vehicles_in_lot", "description": "Vehicles built with a part lot, "
     "split sold / unsold.", "parameters": {"type": "object", "properties": {"lot_id": {"type": "string"}},
                                            "required": ["lot_id"]}}},
    {"type": "function", "function": {"name": "path_between", "description": "Shortest knowledge-graph path between "
     "two entity ids (part, plant, dealer, order, lot, ...).", "parameters": {"type": "object", "properties": {
         "a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a", "b"]}}},
]


# ------------------------------------------------------------------ routing
def route(question: str) -> tuple[str, dict] | None:
    """Deterministic fallback router: ids + keywords -> (function, args)."""
    q = question
    ids = re.findall(r"\b(E-\d{2}|P_[A-Z]{2}|D\d{2}|LOT-\d{4}|\d{4}-\d{2}-\d{2}|[A-Z]{2,5}-[A-Z0-9]{2,4}|PO-\d{4}|"
                     r"SUP-\d{2}|SH-\d{4}|CO-\d{5}|C\d{4})\b", q)
    ev = next((i for i in ids if i.startswith("E-")), None)
    dealer = next((i for i in ids if re.match(r"^D\d{2}$", i)), None)
    low = q.lower()
    if re.search(r"connect|path|link|related", low):
        ents = [i for i in ids if not i.startswith("E-") and not re.match(r"\d{4}-", i)]
        if len(ents) >= 2:
            return "path_between", {"a": ents[0], "b": ents[1]}
    lot = next((i for i in ids if i.startswith("LOT-")), None)
    if lot:
        return "vehicles_in_lot", {"lot_id": lot}
    if dealer and "loaner" in low:
        return "loaners_for_dealer", {"dealer_id": dealer, **({"event_id": ev} if ev else {})}
    plant = next((i for i in ids if i.startswith("P_")), None)
    day = next((i for i in ids if re.match(r"\d{4}-\d{2}-\d{2}", i)), None)
    if plant and day:
        return "orders_at_plant_day", {"plant_id": plant, "day": day}
    if ev and re.search(r"dealer|notif|stop", low):
        return "dealers_for_event", {"event_id": ev}
    if ev:
        return "who_is_affected", {"event_id": ev}
    return None


def _llm_pick(question: str) -> tuple[str, dict] | None:
    if config.LLM_DISABLED:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY, timeout=60, max_retries=0)
        resp = client.chat.completions.create(
            model=config.LLM_MODEL, temperature=0, tools=TOOLS, tool_choice="auto",
            messages=[{"role": "system", "content": "Pick exactly one tool to answer the operations question. "
                       "Copy ids exactly as written (E-09, D12, P_AL, LOT-0191, CAM-360). Do not answer yourself."},
                      {"role": "user", "content": question}])
        calls = resp.choices[0].message.tool_calls or []
        if not calls:
            return None
        name, args = calls[0].function.name, json.loads(calls[0].function.arguments or "{}")
        return (name, args) if name in FUNCTIONS else None
    except Exception:
        return None


def render(name: str, res: dict) -> str:
    if "error" in res:
        return f"Sorry - {res['error']}."
    if name == "who_is_affected":
        if not res["incidents"]:
            return f"{res['event_id']} ({res['category']}) affected nothing: no operational action was taken."
        lines = []
        for i in res["incidents"]:
            if i["type"] == "quality_hold":
                lines.append(f"{i['incident_id']} quality hold on {', '.join(i['lots'])}: {len(i['vehicles_unsold'])} "
                             f"unsold vehicles at {len(i['dealers'])} dealers, {len(i['customers'])} owners.")
            else:
                lines.append(f"{i['incident_id']} {i['type'].replace('_', ' ')}: {len(i['production_orders'])} "
                             f"production orders ({', '.join(i['production_orders'][:8])}"
                             f"{'...' if len(i['production_orders']) > 8 else ''}), {len(i['customer_orders'])} "
                             f"customer orders, {len(i['dealers'])} dealers.")
            lines.append(f"   path: {i['path']}")
        return "\n".join(lines)
    if name == "dealers_for_event":
        n, s = res["notified"], res["stop_sale"]
        if not n and not s:
            return f"No dealer was contacted for {res['event_id']}."
        out = [f"{len(n)} dealers notified for {res['event_id']}: " + ", ".join(
            f"{x['dealer_id']} ({len(x['customer_order_ids'])})" for x in n)] if n else []
        if s:
            out.append(f"{len(s)} dealers got a stop-sale: " + ", ".join(f"{x['dealer_id']} ({len(x['vins'])} VINs)"
                                                                        for x in s))
        return "\n".join(out)
    if name == "loaners_for_dealer":
        rows = res["decisions"]
        if not rows:
            return f"No loaner decisions at {res['dealer_id']} (initial pool {res['initial_pool']})."
        out = [f"{res['dealer_id']} (initial pool {res['initial_pool']}):"]
        for r in rows:
            out.append(f"   {r['event_id']} {r['co']} {r['customer']} {r['tier']:9} promised {r['promised']} -> "
                       f"{r['decision']}" + (f" (rank {r['rank']})" if r["rank"] else ""))
        return "\n".join(out)
    if name == "orders_at_plant_day":
        o = res["orders"]
        return (f"{res['plant_id']} on {res['date']} ({res['note']}): {len(o)}/{res['capacity']} slots used - "
                + ", ".join(f"{x['production_order_id']} {x['model']}" for x in o))
    if name == "vehicles_in_lot":
        return (f"{res['lot_id']} ({res['part_id']} at {res['plant_id']}, built {res['window']}): "
                f"{len(res['unsold'])} unsold ({', '.join(res['unsold'][:6])}{'...' if len(res['unsold']) > 6 else ''}"
                f"), {len(res['sold'])} sold.")
    if name == "path_between":
        return res["path"] or "No path found."
    return json.dumps(res)[:500]


def ask(question: str, use_llm: bool = True) -> dict:
    picked = _llm_pick(question) if use_llm else None
    method = "llm_tool_call"
    if picked is None:
        picked, method = route(question), "keyword_router"
    if picked is None:
        return {"question": question, "method": "none", "function": None, "args": {}, "result": {},
                "answer": "I can answer questions about events (E-01..E-15), dealers' loaners, plant schedules, lots "
                          "and graph paths. Try: " + "; ".join(EXAMPLES[:3])}
    name, args = picked
    try:
        res = FUNCTIONS[name](**args)
    except Exception as e:  # bad args chosen by the LLM
        res = {"error": f"{type(e).__name__}: {e}"}
    return {"question": question, "method": method, "function": name, "args": args, "result": res,
            "answer": render(name, res)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Ask the control tower (read-only)")
    ap.add_argument("question", nargs="*")
    ap.add_argument("--no-llm", action="store_true")
    a = ap.parse_args()
    qs = [" ".join(a.question)] if a.question else EXAMPLES
    for q in qs:
        r = ask(q, use_llm=not a.no_llm)
        print(f"Q: {q}\n   [{r['method']}] {r['function']}({r['args']})\n{r['answer']}\n")


if __name__ == "__main__":
    main()
