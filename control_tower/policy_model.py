"""Versioned operating policy: event types, playbooks, rules, switches, verifier checks.

handbook_v1.yaml is the scored baseline. The official run loads it unless --policy is passed.
Edited profiles are new files under config/policies/ and are for the sandbox only.
"""
from __future__ import annotations

import difflib
import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

POLICIES = Path(__file__).resolve().parent.parent / "config" / "policies"
AUDIT_PATH = Path(__file__).resolve().parent.parent / "traces" / "policy_audit.jsonl"
DESK_PATH = POLICIES / "desk.json"
HISTORY_PATH = POLICIES / "history.jsonl"

STEP_LIBRARY: dict[str, str] = {
    "find_affected_by_part_window": "Orders at the receiving plant that use the delayed part inside the shipment window.",
    "find_affected_by_plant_window": "Orders at the plant inside the outage window.",
    "reschedule_or_transfer": "Earliest feasible slot: same plant on or after restart, otherwise transfer.",
    "notify_dealers": "One dealer.notify per affected dealer for its customer orders.",
    "assign_loaners": "Loaners for the eligible tiers, ranked by the priority order, within the live pool.",
    "hold_lot": "Hold the suspect lot.",
    "stop_sale_unsold": "Stop sale of unsold vehicles that used the lot.",
    "notify_owners": "Contact the owners of sold vehicles that used the lot.",
    "escalate": "Hand the event to a person. No operational write.",
    "no_action": "Do nothing. No tool calls.",
}
KNOWN_TIERS = ("Platinum", "Gold", "Standard")
KNOWN_SWITCHES = (
    "NEXT_WEEKDAY", "TRANSFER_LOWER_BOUND", "TRANSFER_SEARCH", "PLANT_TIEBREAK", "SLOT_PRIORITY",
    "COMPOUND_ORDER", "NOTIFY_SCOPE", "NO_SLOT_ACTION", "ESCALATE_NOISE", "FUZZY_THRESHOLD",
)
SWITCH_OPTIONS: dict[str, list] = {
    "NEXT_WEEKDAY": ["following_week", "nearest_upcoming"],
    "TRANSFER_LOWER_BOUND": ["restart", "today"],
    "TRANSFER_SEARCH": ["day_first", "plant_first"],
    "PLANT_TIEBREAK": ["plants_csv_order", "plant_id_alpha"],
    "SLOT_PRIORITY": ["build_date", "promised_date"],
    "COMPOUND_ORDER": ["message_order", "earliest_disruption_first"],
    "NOTIFY_SCOPE": ["per_event", "per_incident"],
    "NO_SLOT_ACTION": ["escalate", "skip"],
    "ESCALATE_NOISE": [False, True],
}

BASELINE_NOISE = (
    "not about our supply, plants, part quality or customers (marketing, brochures, menus, IT tickets,\n"
    "   weather or news far away, price lists, greetings). Noise has incidents = []."
)
BASELINE_UNCONFIRMED = (
    "possibly about us but a rumor, hearsay, vague, unspecific (no part/plant/date) or explicitly\n"
    "   not confirmed. Unconfirmed has incidents = [] unless details are given; never guess missing details."
)


class PolicyError(ValueError):
    pass


class PolicyRefused(PolicyError):
    """The official run will not load an edited profile unless --policy names it."""


class RequiredField(BaseModel):
    field: str
    key: str | None = None
    any_of: list[str] | None = None


class EventType(BaseModel):
    id: str
    name: str
    description: str = ""
    category: Literal["incident", "noise", "unconfirmed"] = "incident"
    keywords: str = ""
    examples: list[str] = Field(default_factory=list)
    phrase_hint: str = ""
    prompt_clause: str | None = None
    required_summary: str = ""
    required_if_absent: str | None = None
    required: list[RequiredField] = Field(default_factory=list)
    playbook: str
    prompt_rank: int = 100
    shape: Literal["part_window", "plant_window", "lot", "none"] = "none"
    window_start: Literal["inclusive", "exclusive"] = "inclusive"
    window_end: Literal["inclusive", "exclusive"] = "inclusive"
    date_fields: list[tuple[str, str]] = Field(default_factory=list)
    sanity_left: str | None = None
    sanity_right: str | None = None
    sanity_allow_equal: bool = True


class Playbook(BaseModel):
    steps: list[str]


class Rules(BaseModel):
    loaner_tiers: list[str]
    tier_priority: list[str]
    min_action_kinds: int = 3
    hedge_patterns: list[str]
    noise_topics: list[str]


class VerifierCheck(BaseModel):
    id: str
    name: str
    enabled: bool = True
    severity: Literal["block", "warn"] = "block"


class Policy(BaseModel):
    id: str
    name: str
    label: str = ""
    status: str = "draft"
    read_only: bool = False
    author: str = ""
    reason: str = ""
    noise_prompt: str = BASELINE_NOISE
    unconfirmed_prompt: str = BASELINE_UNCONFIRMED
    event_types: list[EventType]
    playbooks: dict[str, Playbook]
    rules: Rules
    switches: dict[str, Any]
    verifier: list[VerifierCheck]

    @model_validator(mode="after")
    def _consistent(self) -> "Policy":
        ids = [e.id for e in self.event_types]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate event type id")
        for et in self.event_types:
            if et.playbook not in self.playbooks:
                raise ValueError(f"event type {et.id} references unknown playbook {et.playbook}")
        for name, book in self.playbooks.items():
            if not book.steps:
                raise ValueError(f"playbook {name} is empty")
            unknown = [s for s in book.steps if s not in STEP_LIBRARY]
            if unknown:
                raise ValueError(f"playbook {name} has unknown step(s): {', '.join(unknown)}")
            if len(book.steps) != len(set(book.steps)):
                raise ValueError(f"playbook {name} repeats a step")
        for tier in list(self.rules.loaner_tiers) + list(self.rules.tier_priority):
            if tier not in KNOWN_TIERS:
                raise ValueError(f"unknown tier {tier}")
        missing = [s for s in KNOWN_SWITCHES if s not in self.switches]
        if missing:
            raise ValueError(f"switches missing: {', '.join(missing)}")
        if self.rules.min_action_kinds < 1:
            raise ValueError("min_action_kinds must be at least 1")
        return self

    def event_type(self, type_id: str | None) -> EventType | None:
        return next((e for e in self.event_types if e.id == type_id), None)

    def incident_types(self) -> list[EventType]:
        return [e for e in self.event_types if e.category == "incident"]

    def steps(self, type_id: str | None) -> list[str]:
        et = self.event_type(type_id)
        if et is None:
            return []
        return list(self.playbooks[et.playbook].steps)

    def check_spec(self, check_id: str) -> VerifierCheck | None:
        return next((c for c in self.verifier if c.id == check_id), None)

    def is_baseline(self) -> bool:
        return self.id == "handbook_v1" or self.status == "scored_baseline" or self.read_only


_active: Policy | None = None


def load(name: str) -> Policy:
    stem = name[:-5] if name.endswith(".yaml") else name
    path = POLICIES / f"{stem}.yaml"
    if not path.exists():
        raise PolicyError(f"no policy file {path.name}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Policy.model_validate(data)


def active() -> Policy:
    global _active
    if _active is None:
        _active = load("handbook_v1")
    return _active


def activate(pol: Policy) -> None:
    """Make pol the policy the agents read, and copy its switches onto config."""
    global _active
    _active = pol
    from . import config
    config.apply_switches(pol.switches)


@contextmanager
def using(pol: Policy) -> Iterator[Policy]:
    prev = active()
    activate(pol)
    try:
        yield pol
    finally:
        activate(prev)


def load_for_official_run(name: str | None, *, explicit: bool) -> Policy:
    """The scored run. An edited profile is refused unless --policy passed it explicitly."""
    stem = (name or "").removesuffix(".yaml")
    if not stem or stem == "handbook_v1":
        return load("handbook_v1")
    if not explicit:
        raise PolicyRefused(
            f"The official run uses the scored baseline handbook_v1 unless --policy is passed. Refusing {stem}."
        )
    return load(stem)


def list_policies() -> list[Policy]:
    out = []
    for path in sorted(POLICIES.glob("*.yaml")):
        try:
            out.append(Policy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError, yaml.YAMLError):
            continue
    return out


def dump_yaml(pol: Policy) -> str:
    return yaml.safe_dump(pol.model_dump(mode="json"), sort_keys=False, allow_unicode=True, width=100)


def save_new_version(pol: Policy, author: str, reason: str) -> Policy:
    """Write a new profile file. handbook_v1 is never overwritten."""
    if not author.strip() or not reason.strip():
        raise PolicyError("Publish needs an author and a reason.")
    base = _slug(pol.name or pol.id)
    if base == "handbook":
        base = "profile"
    n = 1
    while (POLICIES / f"{base}_v{n}.yaml").exists():
        n += 1
    new_id = f"{base}_v{n}"
    published = pol.model_copy(update={
        "id": new_id, "status": "published", "read_only": False, "label": f"Published v{n}",
        "author": author.strip(), "reason": reason.strip(),
    })
    path = POLICIES / f"{new_id}.yaml"
    path.write_text(dump_yaml(published), encoding="utf-8")
    _history("publish", new_id, author, reason, f"saved {path.name}")
    return published


def set_desk(profile_id: str, author: str = "manager", reason: str = "desk profile") -> None:
    if not (POLICIES / f"{profile_id}.yaml").exists():
        raise PolicyError(f"no profile {profile_id}")
    DESK_PATH.write_text(json.dumps({"profile": profile_id}, indent=2) + "\n", encoding="utf-8")
    _history("desk", profile_id, author, reason, "Live Incident Desk profile")


def desk_profile() -> str:
    if not DESK_PATH.exists():
        return "handbook_v1"
    try:
        return json.loads(DESK_PATH.read_text(encoding="utf-8")).get("profile") or "handbook_v1"
    except json.JSONDecodeError:
        return "handbook_v1"


def rollback(profile_id: str, author: str, reason: str) -> None:
    """Point the sandbox back at an existing version. Does not edit handbook_v1."""
    if not author.strip() or not reason.strip():
        raise PolicyError("Rollback needs an author and a reason.")
    set_desk(profile_id, author, reason)
    _history("rollback", profile_id, author, reason, "sandbox rolled back to this profile")


def history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    return [json.loads(line) for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def audit_rows() -> list[dict]:
    if not AUDIT_PATH.exists():
        return []
    return [json.loads(line) for line in AUDIT_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def yaml_diff(a: Policy, b: Policy) -> str:
    left = dump_yaml(a).splitlines(keepends=True)
    right = dump_yaml(b).splitlines(keepends=True)
    return "".join(difflib.unified_diff(left, right, fromfile=a.id, tofile=b.id))


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "profile"


def _history(kind: str, profile_id: str, author: str, reason: str, detail: str) -> None:
    row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind,
           "profile": profile_id, "author": author, "reason": reason, "detail": detail}
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------- what the agents read
def steps_for(type_id: str | None) -> list[str]:
    return active().steps(type_id)


def event_type(type_id: str | None) -> EventType | None:
    return active().event_type(type_id)


def query_bounds(type_id: str | None, start, end, default_end: str):
    """Dates to plug into the existing window comparison.

    ``default_end`` is ``exclusive`` for a part window (orig <= day < end) and ``inclusive`` for a plant
    window (start <= day <= end). Handbook flags match those defaults, so the dates come back unchanged.
    """
    from datetime import timedelta
    et = event_type(type_id)
    if et is None or (et.window_start == "inclusive" and et.window_end == default_end):
        return start, end
    s = start + timedelta(days=1) if et.window_start == "exclusive" else start
    if et.window_end == default_end:
        e = end
    elif default_end == "exclusive":
        e = end + timedelta(days=1)
    else:
        e = end - timedelta(days=1)
    return s, e


def shape_of(type_id: str | None) -> str:
    et = event_type(type_id)
    if et is not None and et.shape != "none":
        return et.shape
    return {"supplier_delay": "part_window", "plant_outage": "plant_window", "quality_hold": "lot"}.get(
        type_id or "", "lot")


def date_fields_for(type_id: str | None) -> list[tuple[str, str]]:
    et = event_type(type_id)
    if et is not None and et.date_fields:
        return list(et.date_fields)
    from .resolvers import DATE_FIELDS
    return list(DATE_FIELDS.get(type_id or "", []))


def sanity_for(type_id: str | None) -> tuple[str, str, bool] | None:
    et = event_type(type_id)
    if et is not None and et.sanity_left and et.sanity_right:
        return et.sanity_left, et.sanity_right, et.sanity_allow_equal
    fallback = {"supplier_delay": ("original_eta", "new_eta", False),
                "plant_outage": ("start", "end", True),
                "quality_hold": ("window_from", "window_to", True)}
    return fallback.get(type_id or "")


def type_keywords() -> list[tuple[str, str]]:
    return [(e.id, e.keywords) for e in active().event_types if e.keywords]


def hedge_patterns() -> list[str]:
    return list(active().rules.hedge_patterns)


def loaner_tiers() -> tuple[str, ...]:
    return tuple(active().rules.loaner_tiers)


def loaner_rank(tier: str) -> int:
    order = active().rules.tier_priority
    return order.index(tier) if tier in order else len(order)


def required_summary(type_id: str | None) -> str:
    et = event_type(type_id)
    return et.required_summary if et and et.required_summary else "?"


def missing_field_names(resolved: dict) -> list[str]:
    et = event_type(resolved.get("type"))
    if et is None or et.category != "incident":
        return ["incident_type"]
    if et.required_if_absent and resolved.get(et.required_if_absent):
        return []
    miss: list[str] = []
    for req in et.required:
        # A concrete new ETA is enough to look up the open shipment in the twin;
        # do not also demand original ETA / shipment id for the gate missing list.
        if req.field == "original_eta_or_shipment_id" and resolved.get("new_eta"):
            continue
        if req.any_of:
            if not any(resolved.get(k) for k in req.any_of):
                miss.append(req.field)
        elif req.key and not resolved.get(req.key):
            miss.append(req.field)
    return miss


def extra_type_ids() -> set[str]:
    baseline = {"supplier_delay", "plant_outage", "quality_hold", "noise", "unconfirmed"}
    return {e.id for e in active().incident_types()} - baseline


def build_system_prompt(pol: Policy | None = None) -> str:
    """Category list and definitions come from the policy's event types.

    For handbook_v1 the stored clauses reproduce the original prompt byte for byte, so the LLM cache hits.
    """
    pol = pol or active()
    incidents = sorted(pol.incident_types(), key=lambda e: (e.prompt_rank, e.id))
    clauses = []
    for et in incidents:
        if et.prompt_clause:
            clauses.append(et.prompt_clause)
        else:
            clauses.append(f"    {et.id} = {et.description}.")
    # The baseline prompt puts a semicolon on every definition except the last, which has a period.
    # Stored clauses already include that punctuation. Generated ones use a period; fix the joiners
    # when more than the stored baseline is present.
    if any(et.prompt_clause is None for et in incidents):
        rebuilt = []
        for i, et in enumerate(incidents):
            text = et.prompt_clause or f"    {et.id} = {et.description}"
            text = text.rstrip(";.").rstrip()
            text += "." if i == len(incidents) - 1 else ";"
            rebuilt.append(text)
        clauses = rebuilt
    hints = "\n".join(f"- {et.id}: {et.phrase_hint}" for et in incidents if et.phrase_hint)
    union = "|".join(et.id for et in incidents)
    return (
        "You are the intake clerk of an automaker's operations control tower. Your ONLY job is to\n"
        "classify one incoming message and copy out phrases. You never decide actions, never compute dates, never invent ids.\n"
        "\n"
        "Categories:\n"
        "- \"incident\": a concrete, confirmed operational problem for OUR company of one of these types:\n"
        + "\n".join(clauses) + "\n"
        "- \"noise\": " + pol.noise_prompt + "\n"
        "- \"unconfirmed\": " + pol.unconfirmed_prompt + "\n"
        "\n"
        "Rules:\n"
        "- One incident object per incident. A digest with items (1) and (2) yields two incident objects.\n"
        "- Copy every phrase EXACTLY as written in the message (same words, same case). No date math: \"next Friday\" stays\n"
        "  \"next Friday\". Use null when the message does not say it.\n"
        "- evidence_quote = the exact sentence(s) of the message describing that incident.\n"
        + hints + "\n"
        "- shipment_id / lot_id only if the literal id (like SH-1234, LOT-1234) is in the message.\n"
        "\n"
        "Return ONLY JSON:\n"
        "{\"category\": \"incident|noise|unconfirmed\", \"confidence\": 0.0-1.0, \"rationale\": \"one sentence\",\n"
        " \"incidents\": [{\"type\": \"" + union + "\", \"evidence_quote\": \"...\",\n"
        "   \"supplier_mention\": null, \"part_mention\": null, \"plant_mention\": null, \"shipment_id\": null, \"lot_id\": null,\n"
        "   \"original_eta_phrase\": null, \"new_eta_phrase\": null, \"start_phrase\": null, \"end_phrase\": null,\n"
        "   \"window_from_phrase\": null, \"window_to_phrase\": null, \"is_confirmed\": true}]}"
    )
