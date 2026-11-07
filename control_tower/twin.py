"""Digital twin: a private copy of the organizer's Enterprise used to dry-run every plan before the real server."""
from __future__ import annotations

from datetime import date

from . import config
from .data_loader import date_to_idx, idx_to_date, load_enterprise_module

_ent = load_enterprise_module()
_BASE = None


def _base():
    """Parsing the CSVs is the slow part; build once and give every twin fresh per-event state."""
    global _BASE
    if _BASE is None:
        _BASE = _ent.Enterprise(str(config.DATA_DIR))
    return _BASE


class Twin:
    WRITE_TOOLS = set(_ent.WRITE_TOOLS)

    def __init__(self, event_id: str):
        self.event_id = event_id
        base = _base()
        self.ent = _ent.Enterprise.__new__(_ent.Enterprise)
        self.ent.__dict__.update({k: v for k, v in base.__dict__.items() if k != "_state"})
        self.ent._state = {}
        self.ent.state(event_id)

    @property
    def state(self) -> dict:
        return self.ent.state(self.event_id)

    def call(self, tool: str, args: dict) -> tuple[bool, dict]:
        try:
            return True, self.ent.call(self.event_id, tool, args)
        except _ent.ToolError as e:
            return False, {"error": str(e)}

    def apply(self, planned_actions: list[dict]) -> list[dict]:
        """Apply planned actions in order. Returns one result per action: {seq, tool, ok, result|error}."""
        out = []
        for a in planned_actions:
            ok, res = self.call(a["tool"], a["args"])
            out.append({"seq": a.get("seq"), "tool": a["tool"], "ok": ok,
                        **({"result": res} if ok else {"error": res["error"]})})
        return out

    def snapshot_slots(self, plants: list[str] | None = None, idx_from: int = 0, idx_to: int = 19) -> dict:
        """{plant: {date: used_slots}} for before/after heatmaps."""
        s = self.state
        plants = plants or list(self.ent.plants)
        return {p: {idx_to_date(i).isoformat(): len(s["slots"].get((p, i), ())) for i in range(idx_from, idx_to + 1)}
                for p in plants}

    def location(self, po_id: str) -> tuple[str, date] | None:
        loc = self.state["loc"].get(po_id)
        return (loc[0], idx_to_date(loc[1])) if loc else None

    def free_slots(self, plant: str, d: date) -> int:
        i = date_to_idx(d)
        return self.ent.plants[plant]["slots"] - len(self.state["slots"].get((plant, i), ()))

    def loaner_pool(self, dealer_id: str) -> int:
        return self.state["loaners"].get(dealer_id, 0)
