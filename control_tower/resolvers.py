"""Deterministic resolution of entity mentions and date phrases (SPEC section 3)."""
from __future__ import annotations

import re
from datetime import date, timedelta

from rapidfuzz import fuzz, process

from . import config
from .data_loader import TODAY, DataStore, get_store, is_working_day, next_working_day

ID_PATTERNS = {
    "plant": r"\bP_[A-Z]{2}\b",
    "supplier": r"\bSUP-\d{2}\b",
    "shipment": r"\bSH-\d{4}\b",
    "lot": r"\bLOT-\d{4}\b",
    "production_order": r"\bPO-\d{4}\b",
}

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_WD = r"(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*"
_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"

Resolution = tuple[str | None, str, float]


def _norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[\"'`()]", " ", s)
    s = re.sub(r"^(the|our|a|an)\s+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _singular(s: str) -> str:
    words = []
    for w in s.split():
        if len(w) > 3 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        words.append(w)
    return " ".join(words)


def _part_ids(ds: DataStore) -> list[str]:
    return sorted(ds.parts, key=len, reverse=True)


def _ids_of_kind(ds: DataStore, kind: str) -> set[str]:
    return {
        "plant": set(ds.plants), "supplier": set(ds.suppliers), "shipment": set(ds.shipments),
        "lot": set(ds.part_lots), "production_order": set(ds.production_orders), "part": set(ds.parts),
    }[kind]


def find_ids_in_text(text: str, ds: DataStore | None = None) -> dict[str, list[str]]:
    """All explicit ids (plants, suppliers, shipments, lots, parts, POs) in text order, de-duplicated."""
    ds = ds or get_store()
    out: dict[str, list[str]] = {k: [] for k in (*ID_PATTERNS, "part")}
    for kind, pat in ID_PATTERNS.items():
        for m in re.finditer(pat, text):
            if m.group(0) in _ids_of_kind(ds, kind) and m.group(0) not in out[kind]:
                out[kind].append(m.group(0))
    hits = []
    for pid in _part_ids(ds):
        for m in re.finditer(rf"(?<![A-Za-z0-9-]){re.escape(pid)}(?![A-Za-z0-9-])", text):
            hits.append((m.start(), pid))
    for _, pid in sorted(hits):
        if pid not in out["part"]:
            out["part"].append(pid)
    return out


def _name_candidates(ds: DataStore, kind: str) -> dict[str, str]:
    """normalized name -> id, for the name-field resolution step."""
    out: dict[str, str] = {}
    if kind == "plant":
        for p in ds.plants.values():
            out[_norm(p.name)] = p.plant_id
            out[_norm(p.city.split(",")[0])] = p.plant_id
            out[_norm(p.city)] = p.plant_id
    elif kind == "supplier":
        for s in ds.suppliers.values():
            out[_norm(s.name)] = s.supplier_id
            out[_norm(s.name.split()[0])] = s.supplier_id
    elif kind == "part":
        for p in ds.parts.values():
            out[_singular(_norm(p.name))] = p.part_id
    return out


def resolve_entity(mention: str | None, kind: str, ds: DataStore | None = None) -> Resolution:
    """Resolve a mention to an id. Returns (id | None, method, confidence)."""
    ds = ds or get_store()
    if not mention or not mention.strip():
        return None, "missing", 0.0
    text = mention.strip()

    if kind == "part":
        ids = find_ids_in_text(text, ds)["part"]
    else:
        ids = [m.group(0) for m in re.finditer(ID_PATTERNS[kind], text) if m.group(0) in _ids_of_kind(ds, kind)]
    if len(set(ids)) == 1:
        return ids[0], "exact_id", 1.0

    norm = _norm(text)
    aliases = sorted((a for a in ds.aliases if a.entity_type == kind), key=lambda a: len(a.alias), reverse=True)
    for a in aliases:
        an = _norm(a.alias)
        if norm == an or re.search(rf"(?<![a-z0-9]){re.escape(an)}(?![a-z0-9])", norm):
            return a.entity_id, "alias", 1.0

    names = _name_candidates(ds, kind)
    key = _singular(norm) if kind == "part" else norm
    if key in names:
        return names[key], "name", 0.95
    contained = {pid for name, pid in names.items()
                 if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", key)}
    if len(contained) == 1:
        return contained.pop(), "name", 0.9
    if kind == "part" and len(key) >= 6:
        partial = {pid for name, pid in names.items() if key in name}
        if len(partial) == 1:
            return partial.pop(), "name_partial", 0.85

    choices = {**{_norm(a.alias): a.entity_id for a in aliases}, **names}
    best = process.extractOne(key, list(choices), scorer=fuzz.WRatio)
    if best and best[1] >= config.FUZZY_THRESHOLD:
        return choices[best[0]], "fuzzy", round(best[1] / 100, 2)
    return None, "unresolved", 0.0


# ------------------------------------------------------------------------- dates
def _weekday_num(token: str) -> int | None:
    t = token.lower()[:3]
    for i, w in enumerate(WEEKDAYS):
        if w.startswith(t):
            return i
    return None


def _week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def resolve_date(phrase: str | None, today: date = TODAY) -> tuple[date | None, str]:
    """Resolve a date phrase. Returns (date | None, rule_name). Weekday/date mismatch -> (None, 'weekday_mismatch')."""
    if not phrase or not phrase.strip():
        return None, "missing"
    p = phrase.strip().lower()

    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", p)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), "iso_literal"
        except ValueError:
            return None, "invalid_date"

    m = re.search(rf"(?:\b({_WD})\b[\s,]+)?\b({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", p)
    if m:
        month = MONTHS.get(m.group(2)[:3])
        try:
            d = date(today.year, month, int(m.group(3)))
        except (TypeError, ValueError):
            return None, "invalid_date"
        if m.group(1):
            wd = _weekday_num(m.group(1))
            if wd is not None and wd != d.weekday():
                return None, "weekday_mismatch"
            return d, "weekday_month_day_literal"
        return d, "month_day_literal"

    m = re.search(rf"\b(next|this|last|coming)\s+({_WD})\b", p)
    if m:
        wd = _weekday_num(m.group(2))
        if wd is None:
            return None, "unresolved"
        which = m.group(1)
        if which == "last":
            return _week_monday(today) - timedelta(days=7) + timedelta(days=wd), "last_weekday_previous_week"
        if which == "next" and config.NEXT_WEEKDAY == "following_week":
            return _week_monday(today) + timedelta(days=7 + wd), "next_weekday_following_week"
        if which == "next" or which == "coming":
            delta = (wd - today.weekday()) % 7 or 7
            return today + timedelta(days=delta), "next_weekday_nearest_upcoming"
        d = _week_monday(today) + timedelta(days=wd)
        return (d, "this_weekday_current_week") if d >= today else (None, "this_weekday_in_past")

    if re.search(r"\btoday\b", p):
        return today, "today"
    if re.search(r"\btomorrow\b", p):
        return next_working_day(today), "tomorrow_working_day"
    if re.search(r"\byesterday\b", p):
        d = today - timedelta(days=1)
        while not is_working_day(d):
            d -= timedelta(days=1)
        return d, "yesterday_working_day"

    m = re.search(rf"\b({_WD})\b", p)
    if m and _weekday_num(m.group(1)) is not None:
        d = _week_monday(today) + timedelta(days=_weekday_num(m.group(1)))
        return (d, "bare_weekday_current_week") if d >= today else (None, "bare_weekday_in_past")
    return None, "unresolved"
