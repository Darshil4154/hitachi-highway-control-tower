"""Handbook rules as citable constants (source of truth: enterprise/data/policy_handbook.md)."""
from __future__ import annotations

RULES: dict[str, str] = {
    "R1": "Supplier delay: builds needing the delayed part cannot run from the original ETA up to (not including) "
          "the new ETA, only at the receiving plant.",
    "R2": "Plant outage: no builds at the plant during the outage (inclusive); restart the next working day.",
    "R3": "Rescheduling: earliest feasible slot; same plant on/after disruption end, else transfer to a plant that "
          "builds the model on any day with a free slot. Never move unaffected orders.",
    "R4": "Dealer notification: exactly one dealer.notify per dealer listing exactly its affected customer orders.",
    "R5": "Loaners: Platinum/Gold affected customers get one loaner from their dealer pool; priority Platinum > Gold, "
          "earlier promised date, lower customer order id. Standard gets none.",
    "R6": "Quality hold: hold the lot; stop sale of unsold affected vehicles at their dealer; contact owners of sold "
          "affected vehicles.",
    "R7": "Noise: do nothing operational; no write tools.",
    "R8": "Unconfirmed or unclear: no operational action; escalate.",
    "R9": "Completeness: a real incident ends with at least three different kinds of action.",
    "R10": "Do not touch what is not affected.",
}

R1, R2, R3, R4, R5, R6, R7, R8, R9, R10 = (f"R{i}" for i in range(1, 11))

EXECUTION_ORDER = ["mes.reschedule", "mes.transfer", "dealer.notify", "crm.assign_loaner", "quality.hold_lot",
                   "dealer.stop_sale", "crm.notify_customer", "escalate"]


def rule_text(rule_id: str) -> str:
    return RULES.get(rule_id, "")
