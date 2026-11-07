"""Coordinator: LLM call, gate, compound split, routing to specialists, shared ledgers, verification, execution."""
from __future__ import annotations

import time
from datetime import date

from .. import config, llm, verifier
from ..data_loader import DataStore, get_store
from ..ontology import KnowledgeGraph, get_graph, nid
from ..policy import EXECUTION_ORDER, R3, R7, R8
from ..resolvers import resolve_incident
from ..tools_client import ToolsClient
from ..twin import Twin
from .customer_quality import CustomerCareQuality
from .dealer_network import DealerNetwork
from .supply_chain import SlotLedger, SupplyChainPlanner

AGENT = "Coordinator"
TYPE_LABEL = {"supplier_delay": "Supplier delay", "plant_outage": "Plant outage", "quality_hold": "Quality hold"}


class Coordinator:
    def __init__(self, client: ToolsClient, ds: DataStore | None = None, kg: KnowledgeGraph | None = None):
        self.client = client
        self.ds = ds or get_store()
        self.kg = kg or get_graph()
        self.sc = SupplyChainPlanner(self.ds, self.kg)
        self.dn = DealerNetwork(self.ds)
        self.cq = CustomerCareQuality(self.ds, self.kg)

    # ================================================================== entry point
    def handle(self, event: dict) -> dict:
        t0 = time.time()
        eid, text = event["event_id"], event["text"]
        res = llm.extract(text)
        ex = res["extraction"]
        resolved = [resolve_incident(i.model_dump(), text, self.ds) for i in ex.incidents]
        g = llm.gate(ex, resolved, text)
        self.client.mark(eid, g["result"])
        trace = {
            "event": {k: event.get(k) for k in ("event_id", "source", "received_at", "text")},
            "classification": {"category": ex.category, "gate": g["result"], "confidence": ex.confidence,
                               "rationale": ex.rationale, "gate_reason": g["reason"], "hedges": g["hedges"],
                               "llm_model": res["llm_model"], "llm_fallback": res["llm_fallback"],
                               "llm_cached": res["cached"], "llm_error": res["error"]},
            "incidents": [], "plan": [], "verifier": {"plan_checks": [], "world_checks": []}, "actions": [],
            "escalation": {"escalated": False, "reason": "", "missing_fields": []}, "schedule": None,
            "config_snapshot": config.snapshot(),
        }
        if g["result"] == "noise":
            trace["incidents"] = [self._incident_stub(eid, k, r) for k, r in enumerate(resolved)]
            trace["decision_rule"] = R7
            trace["summary"] = (f"Judged not operational: {g['reason']} No tool calls were made (handbook rule 7).")
        elif g["result"] in ("unconfirmed", "needs_review"):
            trace["incidents"] = [self._incident_stub(eid, k, r) for k, r in enumerate(resolved)]
            self._escalate_only(eid, trace, g["reason"], g["missing_fields"])
        else:
            self._handle_incidents(eid, text, resolved, trace)
        self._finish(eid, trace, res, t0)
        return trace

    # ================================================================== escalation-only path
    def _escalate_only(self, eid: str, trace: dict, reason: str, missing: list[str]) -> None:
        trace["decision_rule"] = R8
        action = {"seq": 1, "agent": AGENT, "tool": "escalate", "args": {"reason": reason[:900]}, "rule_id": R8,
                  "reason": "not actionable without a human", "evidence_path": [], "incident_id": None}
        trace["plan"] = [action]
        ok, _ = self.client.act(eid, "escalate", action["args"], seq=1, agent=AGENT, rule_id=R8)
        trace["escalation"] = {"escalated": ok, "reason": reason, "missing_fields": missing}
        trace["summary"] = (f"Escalated to a human, no operational change (handbook rule 8). {reason}")

    def _incident_stub(self, eid: str, k: int, r: dict) -> dict:
        return {"incident_id": f"{eid}-I{k + 1}", "type": r.get("type"), "evidence_quote": r.get("evidence_quote"),
                "extracted": r["extracted"], "validation": r["validation"], "disruption": None,
                "graph_path": {"nodes": [], "edges": [], "text": ""}, "affected": {}, "excluded": [],
                "decisions": {"reschedule": [], "loaners": []}}

    # ================================================================== incident path
    def _handle_incidents(self, eid: str, text: str, resolved: list[dict], trace: dict) -> None:
        if config.COMPOUND_ORDER == "earliest_disruption_first":
            key = lambda r: r.get("original_eta") or r.get("start") or r.get("window_from") or date.max
            resolved = sorted(resolved, key=key)
        sched, quality, failures, items = [], [], [], []
        for k, r in enumerate(resolved):
            iid = f"{eid}-I{k + 1}"
            item = self._incident_stub(eid, k, r)
            items.append(item)
            if r["type"] == "supplier_delay":
                d = self.sc.resolve_delay(r)
                item["validation"] += d["validation"]
                if not d["ok"]:
                    failures.append(f"{iid}: {d['reason']}")
                    continue
                inc = self.sc.delay_incident(iid, d)
                sched.append(inc)
                item["_inc"] = inc
            elif r["type"] == "plant_outage":
                inc = self.sc.outage_incident(iid, r)
                sched.append(inc)
                item["_inc"] = inc
            elif r["type"] == "quality_hold":
                lot = self.cq.resolve_lot(r)
                item["validation"] += lot["validation"]
                if not lot["ok"]:
                    failures.append(f"{iid}: {lot['reason']}")
                    continue
                qp = self.cq.plan_quality(iid, lot["lot_id"])
                qp["lot_path"], qp["lot_method"] = lot["path"], lot["method"]
                quality.append((iid, qp))
                item["_q"] = qp
        trace["incidents"] = items
        if failures:
            for it in items:
                it.pop("_inc", None)
                it.pop("_q", None)
            self._escalate_only(eid, trace, "Validation failed, no operational action: " + " | ".join(failures),
                                ["validated shipment/lot"])
            return

        # ---------------- Supply chain: shared slot ledger across every incident of this event
        ledger = SlotLedger.from_store(self.ds)
        touched_plants = sorted({i["disruption"]["plant_id"] for i in sched})
        before = ledger.utilization(self.ds.plant_order())
        moves, decisions = self.sc.plan_moves(sched, ledger)
        no_slot = [d for d in decisions if d["kind"] == "no_slot"]
        outcome = {}
        for d in decisions:
            if d["kind"] == "same_plant":
                outcome[d["po"]] = f"rescheduled to {d['to'].split()[1]} at {d['to'].split()[0]}"
            elif d["kind"] == "transfer":
                outcome[d["po"]] = f"transferred to {d['to'].split()[0]} on {d['to'].split()[1]}"
            else:
                outcome[d["po"]] = "no free slot in the planning window, escalated to planning"

        affected_cos: dict[str, str] = {}
        reasons_of_co: dict[str, str] = {}
        for inc in sched:
            label = ("a supplier delay" if inc["type"] == "supplier_delay" else "a plant outage") + \
                    f" at {inc['disruption']['plant_id']}"
            for po in inc["affected_pos"]:
                for co in self.ds.customer_orders_by_po.get(po, []):
                    affected_cos.setdefault(co.customer_order_id, inc["incident_id"])
                    reasons_of_co.setdefault(co.customer_order_id, label)

        notifies = self.dn.plan_notifications(affected_cos, outcome, reasons_of_co) if affected_cos else []
        if config.NOTIFY_SCOPE == "per_incident":
            notifies = []
            for inc in sched:
                sub = {c: i for c, i in affected_cos.items() if i == inc["incident_id"]}
                notifies += self.dn.plan_notifications(sub, outcome, reasons_of_co)

        pools: dict[str, int] = {}
        for dealer in self.cq.eligible_dealers(affected_cos):
            ok, res = self.client.act(eid, "crm.loaner_availability", {"dealer_id": dealer}, agent="CustomerCareQuality",
                                       rule_id="R5 pool check")
            pools[dealer] = int(res.get("available", 0)) if ok else 0
        loaners, loaner_decisions = self.cq.plan_loaners(affected_cos, pools)

        holds, stops, owners = [], [], []
        for iid, qp in quality:
            holds.append(qp["hold"])
            stops += self.dn.plan_stop_sales(qp["unsold"], iid, qp["lot"].lot_id)
            owners += qp["notify_customers"]

        escalations = []
        if no_slot and config.NO_SLOT_ACTION == "escalate":
            escalations.append({"agent": AGENT, "tool": "escalate", "rule_id": R3, "incident_id": None,
                                "args": {"reason": "No feasible slot before 2027-04-02 for: "
                                         + ", ".join(d["po"] for d in no_slot) + ". Dealers were notified; a planner "
                                         "must decide (overtime, later window)."},
                                "reason": "human decision needed for orders without a feasible slot"})
        plan = moves + notifies + loaners + holds + stops + owners + escalations
        plan.sort(key=lambda a: EXECUTION_ORDER.index(a["tool"]))
        for n, a in enumerate(plan, 1):
            a["seq"] = n
            a["evidence_path"] = self._evidence(a, sched, quality)
        trace["plan"] = plan

        # ---------------- incident detail for the trace
        for item in items:
            inc, qp = item.pop("_inc", None), item.pop("_q", None)
            if inc:
                self._fill_sched_item(item, inc, decisions, loaner_decisions, affected_cos)
            if qp:
                self._fill_quality_item(item, qp)
        if len(items) > 1:
            trace["shared_resources"] = {
                "processing_order": [i["incident_id"] for i in items],
                "slot_ledger_note": "One slot ledger for the whole event: every incident's blocked days are applied "
                                    "before any order is placed, and each placement consumes a slot the next "
                                    "placement can no longer use.",
                "loaner_ledger_note": "Eligible customers from all incidents are ranked together per dealer against "
                                      "one live pool; each dealer gets one merged dealer.notify.",
            }

        # ---------------- guardrails: verifier -> twin -> verifier
        verif_incidents = [{**i["disruption"], "type": i["type"]} for i in sched] + [{"type": "quality_hold", "lot_id": qp["lot"].lot_id}
                                                              for _, qp in quality]
        plan_checks = verifier.check_plan(self.ds, plan, verif_incidents, pools, {d["po"] for d in no_slot})
        twin = Twin(eid)
        dry = twin.apply([a for a in plan])
        world_checks = verifier.check_world(twin, plan, dry)
        trace["verifier"] = {"plan_checks": plan_checks, "world_checks": world_checks}
        after = twin.snapshot_slots(self.ds.plant_order())
        trace["schedule"] = {"plants": self.ds.plant_order(), "touched_plants": touched_plants,
                             "transfer_targets": sorted({a["args"]["to_plant_id"] for a in plan
                                                         if a["tool"] == "mes.transfer"}),
                             "capacity": {p: self.ds.plants[p].slots_per_day for p in self.ds.plants},
                             "before": before, "after": after}
        if not (verifier.passed(plan_checks) and verifier.passed(world_checks)):
            bad = [c["name"] + (f" ({c['detail']})" if c["detail"] else "") for c in plan_checks + world_checks
                   if not c["ok"] and c.get("blocking", True)]
            trace["plan_rejected"] = plan
            trace["plan"] = []
            self._escalate_only(eid, trace, "Verifier blocked the plan: " + "; ".join(bad), ["verifier"])
            return

        # ---------------- execute on the real server
        failed = None
        for a in plan:
            ok, res = self.client.act(eid, a["tool"], a["args"], seq=a["seq"], agent=a["agent"], rule_id=a["rule_id"])
            if not ok:
                failed = (a, res)
                break
        if failed:
            a, res = failed
            self.client.act(eid, "escalate", {"reason": f"Execution stopped: {a['tool']} failed ({res.get('error')}). "
                                                        "Remaining actions not sent."}, agent=AGENT, rule_id=R8)
            trace["escalation"] = {"escalated": True, "reason": f"{a['tool']} failed: {res.get('error')}",
                                   "missing_fields": []}
        if no_slot and not failed:
            trace["escalation"] = {"escalated": True, "reason": escalations[0]["args"]["reason"] if escalations
                                   else "no slot", "missing_fields": []}
        self._read_back(eid, plan, pools, trace)
        trace["summary"] = self._summary(items, plan, no_slot)

    # ================================================================== trace detail helpers
    def _fill_sched_item(self, item, inc, decisions, loaner_decisions, affected_cos) -> None:
        pos = inc["affected_pos"]
        cos, co_edges = self.kg.customer_orders_of(pos)
        cos = [c for c in cos if affected_cos.get(c) == inc["incident_id"]]
        dealers = sorted({self.ds.customer_orders[c].dealer_id for c in cos})
        customers = sorted({self.ds.customer_orders[c].customer_id for c in cos})
        edges = inc["path_edges"] + co_edges
        edges += [[nid("Dealer", d), "HAS_POOL", nid("LoanerPool", d)] for d in dealers]
        item["disruption"] = inc["disruption"]
        item["graph_path"] = self._graph_path(
            edges, inc["anchor"], self._sched_chain(inc, cos),
            f"{len(pos)} production orders, {len(cos)} customer orders, {len(dealers)} dealers")
        item["affected"] = {"production_orders": pos, "customer_orders": cos, "dealers": dealers,
                            "customers": customers, "lots": [], "vehicles_unsold": [], "vehicles_sold": []}
        item["excluded"] = inc["excluded"]
        pos_set = set(pos)
        item["decisions"] = {"reschedule": [d for d in decisions if d["po"] in pos_set],
                             "loaners": [d for d in loaner_decisions if d["co"] in set(cos)]}

    def _fill_quality_item(self, item, qp) -> None:
        lot = qp["lot"]
        item["disruption"] = {"lot_id": lot.lot_id, "part_id": lot.part_id, "supplier_id": lot.supplier_id,
                              "plant_id": lot.plant_id, "window_from": lot.first_build_date.isoformat(),
                              "window_to": lot.last_build_date.isoformat(), "lot_match": qp["lot_method"]}
        item["graph_path"] = self._graph_path(
            qp["lot_path"] + qp["path_edges"], nid("PartLot", lot.lot_id), self._quality_chain(qp),
            f"{len(qp['vehicles'])} vehicles: {len(qp['unsold'])} unsold, {len(qp['sold'])} sold to "
            f"{len(qp['owners'])} owners")
        pos = sorted({self.ds.vehicles[v].production_order_id for v in qp["vehicles"]})
        item["affected"] = {"production_orders": pos, "customer_orders": [],
                            "dealers": sorted({self.ds.vehicles[v].dealer_id for v in qp["unsold"]}),
                            "customers": qp["owners"], "lots": [lot.lot_id], "vehicles_unsold": qp["unsold"],
                            "vehicles_sold": qp["sold"]}
        other_models = sorted({p.model for p in self.ds.production_orders.values() if p.plant_id == lot.plant_id
                               and lot.first_build_date <= p.build_date <= lot.last_build_date
                               and lot.part_id not in self.ds.bom[p.model]})
        item["excluded"] = [{"id": m, "reason": f"{m} does not use {lot.part_id}"} for m in other_models]

    def _graph_path(self, edges: list, anchor: str, chain: list | None = None, counts: str = "") -> dict:
        nodes = sorted({e[0] for e in edges} | {e[2] for e in edges} | {anchor})
        text = (self.kg.explain_path(chain, limit=12, ordered=True) if chain
                else self.kg.explain_path(edges, limit=12).split("  (+")[0])
        return {"nodes": nodes, "edges": edges, "text": text + (f"  [{counts}]" if counts else ""),
                "chain": chain or [], "anchor": anchor}

    def _sched_chain(self, inc: dict, cos: list[str]) -> list:
        """One representative, connected path: Shipment/Plant -> ... -> ProductionOrder -> CustomerOrder -> Dealer."""
        if not inc["affected_pos"]:
            return []
        po_id = inc["affected_pos"][0]
        po, plant = nid("ProductionOrder", po_id), nid("Plant", inc["disruption"]["plant_id"])
        model = nid("Model", self.ds.production_orders[po_id].model)
        if inc["type"] == "supplier_delay":
            sh, part = nid("Shipment", inc["disruption"]["shipment_id"]), nid("Part", inc["disruption"]["part_id"])
            chain = [[sh, "RECEIVED_AT", plant], [sh, "DELIVERS", part], [part, "USED_IN", model],
                     [po, "BUILDS", model]]
        else:
            chain = [[po, "SCHEDULED_AT", plant]]
        co_id = next((c for c in cos if self.ds.customer_orders[c].production_order_id == po_id), None)
        if co_id:
            co = self.ds.customer_orders[co_id]
            c = nid("CustomerOrder", co_id)
            chain += [[po, "FULFILLS", c], [c, "SOLD_THROUGH", nid("Dealer", co.dealer_id)],
                      [c, "ORDERED_BY", nid("Customer", co.customer_id)]]
        return chain

    def _quality_chain(self, qp: dict) -> list:
        """Lot -> ProductionOrder -> Vehicle -> Dealer / Customer, via the derived USED_IN_ORDER edge."""
        lot = qp["lot"]
        n = nid("PartLot", lot.lot_id)
        vin = (qp["sold"] or qp["unsold"] or [None])[0]
        if not vin:
            return [[n, "LOT_OF", nid("Part", lot.part_id)], [n, "INSTALLED_AT", nid("Plant", lot.plant_id)]]
        v = self.ds.vehicles[vin]
        po, veh = nid("ProductionOrder", v.production_order_id), nid("Vehicle", vin)
        chain = [[n, "USED_IN_ORDER", po], [veh, "BUILT_FROM", po], [veh, "AT_DEALER", nid("Dealer", v.dealer_id)]]
        if v.customer_id:
            chain.append([veh, "OWNED_BY", nid("Customer", v.customer_id)])
        return chain

    def _evidence(self, a: dict, sched: list[dict], quality: list) -> list:
        tool, args = a["tool"], a["args"]
        inc = next((i for i in sched if i["incident_id"] == (a.get("incident_id") or "").split(",")[0]), None)
        if tool in ("mes.reschedule", "mes.transfer") and inc:
            po = nid("ProductionOrder", args["production_order_id"])
            model = nid("Model", self.ds.production_orders[args["production_order_id"]].model)
            plant = nid("Plant", inc["disruption"]["plant_id"])
            path = []
            if inc["type"] == "supplier_delay":
                sh, part = nid("Shipment", inc["disruption"]["shipment_id"]), nid("Part", inc["disruption"]["part_id"])
                path = [[sh, "DELIVERS", part], [sh, "RECEIVED_AT", plant], [part, "USED_IN", model],
                        [po, "BUILDS", model]]
            path.append([po, "SCHEDULED_AT", plant])
            if tool == "mes.transfer":
                path.append([nid("Plant", args["to_plant_id"]), "CAN_BUILD", model])
            return path
        if tool == "dealer.notify":
            out = []
            for c in args["customer_order_ids"]:
                co = self.ds.customer_orders[c]
                out += [[nid("ProductionOrder", co.production_order_id), "FULFILLS", nid("CustomerOrder", c)],
                        [nid("CustomerOrder", c), "SOLD_THROUGH", nid("Dealer", co.dealer_id)]]
            return out
        if tool == "crm.assign_loaner":
            co = self.ds.customer_orders[args["customer_order_id"]]
            c = nid("CustomerOrder", co.customer_order_id)
            return [[nid("ProductionOrder", co.production_order_id), "FULFILLS", c],
                    [c, "ORDERED_BY", nid("Customer", co.customer_id)], [c, "SOLD_THROUGH", nid("Dealer", co.dealer_id)],
                    [nid("Dealer", co.dealer_id), "HAS_POOL", nid("LoanerPool", co.dealer_id)]]
        if tool == "quality.hold_lot":
            lot = self.ds.part_lots[args["lot_id"]]
            n = nid("PartLot", lot.lot_id)
            return [[n, "LOT_OF", nid("Part", lot.part_id)], [n, "LOT_FROM", nid("Supplier", lot.supplier_id)],
                    [n, "INSTALLED_AT", nid("Plant", lot.plant_id)]]
        lot_node = next((nid("PartLot", qp["lot"].lot_id) for iid, qp in quality if iid == a.get("incident_id")), None)
        if tool == "dealer.stop_sale":
            out = []
            for v in args["vins"]:
                veh = self.ds.vehicles[v]
                po = nid("ProductionOrder", veh.production_order_id)
                out += ([[lot_node, "USED_IN_ORDER", po]] if lot_node else []) + [
                    [nid("Vehicle", v), "BUILT_FROM", po], [nid("Vehicle", v), "AT_DEALER", nid("Dealer", veh.dealer_id)]]
            return out
        if tool == "crm.notify_customer":
            vins = [v.vin for v in self.ds.vehicles.values() if v.customer_id == args["customer_id"]
                    and any(v.vin in qp["sold"] for _, qp in quality)]
            out = []
            for v in vins:
                po = nid("ProductionOrder", self.ds.vehicles[v].production_order_id)
                out += ([[lot_node, "USED_IN_ORDER", po]] if lot_node else []) + [
                    [nid("Vehicle", v), "BUILT_FROM", po], [nid("Vehicle", v), "OWNED_BY", nid("Customer", args["customer_id"])]]
            return out
        return []

    # ================================================================== read-back + summary
    def _read_back(self, eid: str, plan: list[dict], pools: dict[str, int], trace: dict) -> None:
        checks = []
        targets: dict[tuple[str, str], list[str]] = {}
        for a in plan:
            if a["tool"] in ("mes.reschedule", "mes.transfer"):
                po = a["args"]["production_order_id"]
                plant = a["args"].get("to_plant_id") or self.ds.production_orders[po].plant_id
                targets.setdefault((plant, a["args"]["new_date"]), []).append(po)
        for (plant, day), pos in sorted(targets.items()):
            ok, res = self.client.act(eid, "mes.get_schedule", {"plant_id": plant, "date": day}, agent="Verifier",
                                      rule_id="R3 read-back")
            there = {o["production_order_id"] for o in res.get("orders", [])} if ok else set()
            checks.append({"name": f"read-back {plant} {day}: {', '.join(pos)} present, free slots >= 0",
                           "ok": ok and set(pos) <= there and res.get("free_slots", -1) >= 0, "detail": "", "blocking": False})
        loaned: dict[str, int] = {}
        for a in plan:
            if a["tool"] == "crm.assign_loaner":
                d = self.ds.customer_orders[a["args"]["customer_order_id"]].dealer_id
                loaned[d] = loaned.get(d, 0) + 1
        for d, n in sorted(loaned.items()):
            ok, res = self.client.act(eid, "crm.loaner_availability", {"dealer_id": d}, agent="Verifier",
                                      rule_id="R5 read-back")
            checks.append({"name": f"read-back loaners {d}: {pools.get(d, 0)} - {n} = {pools.get(d, 0) - n}",
                           "ok": ok and res.get("available") == pools.get(d, 0) - n, "detail": "", "blocking": False})
        trace["verifier"]["readback_checks"] = checks

    def _summary(self, items: list[dict], plan: list[dict], no_slot: list[dict]) -> str:
        parts = []
        for it in items:
            d, aff = it["disruption"] or {}, it["affected"]
            if it["type"] == "quality_hold":
                parts.append(f"{TYPE_LABEL[it['type']]} on {d.get('lot_id')} ({d.get('part_id')} at {d.get('plant_id')}, "
                             f"built {d.get('window_from')} to {d.get('window_to')}): {len(aff['vehicles_unsold'])} unsold "
                             f"vehicles stopped at {len(aff['dealers'])} dealers and {len(aff['customers'])} owners "
                             f"contacted.")
            else:
                rs = it["decisions"]["reschedule"]
                same = sum(1 for x in rs if x["kind"] == "same_plant")
                tr = sum(1 for x in rs if x["kind"] == "transfer")
                loans = sum(1 for x in it["decisions"]["loaners"] if x["decision"] == "assigned")
                where = d.get("plant_id")
                what = (f"{d.get('part_id')} delay to {where} ({d.get('blocked_from')} -> {d.get('blocked_until_excl')})"
                        if it["type"] == "supplier_delay" else
                        f"outage at {where} ({d.get('blocked_from')} to {d.get('blocked_to_incl')})")
                parts.append(f"{TYPE_LABEL[it['type']]}: {what} affects {len(aff['production_orders'])} production "
                             f"orders; {same} rescheduled at the same plant, {tr} transferred; "
                             f"{len(aff['dealers'])} dealers notified about {len(aff['customer_orders'])} customer "
                             f"orders; {loans} loaners assigned.")
        kinds = sorted({a["tool"] for a in plan if a["tool"] != "escalate"})
        tail = f" {len(plan)} actions of {len(kinds)} kinds, all verified in the digital twin before execution."
        if no_slot:
            tail += f" {len(no_slot)} orders had no feasible slot and were escalated."
        return " ".join(parts) + tail

    def _finish(self, eid: str, trace: dict, res: dict, t0: float) -> None:
        calls = self.client.calls_for(eid)
        trace["actions"] = [{k: c[k] for k in ("call_no", "seq", "rule_id", "agent", "tool", "args", "ok", "error",
                                               "kind", "ts")}
                            for c in calls]
        trace["metrics"] = {"llm_calls": res["llm_calls"], "llm_model": res["llm_model"],
                            "llm_cached": res["cached"], "prompt_tokens": res["prompt_tokens"],
                            "completion_tokens": res["completion_tokens"], "tool_calls": len(calls),
                            "reads": sum(1 for c in calls if c["kind"] == "read"),
                            "writes": sum(1 for c in calls if c["kind"] == "write"),
                            "escalations": sum(1 for c in calls if c["kind"] == "escalate"),
                            "failed": sum(1 for c in calls if not c["ok"]), "runtime_s": round(time.time() - t0, 2)}
        mentions = sorted({x["resolved"] for it in trace["incidents"] for x in it.get("extracted", [])
                           if x.get("resolved") and x["field"].endswith(("mention", "_id"))})
        trace["event"]["mentions"] = mentions
        for it in trace["incidents"]:
            it["graph_path"].setdefault("text", "")
