"""Supply Chain Planner: R1 (delay), R2 (outage), R3 (reschedule / transfer) with a shared slot ledger."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .. import config
from ..data_loader import LAST_IDX, DataStore, date_to_idx, idx_to_date, is_working_day, next_working_day, working_days
from ..ontology import KnowledgeGraph, nid
from ..policy import R1, R2, R3, R10

AGENT = "SupplyChainPlanner"


def first_working_on_or_after(d: date) -> date:
    return d if is_working_day(d) else next_working_day(d)


@dataclass
class Block:
    incident_id: str
    plant_id: str
    days: set[int]
    models: set[str] | None  # None = every model (outage)


@dataclass
class SlotLedger:
    """Occupancy per (plant, day index), shared by every incident of one event."""
    capacity: dict[str, int]
    slots: dict[tuple[str, int], set[str]]
    loc: dict[str, tuple[str, int]]
    model_of: dict[str, str]
    blocks: list[Block] = field(default_factory=list)

    @classmethod
    def from_store(cls, ds: DataStore) -> "SlotLedger":
        slots: dict[tuple[str, int], set[str]] = {}
        loc: dict[str, tuple[str, int]] = {}
        for po in ds.production_orders.values():
            if po.idx >= 0:
                slots.setdefault((po.plant_id, po.idx), set()).add(po.production_order_id)
                loc[po.production_order_id] = (po.plant_id, po.idx)
        return cls(capacity={p.plant_id: p.slots_per_day for p in ds.plants.values()}, slots=slots, loc=loc,
                   model_of={p.production_order_id: p.model for p in ds.production_orders.values()})

    def used(self, plant: str, idx: int) -> int:
        return len(self.slots.get((plant, idx), ()))

    def free(self, plant: str, idx: int) -> bool:
        return self.used(plant, idx) < self.capacity[plant]

    def blocked(self, plant: str, idx: int, model: str) -> bool:
        return any(b.plant_id == plant and idx in b.days and (b.models is None or model in b.models)
                   for b in self.blocks)

    def move(self, po: str, plant: str, idx: int) -> None:
        cur = self.loc[po]
        self.slots[cur].discard(po)
        self.slots.setdefault((plant, idx), set()).add(po)
        self.loc[po] = (plant, idx)

    def utilization(self, plants: list[str]) -> dict[str, dict[str, int]]:
        return {p: {idx_to_date(i).isoformat(): self.used(p, i) for i in range(0, LAST_IDX + 1)} for p in plants}


class SupplyChainPlanner:
    def __init__(self, ds: DataStore, kg: KnowledgeGraph):
        self.ds, self.kg = ds, kg

    # ------------------------------------------------------------------ R1 shipment resolution
    def resolve_delay(self, r: dict) -> dict:
        """Validate a supplier delay and find its shipment. Returns {ok, reason, shipment_id, ..., validation[]}."""
        v: list[dict] = []
        part, plant, sup = r.get("part_id"), r.get("plant_id"), r.get("supplier_id")
        orig, new, sh_id = r.get("original_eta"), r.get("new_eta"), r.get("shipment_id")
        out = {"ok": False, "reason": "", "shipment_id": None, "part_id": part, "plant_id": plant,
               "supplier_id": sup, "original_eta": orig, "new_eta": new, "validation": v, "path": []}
        if sh_id:
            sh = self.ds.shipments.get(sh_id)
            checks = [("shipment exists", sh is not None)]
            if sh:
                checks += [(f"shipment part {sh.part_id} == {part}", sh.part_id == part),
                           (f"shipment plant {sh.plant_id} == {plant}", sh.plant_id == plant)]
                if sup:
                    checks.append((f"shipment supplier {sh.supplier_id} == {sup}", sh.supplier_id == sup))
                if orig:
                    checks.append((f"shipment ETA {sh.eta_date} == original ETA {orig}", sh.eta_date == orig))
            v += [{"check": c, "ok": ok} for c, ok in checks]
            if not all(ok for _, ok in checks):
                out["reason"] = "Shipment id does not match the message: " + "; ".join(c for c, ok in checks if not ok)
                return out
            assert sh is not None
            orig = orig or sh.eta_date
            sup = sup or sh.supplier_id
            matches = [sh_id]
            _, path = self.kg.find_shipment(part, plant, sh.supplier_id, sh.eta_date)
        else:
            if orig:
                matches, path = self.kg.find_shipment(part, plant, sup, orig)
                v.append({"check": f"exactly one shipment of {part} to {plant}"
                                   f"{' from ' + sup if sup else ''} due {orig}", "ok": len(matches) == 1})
            else:
                cands, path = self.kg.find_shipment(part, plant, sup)
                matches = [s for s in cands if self.ds.shipments[s].eta_date < new
                           and self.ds.shipments[s].eta_date >= idx_to_date(0)]
                v.append({"check": "original ETA missing: exactly one open shipment before new ETA",
                          "ok": len(matches) == 1})
            if len(matches) != 1:
                out["reason"] = f"Could not identify a single shipment ({len(matches)} candidates)."
                return out
            orig = self.ds.shipments[matches[0]].eta_date
            sup = sup or self.ds.shipments[matches[0]].supplier_id
            path = [e for e in path if e[0] == nid("Shipment", matches[0])]
        ok_order = new > orig
        v.append({"check": f"new ETA {new} after original ETA {orig}", "ok": ok_order})
        if not ok_order:
            out["reason"] = "New ETA is not after the original ETA."
            return out
        out.update(ok=True, shipment_id=matches[0], original_eta=orig, supplier_id=sup, path=path)
        return out

    # ------------------------------------------------------------------ disruption + affected orders
    def delay_incident(self, incident_id: str, d: dict) -> dict:
        part, plant, orig, new = d["part_id"], d["plant_id"], d["original_eta"], d["new_eta"]
        models, model_path = self.kg.models_using_part(part)
        models = sorted(set(models) & self.ds.plant_models[plant])
        pos, path = self.kg.orders_needing_part(part, plant, orig, new)
        restart = first_working_on_or_after(new)
        block = Block(incident_id, plant, {date_to_idx(x) for x in working_days(orig, new) if x < new
                                           and 0 <= date_to_idx(x) <= LAST_IDX}, set(models))
        excluded = self._excluded_delay(part, plant, orig, new)
        affected, past = self._clamp(pos, excluded)
        sh_node = nid("Shipment", d["shipment_id"])
        edges = d["path"] + [e for e in model_path if e[2] in {nid("Model", m) for m in models}] + path
        return {
            "incident_id": incident_id, "type": "supplier_delay", "rule_id": R1,
            "disruption": {"plant_id": plant, "part_id": part, "shipment_id": d["shipment_id"],
                           "supplier_id": d["supplier_id"], "blocked_from": orig.isoformat(),
                           "blocked_until_excl": new.isoformat(), "restart": restart.isoformat(),
                           "models_blocked": models},
            "block": block, "restart": restart, "affected_pos": affected, "excluded": excluded + past,
            "path_edges": edges, "anchor": sh_node,
            "reason": f"supplier delay: {part} shipment {d['shipment_id']} to {plant} moved from {orig} to {new}",
        }

    def outage_incident(self, incident_id: str, r: dict) -> dict:
        plant, start, end = r["plant_id"], r["start"], r["end"]
        pos, path = self.kg.orders_at_plant(plant, start, end)
        restart = next_working_day(end)
        block = Block(incident_id, plant, {date_to_idx(x) for x in working_days(start, end)
                                           if 0 <= date_to_idx(x) <= LAST_IDX}, None)
        affected, past = self._clamp(pos, [])
        return {
            "incident_id": incident_id, "type": "plant_outage", "rule_id": R2,
            "disruption": {"plant_id": plant, "blocked_from": start.isoformat(), "blocked_to_incl": end.isoformat(),
                           "restart": restart.isoformat(), "models_blocked": "all"},
            "block": block, "restart": restart, "affected_pos": affected, "excluded": past,
            "path_edges": path, "anchor": nid("Plant", plant),
            "reason": f"plant outage at {plant} {start} to {end}",
        }

    def _clamp(self, pos: list[str], excluded: list[dict]) -> tuple[list[str], list[dict]]:
        keep, past = [], []
        for p in pos:
            if self.ds.production_orders[p].idx >= 0:
                keep.append(p)
            else:
                past.append({"id": p, "reason": "already built (before today), cannot be moved"})
        return keep, past

    def _excluded_delay(self, part: str, plant: str, orig: date, new: date) -> list[dict]:
        out = []
        for po in sorted(self.ds.production_orders.values(), key=lambda p: (p.build_date, p.production_order_id)):
            if po.plant_id == plant and orig <= po.build_date < new and part not in self.ds.bom[po.model]:
                out.append({"id": po.production_order_id, "reason": f"{po.model} does not use {part}"})
        return out

    # ------------------------------------------------------------------ R3 slot search
    def plan_moves(self, incidents: list[dict], ledger: SlotLedger) -> tuple[list[dict], list[dict]]:
        """Returns (planned move actions, decisions). Decisions with kind 'no_slot' need escalation."""
        for inc in incidents:
            ledger.blocks.append(inc["block"])
        restart_of: dict[str, date] = {}
        for inc in incidents:
            for po in inc["affected_pos"]:
                restart_of[po] = max(restart_of.get(po, inc["restart"]), inc["restart"])
        actions, decisions, done = [], [], set()
        for inc in incidents:
            ordered = sorted(inc["affected_pos"],
                             key=lambda p: (self.ds.production_orders[p].build_date, p))
            for po in ordered:
                if po in done:
                    continue
                done.add(po)
                a, dec = self._place(po, restart_of[po], ledger, inc)
                decisions.append(dec)
                if a:
                    actions.append(a)
        return actions, decisions

    def _place(self, po: str, restart: date, ledger: SlotLedger, inc: dict) -> tuple[dict | None, dict]:
        model = ledger.model_of[po]
        origin, from_idx = ledger.loc[po]
        frm = f"{origin} {idx_to_date(from_idx)}"
        restart_idx = date_to_idx(restart) if restart <= idx_to_date(LAST_IDX) else LAST_IDX + 1
        for i in range(max(restart_idx, 0), LAST_IDX + 1):
            if ledger.free(origin, i) and not ledger.blocked(origin, i, model):
                ledger.move(po, origin, i)
                to = idx_to_date(i).isoformat()
                reason = (f"{po} ({model}) affected by {inc['reason']}; earliest free unblocked slot at {origin} "
                          f"on/after restart {restart} is {to}")
                return ({"agent": AGENT, "tool": "mes.reschedule", "args": {"production_order_id": po, "new_date": to},
                         "rule_id": R3, "reason": reason, "incident_id": inc["incident_id"]},
                        {"po": po, "model": model, "from": frm, "to": f"{origin} {to}", "kind": "same_plant",
                         "reason": reason, "rule_id": R3})
        lb = 0 if config.TRANSFER_LOWER_BOUND == "today" else max(restart_idx, 0)
        plants = [p for p in self.ds.plant_order() if p != origin and model in self.ds.plant_models[p]]
        for i in range(lb, LAST_IDX + 1):
            for p in plants:
                if ledger.free(p, i) and not ledger.blocked(p, i, model):
                    ledger.move(po, p, i)
                    to = idx_to_date(i).isoformat()
                    reason = (f"{po} ({model}) affected by {inc['reason']}; no free slot at {origin} on/after "
                              f"{restart}; earliest free slot at a plant that builds {model} is {p} {to}")
                    return ({"agent": AGENT, "tool": "mes.transfer",
                             "args": {"production_order_id": po, "to_plant_id": p, "new_date": to},
                             "rule_id": R3, "reason": reason, "incident_id": inc["incident_id"]},
                            {"po": po, "model": model, "from": frm, "to": f"{p} {to}", "kind": "transfer",
                             "reason": reason, "rule_id": R3})
        reason = f"{po} ({model}): no feasible slot at any eligible plant before {idx_to_date(LAST_IDX)}"
        return None, {"po": po, "model": model, "from": frm, "to": None, "kind": "no_slot", "reason": reason,
                      "rule_id": R10 if config.NO_SLOT_ACTION == "skip" else R3}
