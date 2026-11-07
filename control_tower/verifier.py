"""Policy verifier (guardrail). Recomputes expected sets straight from the tables - not via the planners -
and checks a plan (before execution) and a world state (after the twin dry run) against R1-R10."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from . import config
from .data_loader import LAST_IDX, LOANER_TIERS, TIER_RANK, DataStore, date_to_idx, idx_to_date, next_working_day

MOVE_TOOLS = {"mes.reschedule", "mes.transfer"}
WRITE_KINDS = {"mes.reschedule", "mes.transfer", "dealer.notify", "dealer.stop_sale", "crm.assign_loaner",
               "crm.notify_customer", "quality.hold_lot"}


def _check(name: str, ok: bool, detail: str = "", blocking: bool = True) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail, "blocking": blocking}


def expected_for_incident(ds: DataStore, inc: dict) -> dict:
    """Independent recomputation of an incident's affected orders, blocks and restart."""
    t = inc["type"]
    if t == "supplier_delay":
        plant, part = inc["plant_id"], inc["part_id"]
        orig, new = date.fromisoformat(inc["blocked_from"]), date.fromisoformat(inc["blocked_until_excl"])
        pos = {p.production_order_id for p in ds.production_orders.values()
               if p.plant_id == plant and part in ds.bom[p.model] and orig <= p.build_date < new and p.idx >= 0}
        models = {m for m, parts in ds.bom.items() if part in parts}
        restart = new
        while restart.weekday() > 4:
            restart = next_working_day(restart)
        return {"pos": pos, "plant": plant, "from": orig, "to_excl": new, "models": models, "restart": restart}
    if t == "plant_outage":
        plant = inc["plant_id"]
        start, end = date.fromisoformat(inc["blocked_from"]), date.fromisoformat(inc["blocked_to_incl"])
        pos = {p.production_order_id for p in ds.production_orders.values()
               if p.plant_id == plant and start <= p.build_date <= end and p.idx >= 0}
        return {"pos": pos, "plant": plant, "from": start, "to_incl": end, "models": None,
                "restart": next_working_day(end)}
    lot = ds.part_lots[inc["lot_id"]]
    vins = {v.vin for v in ds.vehicles.values() if v.plant_id == lot.plant_id and lot.part_id in ds.bom[v.model]
            and lot.first_build_date <= v.build_date <= lot.last_build_date}
    return {"pos": set(), "lot": lot.lot_id, "vins": vins,
            "unsold": {v for v in vins if ds.vehicles[v].status == "in_stock"},
            "owners": {ds.vehicles[v].customer_id for v in vins if ds.vehicles[v].status == "sold"}}


def _blocked(exp: list[dict], plant: str, d: date, model: str) -> bool:
    for e in exp:
        if e.get("plant") != plant or "from" not in e:
            continue
        inside = e["from"] <= d < e["to_excl"] if "to_excl" in e else e["from"] <= d <= e["to_incl"]
        if inside and (e["models"] is None or model in e["models"]):
            return True
    return False


def check_plan(ds: DataStore, plan: list[dict], incidents: list[dict], pools: dict[str, int],
               escalated_pos: set[str]) -> list[dict]:
    checks: list[dict] = []
    exp = [expected_for_incident(ds, i) for i in incidents]
    affected = set().union(*(e["pos"] for e in exp)) if exp else set()
    restart: dict[str, date] = {}
    for e in exp:
        for p in e["pos"]:
            restart[p] = max(restart.get(p, e["restart"]), e["restart"])
    moves = [a for a in plan if a["tool"] in MOVE_TOOLS]
    moved = [a["args"]["production_order_id"] for a in moves]

    checks.append(_check("R10 only affected orders are moved", set(moved) <= affected,
                         f"unaffected moved: {sorted(set(moved) - affected)}" if set(moved) - affected else
                         f"{len(moved)} moves, all affected"))
    checks.append(_check("R3 each order moved at most once", len(moved) == len(set(moved))))
    missing = affected - set(moved) - escalated_pos
    checks.append(_check("R3 every affected order is moved or escalated", not missing,
                         f"not handled: {sorted(missing)}" if missing else f"{len(affected)} affected handled"))

    cap = {p.plant_id: p.slots_per_day for p in ds.plants.values()}
    used: dict[tuple[str, int], int] = defaultdict(int)
    loc: dict[str, tuple[str, int]] = {}
    for p in ds.production_orders.values():
        if p.idx >= 0:
            used[(p.plant_id, p.idx)] += 1
            loc[p.production_order_id] = (p.plant_id, p.idx)
    over, blocked_hits, early, bad_plant, not_earliest = [], [], [], [], []
    for a in moves:
        po = a["args"]["production_order_id"]
        model = ds.production_orders[po].model
        origin = loc[po][0]
        plant = a["args"].get("to_plant_id", origin)
        d = date.fromisoformat(a["args"]["new_date"])
        i = date_to_idx(d)
        if a["tool"] == "mes.transfer" and (plant == origin or model not in ds.plant_models[plant]):
            bad_plant.append(po)
        if a["tool"] == "mes.reschedule" and d < restart.get(po, d):
            early.append(po)
        if _blocked(exp, plant, d, model):
            blocked_hits.append(po)
        free = lambda pl, ix: used[(pl, ix)] < cap[pl] and not _blocked(exp, pl, idx_to_date(ix), model)
        r_idx = date_to_idx(restart[po]) if po in restart and restart[po] <= idx_to_date(LAST_IDX) else LAST_IDX + 1
        same_plant_option = next((ix for ix in range(max(r_idx, 0), LAST_IDX + 1) if free(origin, ix)), None)
        if a["tool"] == "mes.reschedule" and same_plant_option is not None and same_plant_option < i:
            not_earliest.append(po)
        if a["tool"] == "mes.transfer":
            if same_plant_option is not None:
                not_earliest.append(po)
            else:
                lb = 0 if config.TRANSFER_LOWER_BOUND == "today" else max(r_idx, 0)
                order = [pl for pl in ds.plant_order() if pl != origin and model in ds.plant_models[pl]]
                if config.TRANSFER_SEARCH == "plant_first":
                    earlier = any(free(plant, ix) for ix in range(lb, i))
                    tie = any(free(pl, ix) for pl in order[: order.index(plant)] for ix in range(lb, LAST_IDX + 1)) \
                        if plant in order else True
                else:
                    earlier = any(free(pl, ix) for ix in range(lb, i) for pl in order)
                    tie = any(free(pl, i) for pl in order[: order.index(plant)]) if plant in order else True
                if earlier or tie:
                    not_earliest.append(po)
        if used[(plant, i)] >= cap[plant]:
            over.append(po)
        used[loc[po]] -= 1
        used[(plant, i)] += 1
        loc[po] = (plant, i)
    checks.append(_check("R3 no slot over capacity", not over, f"over: {over}" if over else ""))
    checks.append(_check("R1/R2 no move into a blocked day", not blocked_hits, f"{blocked_hits}" if blocked_hits else ""))
    checks.append(_check("R3 same-plant moves on/after restart", not early, f"{early}" if early else ""))
    checks.append(_check("R3 transfers go to another plant that builds the model", not bad_plant,
                         f"{bad_plant}" if bad_plant else ""))
    checks.append(_check("R3 earliest feasible slot chosen", not not_earliest,
                         f"{not_earliest}" if not_earliest else ""))

    aff_cos = {c.customer_order_id for p in affected for c in ds.customer_orders_by_po.get(p, [])}
    # per_event: one set per dealer. per_incident: one set per dealer per incident, each order counted once
    # (under the first incident that affects it).
    want_sets: dict[str, list[set[str]]] = defaultdict(list)
    groups = [e["pos"] for e in exp] if config.NOTIFY_SCOPE == "per_incident" else [affected]
    claimed: set[str] = set()
    for pos in groups:
        by_dealer: dict[str, set[str]] = defaultdict(set)
        for p in sorted(pos):
            for c in ds.customer_orders_by_po.get(p, []):
                if c.customer_order_id not in claimed:
                    claimed.add(c.customer_order_id)
                    by_dealer[c.dealer_id].add(c.customer_order_id)
        for d, cos in by_dealer.items():
            want_sets[d].append(cos)
    notifies = [a for a in plan if a["tool"] == "dealer.notify"]
    got: dict[str, list[set[str]]] = defaultdict(list)
    for a in notifies:
        got[a["args"]["dealer_id"]].append(set(a["args"]["customer_order_ids"]))
    canon = lambda sets: sorted(sorted(s) for s in sets)
    r4_ok = set(got) == set(want_sets) and all(canon(got[d]) == canon(want_sets[d]) for d in want_sets)
    scope = "per incident" if config.NOTIFY_SCOPE == "per_incident" else "per event"
    checks.append(_check("R4 exactly one notify per affected dealer with exactly its orders", r4_ok,
                         f"{len(want_sets)} dealers, {len(aff_cos)} customer orders ({scope})"))

    assigned = {a["args"]["customer_order_id"] for a in plan if a["tool"] == "crm.assign_loaner"}
    exp_assigned: set[str] = set()
    elig: dict[str, list[str]] = defaultdict(list)
    for c in aff_cos:
        co = ds.customer_orders[c]
        if ds.customers[co.customer_id].tier in LOANER_TIERS:
            elig[co.dealer_id].append(c)
    for d, cs in elig.items():
        cs.sort(key=lambda c: (TIER_RANK[ds.customers[ds.customer_orders[c].customer_id].tier],
                               ds.customer_orders[c].promised_date, c))
        exp_assigned |= set(cs[: max(pools.get(d, 0), 0)])
    checks.append(_check("R5 loaners: only Platinum/Gold, within pool, priority respected", assigned == exp_assigned,
                         f"assigned {len(assigned)} of {sum(len(v) for v in elig.values())} eligible"
                         + (f"; diff {sorted(assigned ^ exp_assigned)}" if assigned != exp_assigned else "")))

    q = [e for e in exp if "lot" in e]
    holds = {a["args"]["lot_id"] for a in plan if a["tool"] == "quality.hold_lot"}
    stops: dict[str, set[str]] = defaultdict(set)
    stop_calls: dict[str, int] = defaultdict(int)
    for a in plan:
        if a["tool"] == "dealer.stop_sale":
            stops[a["args"]["dealer_id"]] |= set(a["args"]["vins"])
            stop_calls[a["args"]["dealer_id"]] += 1
    owners = [a["args"]["customer_id"] for a in plan if a["tool"] == "crm.notify_customer"]
    want_unsold = set().union(*(e["unsold"] for e in q)) if q else set()
    want_owners = set().union(*(e["owners"] for e in q)) if q else set()
    stop_ok = all(ds.vehicles[v].dealer_id == d for d, vs in stops.items() for v in vs)
    checks.append(_check("R6 hold exactly the suspect lot(s)", holds == {e["lot"] for e in q}, f"{sorted(holds)}"))
    checks.append(_check("R6 every unsold affected vehicle stopped at its dealer (one call per dealer)",
                         set().union(*stops.values()) == want_unsold and stop_ok
                         and all(n == 1 for n in stop_calls.values()) if stops or want_unsold else True,
                         f"{len(want_unsold)} unsold vehicles at {len(stops)} dealers"))
    checks.append(_check("R6 every owner of a sold affected vehicle contacted once",
                         set(owners) == want_owners and len(owners) == len(set(owners)),
                         f"{len(want_owners)} owners"))

    kinds = {a["tool"] for a in plan if a["tool"] in WRITE_KINDS}
    checks.append(_check("R9 at least three different kinds of action", len(kinds) >= 3 or not incidents,
                         f"{len(kinds)} kinds: {', '.join(sorted(kinds))}", blocking=False))
    return checks


def check_world(twin, plan: list[dict], dry_results: list[dict]) -> list[dict]:
    s = twin.state
    checks = [_check("twin dry run: zero failed calls", all(r["ok"] for r in dry_results),
                     "; ".join(f"{r['tool']}: {r['error']}" for r in dry_results if not r["ok"]))]
    wrong_loc = []
    for a in plan:
        if a["tool"] in MOVE_TOOLS:
            po = a["args"]["production_order_id"]
            want_plant = a["args"].get("to_plant_id", s["loc"][po][0])
            if s["loc"][po] != (want_plant, date_to_idx(date.fromisoformat(a["args"]["new_date"]))):
                wrong_loc.append(po)
    checks.append(_check("world: every moved order is at its planned slot", not wrong_loc, f"{wrong_loc}"))
    over = [k for k, v in s["slots"].items() if len(v) > twin.ent.plants[k[0]]["slots"]]
    checks.append(_check("world: no plant-day over capacity", not over, f"{over[:5]}"))
    checks.append(_check("world: no loaner pool below zero", all(v >= 0 for v in s["loaners"].values())))
    planned_loans = {a["args"]["customer_order_id"] for a in plan if a["tool"] == "crm.assign_loaner"}
    checks.append(_check("world: loaners match plan", s["loaned"] == planned_loans))
    planned_lots = {a["args"]["lot_id"] for a in plan if a["tool"] == "quality.hold_lot"}
    checks.append(_check("world: held lots match plan", s["held"] == planned_lots))
    planned_vins = {v for a in plan if a["tool"] == "dealer.stop_sale" for v in a["args"]["vins"]}
    checks.append(_check("world: stopped VINs match plan", s["stopped"] == planned_vins))
    planned_cust = {a["args"]["customer_id"] for a in plan if a["tool"] == "crm.notify_customer"}
    checks.append(_check("world: contacted customers match plan", s["customers"] == planned_cust))
    return checks


def passed(checks: list[dict]) -> bool:
    return all(c["ok"] for c in checks if c.get("blocking", True))
