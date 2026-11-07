"""Self-check evaluator: replay an action_log.jsonl on a fresh organizer Enterprise and score it against the
handbook with a SEPARATE, minimal implementation of R1-R6 written from the handbook text.

It deliberately does not import any control_tower planner/verifier code. The only thing it takes from our run
is each event's interpreted incident parameters (plant, part, dates, lot) from traces/<event>.json, so it checks
"given this reading of the message, are the actions exactly what the handbook demands?".

python eval/self_check.py --log runs/run1/action_log.jsonl [--traces traces] [--out eval/self_check_report.md]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "enterprise" / "data"

_spec = importlib.util.spec_from_file_location("enterprise_ro", ROOT / "enterprise" / "enterprise.py")
ent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ent)

WRITES = {"mes.reschedule", "mes.transfer", "dealer.notify", "dealer.stop_sale", "crm.assign_loaner",
          "crm.notify_customer", "quality.hold_lot"}


def rows(name):
    with (DATA / name).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


D = lambda s: date.fromisoformat(s)
PLANTS = [r["plant_id"] for r in rows("plants.csv")]
SLOTS = {r["plant_id"]: int(r["slots_per_day"]) for r in rows("plants.csv")}
CAN = defaultdict(set)
for r in rows("plant_models.csv"):
    CAN[r["plant_id"]].add(r["model"])
BOM = defaultdict(set)
for r in rows("bom.csv"):
    BOM[r["model"]].add(r["part_id"])
POS = {r["production_order_id"]: r for r in rows("production_orders.csv")}
COS = {r["customer_order_id"]: r for r in rows("customer_orders.csv")}
CUST = {r["customer_id"]: r for r in rows("customers.csv")}
VEH = {r["vin"]: r for r in rows("finished_vehicles.csv")}
LOTS = {r["lot_id"]: r for r in rows("part_lots.csv")}
POOL = {r["dealer_id"]: int(r["loaners_available"]) for r in rows("loaners.csv")}
TODAY, LAST = date(2027, 3, 8), date(2027, 4, 2)


def wd_after(d):
    d += timedelta(days=1)
    while d.weekday() > 4:
        d += timedelta(days=1)
    return d


def days(a, b):
    out, d = [], a
    while d <= b:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


# ------------------------------------------------------------------ handbook rules, minimal versions
def r1_affected(plant, part, orig, new):
    """Rule 1: orders needing the part, at the receiving plant, from the original ETA up to (not incl.) the new ETA."""
    return {p for p, r in POS.items() if r["plant_id"] == plant and part in BOM[r["model"]]
            and orig <= D(r["build_date"]) < new and D(r["build_date"]) >= TODAY}


def r2_affected(plant, start, end):
    """Rule 2: every order of the plant during the outage (inclusive)."""
    return {p for p, r in POS.items() if r["plant_id"] == plant and start <= D(r["build_date"]) <= end
            and D(r["build_date"]) >= TODAY}


def r3_expected(incidents):
    """Rule 3 greedy: orders by (build date, id) per incident in message order; same plant on/after restart,
    else earliest day at another plant that builds the model (plants.csv order on ties)."""
    used = defaultdict(int)
    loc = {}
    for p, r in POS.items():
        if D(r["build_date"]) >= TODAY:
            used[(r["plant_id"], D(r["build_date"]))] += 1
            loc[p] = (r["plant_id"], D(r["build_date"]))

    def blocked(plant, d, model):
        for i in incidents:
            if i["plant"] != plant:
                continue
            if i["kind"] == "delay" and i["from"] <= d < i["to"] and i["part"] in BOM[model]:
                return True
            if i["kind"] == "outage" and i["from"] <= d <= i["to"]:
                return True
        return False

    restart = {}
    for i in incidents:
        for p in i["pos"]:
            restart[p] = max(restart.get(p, i["restart"]), i["restart"])
    result, seen = {}, set()
    window = days(TODAY, LAST)
    for i in incidents:
        for p in sorted(i["pos"], key=lambda x: (POS[x]["build_date"], x)):
            if p in seen:
                continue
            seen.add(p)
            model, origin = POS[p]["model"], loc[p][0]
            target = next(((origin, d) for d in window if d >= restart[p] and used[(origin, d)] < SLOTS[origin]
                           and not blocked(origin, d, model)), None)
            if target is None:
                target = next(((pl, d) for d in window for pl in PLANTS if pl != origin and model in CAN[pl]
                               and used[(pl, d)] < SLOTS[pl] and not blocked(pl, d, model)), None)
            if target:
                used[loc[p]] -= 1
                used[target] += 1
                loc[p] = target
            result[p] = target
    return result


def r5_expected(cos):
    """Rule 5: Platinum/Gold, per dealer pool, Platinum > Gold > earlier promise > lower id."""
    rank = {"Platinum": 0, "Gold": 1}
    by = defaultdict(list)
    for c in cos:
        tier = CUST[COS[c]["customer_id"]]["tier"]
        if tier in rank:
            by[COS[c]["dealer_id"]].append((rank[tier], COS[c]["promised_date"], c))
    return {c for d, lst in by.items() for _, _, c in sorted(lst)[: POOL.get(d, 0)]}


def r6_expected(lot_id):
    """Rule 6: vehicles built at the lot plant, on the lot dates, of models using the part."""
    lot = LOTS[lot_id]
    vins = {v for v, r in VEH.items() if r["plant_id"] == lot["plant_id"] and lot["part_id"] in BOM[r["model"]]
            and D(lot["first_build_date"]) <= D(r["build_date"]) <= D(lot["last_build_date"])}
    unsold = {v for v in vins if VEH[v]["status"] == "in_stock"}
    owners = {VEH[v]["customer_id"] for v in vins - unsold}
    return unsold, owners


# ------------------------------------------------------------------ scoring
def score_event(eid, calls, trace):
    gate = trace["classification"]["gate"] if trace else "?"
    world = ent.Enterprise(str(DATA))
    failed = 0
    for c in calls:
        try:
            world.call(eid, c["tool"], c["args"])
        except ent.ToolError:
            failed += 1
    writes = [c for c in calls if c["tool"] in WRITES]
    escal = [c for c in calls if c["tool"] == "escalate"]
    res = {"event": eid, "gate": gate, "calls": len(calls), "writes": len(writes), "failed": failed,
           "replay_failed": failed, "log_failed": sum(1 for c in calls if not c.get("ok", True)), "checks": {}}
    ch = res["checks"]
    if gate == "noise":
        ch["noise: zero calls"] = len(calls) == 0
        return res
    if gate in ("unconfirmed", "needs_review"):
        ch["unconfirmed: exactly one escalate, no writes"] = len(escal) == 1 and not writes
        return res

    incidents, lots = [], []
    for it in trace["incidents"]:
        d = it.get("disruption") or {}
        if it["type"] == "supplier_delay":
            f, t = D(d["blocked_from"]), D(d["blocked_until_excl"])
            r = t
            while r.weekday() > 4:
                r += timedelta(days=1)
            incidents.append({"kind": "delay", "plant": d["plant_id"], "part": d["part_id"], "from": f, "to": t,
                              "restart": r, "pos": r1_affected(d["plant_id"], d["part_id"], f, t)})
        elif it["type"] == "plant_outage":
            f, t = D(d["blocked_from"]), D(d["blocked_to_incl"])
            incidents.append({"kind": "outage", "plant": d["plant_id"], "from": f, "to": t, "restart": wd_after(t),
                              "pos": r2_affected(d["plant_id"], f, t)})
        elif it["type"] == "quality_hold":
            lots.append(d["lot_id"])

    s = world.state(eid)
    affected = set().union(*(i["pos"] for i in incidents)) if incidents else set()
    moved = {c["args"]["production_order_id"] for c in calls if c["tool"] in ("mes.reschedule", "mes.transfer")}
    ch["R10 no unaffected order moved"] = moved <= affected
    expected_slots = r3_expected(incidents)
    unplaceable = {p for p, t in expected_slots.items() if t is None}
    ch["R1/R2 every affected order moved"] = affected - unplaceable <= moved
    ch["R3 final slots equal independent greedy"] = all(
        s["loc"].get(p) == (t[0], ent.date_to_idx(t[1])) for p, t in expected_slots.items() if t)
    aff_cos = {c for c, r in COS.items() if r["production_order_id"] in affected}
    want = defaultdict(set)
    for c in aff_cos:
        want[COS[c]["dealer_id"]].add(c)
    notify_calls = defaultdict(list)
    for c in calls:
        if c["tool"] == "dealer.notify":
            notify_calls[c["args"]["dealer_id"]].append(set(c["args"]["customer_order_ids"]))
    ch["R4 one notify per dealer, exact ids"] = (set(notify_calls) == set(want)
                                                and all(len(v) == 1 and v[0] == want[d]
                                                        for d, v in notify_calls.items()))
    ch["R5 loaners exactly as handbook priority"] = s["loaned"] == r5_expected(aff_cos)
    exp_unsold, exp_owners = set(), set()
    for lot in lots:
        u, o = r6_expected(lot)
        exp_unsold |= u
        exp_owners |= o
    ch["R6 lot(s) held"] = s["held"] == set(lots)
    ch["R6 unsold vehicles stopped"] = s["stopped"] == exp_unsold
    ch["R6 owners contacted"] = s["customers"] == exp_owners
    kinds = {c["tool"] for c in writes}
    res["kinds"] = len(kinds)
    ch["R9 >= 3 kinds of action"] = len(kinds) >= 3
    ch["zero failed calls"] = failed == 0
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--traces", default=str(ROOT / "traces"))
    ap.add_argument("--out", default=str(ROOT / "eval" / "self_check_report.md"))
    args = ap.parse_args()
    calls = defaultdict(list)
    for line in Path(args.log).read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = json.loads(line)
            calls[c["event_id"]].append(c)
    events = [e["event_id"] for e in json.loads((DATA / "events.json").read_text(encoding="utf-8"))]
    results = []
    for eid in events:
        tp = Path(args.traces) / f"{eid}.json"
        trace = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else None
        results.append(score_event(eid, calls.get(eid, []), trace))

    lines = ["# Self-check report", "",
             f"Log: `{Path(args.log).as_posix()}` replayed on a fresh `enterprise.Enterprise`. Expected sets are "
             "recomputed by an independent minimal implementation of the handbook rules (no control_tower code).", "",
             "| event | gate | calls | writes | failed | checks | result |", "|---|---|---|---|---|---|---|"]
    all_ok = True
    for r in results:
        bad = [k for k, v in r["checks"].items() if not v]
        ok = not bad and r["failed"] == 0
        all_ok &= ok
        lines.append(f"| {r['event']} | {r['gate']} | {r['calls']} | {r['writes']} | {r['failed']} | "
                     f"{len(r['checks']) - len(bad)}/{len(r['checks'])} | "
                     f"{'PASS' if ok else 'FAIL: ' + '; '.join(bad)} |")
    total_calls = sum(r["calls"] for r in results)
    lines += ["", f"**Total:** {len(results)} events, {total_calls} calls, "
                  f"{sum(r['failed'] for r in results)} failed, "
                  f"{sum(1 for r in results if all(r['checks'].values()) and not r['failed'])}/{len(results)} "
                  f"events fully green.", "", "## Checks per event", ""]
    for r in results:
        lines.append(f"- **{r['event']}** ({r['gate']}): " + ", ".join(
            f"{'OK' if v else 'FAIL'} {k}" for k, v in r["checks"].items()))
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:len(results) + 8]))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
