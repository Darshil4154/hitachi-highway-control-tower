"""HTTP client for the organizer server (/events, /tools, /act) with call logging and a hard write guard."""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from . import config
from .twin import Twin

READ_TOOLS = {"mes.get_schedule", "crm.loaner_availability"}
BLOCKING_CATEGORIES = {"noise", "unconfirmed", "needs_review"}


class WriteBlocked(RuntimeError):
    """Raised when a write tool is attempted for an event the coordinator marked noise/unconfirmed/needs_review."""


def tool_kind(tool: str) -> str:
    if tool in READ_TOOLS:
        return "read"
    if tool == "escalate":
        return "escalate"
    return "write"


class ToolsClient:
    def __init__(self, base_url: str | None = None, dry_run: bool = False, timeout: float = 15.0):
        self.base_url = (base_url or config.SERVER_URL).rstrip("/")
        self.dry_run = dry_run
        self.timeout = timeout
        self.calls: list[dict] = []
        self._category: dict[str, str] = {}
        self._dry_twins: dict[str, Twin] = {}

    # ---------------------------------------------------------------- guard
    def mark(self, event_id: str, category: str) -> None:
        self._category[event_id] = category

    def _guard(self, event_id: str, tool: str) -> None:
        cat = self._category.get(event_id)
        if cat is None:
            raise WriteBlocked(f"{event_id}: coordinator has not classified this event; refusing {tool}")
        kind = tool_kind(tool)
        if kind == "write" and cat in BLOCKING_CATEGORIES:
            raise WriteBlocked(f"{event_id} is '{cat}': write tool {tool} is blocked")
        if cat == "noise" and kind == "escalate" and not config.ESCALATE_NOISE:
            raise WriteBlocked(f"{event_id} is noise: no calls allowed")

    # ---------------------------------------------------------------- http
    def get_events(self) -> list[dict]:
        r = requests.get(f"{self.base_url}/events", timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_tools(self) -> list[dict]:
        r = requests.get(f"{self.base_url}/tools", timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def act(self, event_id: str, tool: str, args: dict, seq: int | None = None, agent: str = "") -> tuple[bool, dict]:
        """One call, never retried automatically for writes. Returns (ok, result_or_error)."""
        self._guard(event_id, tool)
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        if self.dry_run:
            twin = self._dry_twins.setdefault(event_id, Twin(event_id))
            ok, res = twin.call(tool, args)
        else:
            try:
                r = requests.post(f"{self.base_url}/act", json={"event_id": event_id, "tool": tool, "args": args},
                                  timeout=self.timeout)
                res = r.json()
                ok = r.status_code == 200 and "error" not in res
            except (requests.RequestException, ValueError) as e:
                ok, res = False, {"error": f"{type(e).__name__}: {e}"}
        self.calls.append({"seq": seq, "event_id": event_id, "agent": agent, "tool": tool, "args": args, "ok": ok,
                           "error": None if ok else res.get("error"), "result": res if ok else None,
                           "kind": tool_kind(tool), "ts": ts})
        return ok, res

    def calls_for(self, event_id: str) -> list[dict]:
        return [c for c in self.calls if c["event_id"] == event_id]
