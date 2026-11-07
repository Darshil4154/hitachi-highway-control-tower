"""Dealer Network: R4 (one dealer.notify per dealer, exact ids) and R6 stop-sale grouping."""
from __future__ import annotations

from collections import defaultdict

from ..data_loader import DataStore
from ..policy import R4, R6

AGENT = "DealerNetwork"


class DealerNetwork:
    def __init__(self, ds: DataStore):
        self.ds = ds

    def plan_notifications(self, affected_cos: dict[str, str], outcome_of_po: dict[str, str],
                           reasons_of_co: dict[str, str]) -> list[dict]:
        """affected_cos: {co_id: incident_id}. One notify per dealer (merged across incidents), sorted ids."""
        by_dealer: dict[str, list[str]] = defaultdict(list)
        for co_id in affected_cos:
            by_dealer[self.ds.customer_orders[co_id].dealer_id].append(co_id)
        actions = []
        for dealer in sorted(by_dealer):
            ids = sorted(by_dealer[dealer])
            reasons = sorted({reasons_of_co[c] for c in ids})
            lines = []
            for c in ids:
                po = self.ds.customer_orders[c].production_order_id
                lines.append(f"{c} ({po}): {outcome_of_po.get(po, 'delayed')}")
            msg = (f"Wacky Wheels operations: {len(ids)} of your customer orders are affected by "
                   f"{' and '.join(reasons)}. " + "; ".join(lines) + ".")
            incidents = sorted({affected_cos[c] for c in ids})
            actions.append({"agent": AGENT, "tool": "dealer.notify",
                            "args": {"dealer_id": dealer, "customer_order_ids": ids, "message": msg},
                            "rule_id": R4, "incident_id": ",".join(incidents),
                            "reason": f"{dealer} has {len(ids)} affected customer order(s); exactly one notify "
                                      f"listing only those ids"})
        return actions

    def plan_stop_sales(self, vins_unsold: list[str], incident_id: str, lot_id: str) -> list[dict]:
        by_dealer: dict[str, list[str]] = defaultdict(list)
        for vin in vins_unsold:
            by_dealer[self.ds.vehicles[vin].dealer_id].append(vin)
        return [{"agent": AGENT, "tool": "dealer.stop_sale",
                 "args": {"dealer_id": d, "vins": sorted(by_dealer[d])}, "rule_id": R6, "incident_id": incident_id,
                 "reason": f"{len(by_dealer[d])} unsold vehicle(s) at {d} contain suspect lot {lot_id}"}
                for d in sorted(by_dealer)]
