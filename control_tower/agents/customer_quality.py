"""Customer Care & Quality: R5 loaner ranking against live pools; R6 lot identification, hold and owner contact."""
from __future__ import annotations

from collections import defaultdict

from ..data_loader import DataStore
from ..policy_model import loaner_rank, loaner_tiers
from ..ontology import KnowledgeGraph, nid
from ..policy import R5, R6

AGENT = "CustomerCareQuality"


class CustomerCareQuality:
    def __init__(self, ds: DataStore, kg: KnowledgeGraph):
        self.ds, self.kg = ds, kg

    # ------------------------------------------------------------------ R5
    def eligible_dealers(self, affected_cos: dict[str, str]) -> list[str]:
        return sorted({self.ds.customer_orders[c].dealer_id for c in affected_cos
                       if self.ds.customers[self.ds.customer_orders[c].customer_id].tier in loaner_tiers()})

    def plan_loaners(self, affected_cos: dict[str, str], pools: dict[str, int]) -> tuple[list[dict], list[dict]]:
        """Rank all eligible affected orders per dealer (across incidents); assign the top `pool`."""
        by_dealer: dict[str, list[str]] = defaultdict(list)
        decisions: list[dict] = []
        for c in sorted(affected_cos):
            co = self.ds.customer_orders[c]
            tier = self.ds.customers[co.customer_id].tier
            if tier in loaner_tiers():
                by_dealer[co.dealer_id].append(c)
            else:
                decisions.append({"co": c, "dealer": co.dealer_id, "customer": co.customer_id, "tier": tier,
                                  "promised": co.promised_date.isoformat(), "rank": None, "decision": "not_eligible",
                                  "reason": f"{tier} tier gets no loaner (dealer is told)", "rule_id": R5})
        actions = []
        for dealer in sorted(by_dealer):
            ranked = sorted(by_dealer[dealer], key=lambda c: (
                loaner_rank(self.ds.customers[self.ds.customer_orders[c].customer_id].tier),
                self.ds.customer_orders[c].promised_date, c))
            pool = pools.get(dealer, 0)
            for rank, c in enumerate(ranked, 1):
                co = self.ds.customer_orders[c]
                tier = self.ds.customers[co.customer_id].tier
                assigned = rank <= pool
                reason = (f"rank {rank} at {dealer} ({tier}, promised {co.promised_date}); pool {pool}"
                          + ("" if assigned else " exhausted"))
                decisions.append({"co": c, "dealer": dealer, "customer": co.customer_id, "tier": tier,
                                  "promised": co.promised_date.isoformat(), "rank": rank,
                                  "decision": "assigned" if assigned else "skipped",
                                  "reason": reason if assigned else f"pool exhausted: {reason}", "rule_id": R5})
                if assigned:
                    actions.append({"agent": AGENT, "tool": "crm.assign_loaner", "args": {"customer_order_id": c},
                                    "rule_id": R5, "incident_id": affected_cos[c], "reason": reason})
        decisions.sort(key=lambda d: (d["dealer"], d["rank"] is None, d["rank"] or 0, d["co"]))
        return actions, decisions

    # ------------------------------------------------------------------ R6
    def resolve_lot(self, r: dict) -> dict:
        v: list[dict] = []
        part, plant, sup = r.get("part_id"), r.get("plant_id"), r.get("supplier_id")
        wf, wt = r.get("window_from"), r.get("window_to")
        out = {"ok": False, "reason": "", "lot_id": None, "validation": v, "path": [], "method": ""}
        lot_id = r.get("lot_id")
        if lot_id:
            lot = self.ds.part_lots.get(lot_id)
            checks = [("lot exists", lot is not None)]
            if lot:
                if part:
                    checks.append((f"lot part {lot.part_id} == {part}", lot.part_id == part))
                if plant:
                    checks.append((f"lot plant {lot.plant_id} == {plant}", lot.plant_id == plant))
                if sup:
                    checks.append((f"lot supplier {lot.supplier_id} == {sup}", lot.supplier_id == sup))
                if wf and wt:
                    checks.append((f"lot window {lot.first_build_date}..{lot.last_build_date} == message {wf}..{wt}",
                                   lot.first_build_date == wf and lot.last_build_date == wt))
            v += [{"check": c, "ok": ok} for c, ok in checks]
            if not all(ok for _, ok in checks):
                out["reason"] = "Lot does not match the message: " + "; ".join(c for c, ok in checks if not ok)
                return out
            assert lot is not None
            _, path = self.kg.find_lots(lot.part_id, lot.plant_id, lot.supplier_id, lot.first_build_date,
                                        lot.last_build_date)
            out.update(ok=True, lot_id=lot_id, path=[e for e in path if e[0] == nid("PartLot", lot_id)],
                       method="explicit lot id, validated")
            return out
        lots, path = self.kg.find_lots(part, plant, sup, wf, wt, mode="equal")
        method = "lot dates equal the message window"
        if not lots:
            lots, path = self.kg.find_lots(part, plant, sup, wf, wt, mode="inside")
            method = "lot fully inside the message window"
        v.append({"check": f"exactly one lot of {part} at {plant}{' from ' + sup if sup else ''} for {wf}..{wt} "
                           f"({method})", "ok": len(lots) == 1})
        if len(lots) != 1:
            out["reason"] = f"Could not identify a single lot ({len(lots)} candidates: {', '.join(lots) or 'none'})."
            return out
        out.update(ok=True, lot_id=lots[0], path=path, method=method)
        return out

    def plan_quality(self, incident_id: str, lot_id: str) -> dict:
        lot = self.ds.part_lots[lot_id]
        vins, path = self.kg.vehicles_for_lot(lot_id)
        unsold = [x for x in vins if self.ds.vehicles[x].status == "in_stock"]
        sold = [x for x in vins if self.ds.vehicles[x].status == "sold"]
        owners = sorted({self.ds.vehicles[x].customer_id for x in sold if self.ds.vehicles[x].customer_id})
        hold = {"agent": AGENT, "tool": "quality.hold_lot", "args": {"lot_id": lot_id}, "rule_id": R6,
                "incident_id": incident_id,
                "reason": f"{lot_id} ({lot.part_id} from {lot.supplier_id}, {lot.plant_id} "
                          f"{lot.first_build_date}..{lot.last_build_date}) is suspect"}
        notify = []
        for c in owners:
            their = sorted(x for x in sold if self.ds.vehicles[x].customer_id == c)
            notify.append({"agent": AGENT, "tool": "crm.notify_customer",
                           "args": {"customer_id": c,
                                    "message": f"Wacky Wheels safety notice: your vehicle {', '.join(their)} contains "
                                               f"a {self.ds.parts[lot.part_id].name} from lot {lot_id} that is on "
                                               f"quality hold. Your dealer will contact you to arrange an inspection."},
                           "rule_id": R6, "incident_id": incident_id,
                           "reason": f"owner of sold affected vehicle(s) {', '.join(their)}"})
        return {"hold": hold, "notify_customers": notify, "vehicles": vins, "unsold": unsold, "sold": sold,
                "owners": owners, "path_edges": path, "lot": lot}
