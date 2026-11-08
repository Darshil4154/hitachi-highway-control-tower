"""LLM extraction (SPEC section 4): classify + extract raw phrases. Code decides everything else.

The LLM never chooses ids, dates or actions. Its output is validated with pydantic, cached on disk,
retried once on invalid JSON, and replaced by a deterministic rule-based extractor if it still fails
or the endpoint is unreachable (``llm_fallback = true`` in the trace).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from . import config
from .resolvers import resolve_incident, scan_mentions

PROMPT_VERSION = "v3"

BASELINE_TYPES = {"supplier_delay", "plant_outage", "quality_hold"}


class IncidentExtraction(BaseModel):
    type: str

    @field_validator("type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        from .policy_model import extra_type_ids
        allowed = BASELINE_TYPES | extra_type_ids()
        if v not in allowed:
            raise ValueError(f"unknown incident type {v}")
        return v
    evidence_quote: str = ""
    supplier_mention: Optional[str] = None
    part_mention: Optional[str] = None
    plant_mention: Optional[str] = None
    shipment_id: Optional[str] = None
    lot_id: Optional[str] = None
    original_eta_phrase: Optional[str] = None
    new_eta_phrase: Optional[str] = None
    start_phrase: Optional[str] = None
    end_phrase: Optional[str] = None
    window_from_phrase: Optional[str] = None
    window_to_phrase: Optional[str] = None
    is_confirmed: bool = True


class Extraction(BaseModel):
    category: Literal["incident", "noise", "unconfirmed"]
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: str = ""
    incidents: list[IncidentExtraction] = Field(default_factory=list)


SYSTEM_PROMPT = """You are the intake clerk of an automaker's operations control tower. Your ONLY job is to
classify one incoming message and copy out phrases. You never decide actions, never compute dates, never invent ids.

Categories:
- "incident": a concrete, confirmed operational problem for OUR company of one of these types:
    supplier_delay = an inbound shipment of a part to one of our plants arrives later than planned;
    plant_outage  = one of our plants cannot build for a range of days;
    quality_hold  = a part (or lot) installed in our vehicles is defective / suspect for a build window.
- "noise": not about our supply, plants, part quality or customers (marketing, brochures, menus, IT tickets,
   weather or news far away, price lists, greetings). Noise has incidents = [].
- "unconfirmed": possibly about us but a rumor, hearsay, vague, unspecific (no part/plant/date) or explicitly
   not confirmed. Unconfirmed has incidents = [] unless details are given; never guess missing details.

Rules:
- One incident object per incident. A digest with items (1) and (2) yields two incident objects.
- Copy every phrase EXACTLY as written in the message (same words, same case). No date math: "next Friday" stays
  "next Friday". Use null when the message does not say it.
- evidence_quote = the exact sentence(s) of the message describing that incident.
- supplier_delay: original_eta_phrase = when it was due / the date it can't make; new_eta_phrase = the new arrival.
- plant_outage: start_phrase and end_phrase of the stoppage (first and last day the plant is down).
- quality_hold: window_from_phrase and window_to_phrase of the suspect build window; lot_id if a lot is named.
- shipment_id / lot_id only if the literal id (like SH-1234, LOT-1234) is in the message.

Return ONLY JSON:
{"category": "incident|noise|unconfirmed", "confidence": 0.0-1.0, "rationale": "one sentence",
 "incidents": [{"type": "supplier_delay|plant_outage|quality_hold", "evidence_quote": "...",
   "supplier_mention": null, "part_mention": null, "plant_mention": null, "shipment_id": null, "lot_id": null,
   "original_eta_phrase": null, "new_eta_phrase": null, "start_phrase": null, "end_phrase": null,
   "window_from_phrase": null, "window_to_phrase": null, "is_confirmed": true}]}"""

FEW_SHOTS: list[tuple[str, dict]] = [
    (
        "Cheddar Valley Cheese Co: our plant in Wisconsin is down Tuesday through Thursday for cleaning. "
        "Orders of gouda will ship late.",
        {"category": "noise", "confidence": 0.9,
         "rationale": "A cheese company's own plant; not one of our plants, parts or customers.", "incidents": []},
    ),
    (
        "Heard from a guy at the tire expo that rubber might get tight later this year. Nobody has confirmed it.",
        {"category": "unconfirmed", "confidence": 0.85,
         "rationale": "Hearsay with no specific part, plant, shipment or dates.", "incidents": []},
    ),
    (
        "Digest: (1) The Ohio plant is down from Wednesday Jun 2 through Friday Jun 4 after a flood. "
        "(2) Sprocket Metals says the brake rotors for the Ohio plant due Monday Jun 7 will now land Thursday Jun 10. "
        "Also, the cafeteria lunch menu changes next week.",
        {"category": "incident", "confidence": 0.95, "rationale": "Two concrete incidents; the menu line is noise.",
         "incidents": [
             {"type": "plant_outage",
              "evidence_quote": "The Ohio plant is down from Wednesday Jun 2 through Friday Jun 4 after a flood.",
              "supplier_mention": None, "part_mention": None, "plant_mention": "The Ohio plant",
              "shipment_id": None, "lot_id": None, "original_eta_phrase": None, "new_eta_phrase": None,
              "start_phrase": "Wednesday Jun 2", "end_phrase": "Friday Jun 4", "window_from_phrase": None,
              "window_to_phrase": None, "is_confirmed": True},
             {"type": "supplier_delay",
              "evidence_quote": "Sprocket Metals says the brake rotors for the Ohio plant due Monday Jun 7 will now "
                                "land Thursday Jun 10.",
              "supplier_mention": "Sprocket Metals", "part_mention": "brake rotors", "plant_mention": "the Ohio plant",
              "shipment_id": None, "lot_id": None, "original_eta_phrase": "Monday Jun 7",
              "new_eta_phrase": "Thursday Jun 10", "start_phrase": None, "end_phrase": None,
              "window_from_phrase": None, "window_to_phrase": None, "is_confirmed": True},
         ]},
    ),
]

HEDGE_WORDS = [r"\brumou?r", r"\bmay\b(?!\s+\d)", r"\bmight\b", r"\bpossibl[ey]\b", r"\bunconfirmed\b",
               r"\bsomeone (?:mentioned|said)\b", r"\bnot confirmed\b", r"\bnothing confirmed\b", r"\bmaybe\b",
               r"\bheard\b", r"\bhearsay\b", r"\bsometime\b"]


def find_hedges(text: str) -> list[str]:
    from .policy_model import hedge_patterns
    low = text.lower()
    return [m.group(0) for pat in hedge_patterns() for m in [re.search(pat, low)] if m]


# ----------------------------------------------------------------------------- rule-based fallback
_DATE_RX = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"
    r"|\b(?:(?:mon|tue|wed|thu|fri)[a-z]*\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b"
    r"|\b(?:next|last|this)\s+(?:mon|tue|wed|thu|fri)[a-z]*\b",
    re.IGNORECASE,
)
def _keyword_pairs() -> list[tuple[str, str]]:
    from .policy_model import type_keywords
    return type_keywords()


# Phrases the handbook keyword list does not cover, still mapped to handbook types.
_SOFT_KIND_PATTERNS: list[tuple[str, str]] = [
    ("plant_outage", r"weather\s+closure|plant\s+is\s+down|is\s+down\s+from|closed\s+from"),
    ("supplier_delay", r"truck\s+broke|broke\s+down|new\s+arrival|were\s+due|due\s+(?:mon|tue|wed|thu|fri)"),
]


def _assign_date_phrases(inc: IncidentExtraction, seg: str, kind: str, dates: list[str]) -> None:
    """Put each date phrase on original/new or start/end using nearby wording, not only order."""
    from .policy_model import date_fields_for, shape_of
    fields = date_fields_for(kind)
    if not fields or not dates:
        return
    if shape_of(kind) == "plant_window":
        a, b = fields[0][0], fields[1][0]
        setattr(inc, a, dates[0])
        setattr(inc, b, dates[1] if len(dates) > 1 else dates[0])
        return
    # supplier_delay / quality window: prefer wording around each match
    found: dict[str, str] = {}
    for m in _DATE_RX.finditer(seg):
        phrase = m.group(0)
        before = seg[max(0, m.start() - 48):m.start()].lower()
        if re.search(r"new\s+arrival|new\s+eta|will\s+now\s+arrive|now\s+arrive|arriving", before):
            found.setdefault("new_eta_phrase", phrase)
        elif re.search(r"\bdue\b|original|was\s+supposed|can'?t\s+make|cannot\s+make|expected", before):
            found.setdefault("original_eta_phrase", phrase)
        elif re.search(r"\bfrom\b|start|beginning", before):
            found.setdefault("start_phrase", phrase)
        elif re.search(r"\bthrough\b|\buntil\b|\bto\b|end", before):
            found.setdefault("end_phrase", phrase)
    if "new_eta_phrase" in found or "original_eta_phrase" in found:
        if "new_eta_phrase" in found:
            inc.new_eta_phrase = found["new_eta_phrase"]
        if "original_eta_phrase" in found:
            inc.original_eta_phrase = found["original_eta_phrase"]
        # leftover dates: if only new was tagged and a second date exists, keep positional backup off
        return
    if "start_phrase" in found or "end_phrase" in found:
        if "start_phrase" in found:
            inc.start_phrase = found["start_phrase"]
        if "end_phrase" in found:
            inc.end_phrase = found["end_phrase"]
        return
    a, b = fields[0][0], fields[1][0]
    setattr(inc, a, dates[0])
    setattr(inc, b, dates[1] if len(dates) > 1 else (dates[0] if shape_of(kind) == "plant_window" else None))


def rule_extract(text: str) -> Extraction:
    """Deterministic keyword/regex extractor used when the LLM is unavailable or returns invalid JSON."""
    keywords = _keyword_pairs()
    soft = list(keywords) + _SOFT_KIND_PATTERNS
    segments = [s.strip() for s in re.split(r"\(\d\)", text)[1:]] if re.search(r"\(\d\)", text) else [text]
    incidents = []
    for seg in segments:
        low = seg.lower()
        kind = next((k for k, pat in soft if re.search(pat, low)), None)
        if not kind:
            continue
        m = scan_mentions(seg)
        dates = [d.group(0) for d in _DATE_RX.finditer(seg)]
        inc = IncidentExtraction(type=kind, evidence_quote=seg, supplier_mention=m["supplier"],
                                 part_mention=m["part"], plant_mention=m["plant"])
        ids = re.findall(r"\b(SH-\d{4}|LOT-\d{4})\b", seg)
        inc.shipment_id = next((i for i in ids if i.startswith("SH-")), None)
        inc.lot_id = next((i for i in ids if i.startswith("LOT-")), None)
        _assign_date_phrases(inc, seg, kind, dates)
        if any(v for v in (m["plant"], m["part"], inc.lot_id, inc.shipment_id)):
            incidents.append(inc)
    hedges = find_hedges(text)
    if incidents and not hedges:
        return Extraction(category="incident", confidence=0.6, rationale="Rule-based: incident keywords with entities.",
                          incidents=incidents)
    if hedges or any(re.search(p, text.lower()) for p in (pat for _, pat in soft)):
        return Extraction(category="unconfirmed", confidence=0.6,
                          rationale=f"Rule-based: hedged or unspecific report ({', '.join(hedges) or 'no entities'}).",
                          incidents=incidents)
    return Extraction(category="noise", confidence=0.6, rationale="Rule-based: no operational keywords or entities.")


def merge_extra_types(extraction: Extraction, text: str) -> Extraction:
    """Add incidents whose type exists only in the active policy.

    handbook_v1 defines no extra types, so this returns the same extraction and the cached LLM result is unchanged.
    """
    from .policy_model import extra_type_ids
    extras = extra_type_ids()
    if not extras:
        return extraction
    extra_incs = [i for i in rule_extract(text).incidents if i.type in extras]
    if not extra_incs:
        return extraction

    def covers(a: IncidentExtraction, b: IncidentExtraction) -> bool:
        qa, qb = (a.evidence_quote or "").lower(), (b.evidence_quote or "").lower()
        return bool(qa and qb and (qa in qb or qb in qa))

    kept = [i for i in extraction.incidents if i.type in extras or not any(covers(i, e) for e in extra_incs)]
    seen = {(i.type, (i.evidence_quote or "")[:120]) for i in kept}
    for inc in extra_incs:
        key = (inc.type, (inc.evidence_quote or "")[:120])
        if key not in seen:
            kept.append(inc)
            seen.add(key)
    return extraction.model_copy(update={"category": "incident", "incidents": kept})


# ----------------------------------------------------------------------------- client
def system_prompt() -> str:
    """Category list and definitions from the active policy. handbook_v1 reproduces SYSTEM_PROMPT byte for byte."""
    from .policy_model import active, build_system_prompt
    return build_system_prompt(active())


def _messages(text: str) -> list[dict]:
    msgs = [{"role": "system", "content": system_prompt()}]
    for user, answer in FEW_SHOTS:
        msgs.append({"role": "user", "content": f"MESSAGE:\n{user}"})
        msgs.append({"role": "assistant", "content": json.dumps(answer)})
    msgs.append({"role": "user", "content": f"MESSAGE:\n{text}"})
    return msgs


def _cache_key(text: str) -> str:
    return hashlib.sha256(f"{config.LLM_MODEL}|{PROMPT_VERSION}|{system_prompt()}|{text}".encode("utf-8")).hexdigest()


def extract(text: str) -> dict:
    """Returns {extraction: Extraction, llm_model, llm_fallback, llm_calls, prompt_tokens, completion_tokens,
    cached, error}."""
    meta = {"llm_model": config.LLM_MODEL, "llm_fallback": False, "llm_calls": 0, "prompt_tokens": 0,
            "completion_tokens": 0, "cached": False, "error": None}
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = config.CACHE_DIR / f"{_cache_key(text)}.json"
    if cache_file.exists():
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        meta.update(data["meta"], cached=True)
        return {**meta, "extraction": Extraction.model_validate(data["extraction"])}
    if config.LLM_DISABLED:
        return {**meta, "llm_fallback": True, "error": "LLM disabled", "extraction": rule_extract(text)}

    from openai import OpenAI

    client = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY, timeout=config.LLM_TIMEOUT_S,
                    max_retries=0)
    messages = _messages(text)
    extraction = None
    for _attempt in range(2):
        try:
            resp = client.chat.completions.create(model=config.LLM_MODEL, messages=messages, temperature=0,
                                                  response_format={"type": "json_object"})
        except Exception as e:  # endpoint down, model missing, timeout
            meta["error"] = f"{type(e).__name__}: {e}"[:300]
            break
        meta["llm_calls"] += 1
        if resp.usage:
            meta["prompt_tokens"] += resp.usage.prompt_tokens or 0
            meta["completion_tokens"] += resp.usage.completion_tokens or 0
        content = resp.choices[0].message.content or ""
        try:
            extraction = Extraction.model_validate(json.loads(content))
            meta["error"] = None
            break
        except (json.JSONDecodeError, ValidationError) as e:
            meta["error"] = f"invalid JSON: {str(e)[:200]}"
            messages = messages + [{"role": "assistant", "content": content},
                                   {"role": "user", "content": f"Your JSON was invalid: {str(e)[:400]}. "
                                                               "Return corrected JSON only."}]
    if extraction is None:
        return {**meta, "llm_fallback": True, "extraction": rule_extract(text)}
    cache_file.write_text(json.dumps({"meta": {k: meta[k] for k in ("llm_model", "llm_calls", "prompt_tokens",
                                                                     "completion_tokens")},
                                      "extraction": extraction.model_dump()}, indent=2), encoding="utf-8")
    return {**meta, "extraction": extraction}


# ----------------------------------------------------------------------------- rationale grounding
# Words a rationale may use without them appearing in the message (category vocabulary, not facts).
_GENERIC = set("""incident incidents noise concrete operational operations problem problems message mentions
mentioned mention specific category issue issues quality delay delayed supply part parts plant plants shipment
shipments dates date build window hearsay rumor rumour confirmed unconfirmed details detail company about with from
that this there rest other only phrases phrase provided indicating indicates item items report reports nothing
contains named given real actual clear vague none their them they which what when where while also some something
mentioned question request asks asking where find related unrelated not""".split())
_COUNTS = {"one": 1, "two": 2, "three": 3, "four": 4}


def rationale_check(rationale: str, text: str, incidents: list[dict]) -> list[str]:
    """Problems with a free-text LLM rationale: facts not in the message, wrong incident count, or a claim that
    part of the message is noise when every sentence belongs to an incident. Empty list = grounded."""
    issues: list[str] = []
    low = text.lower()
    for w in sorted(set(re.findall(r"[a-z]{4,}", rationale.lower()))):
        if w in _GENERIC or w[:5] in low:
            continue
        issues.append(f"'{w}' is not in the message")
    m = re.search(r"\b(one|two|three|four)\s+(?:concrete\s+|specific\s+)?incidents?\b", rationale.lower())
    if m and _COUNTS[m.group(1)] != len(incidents):
        issues.append(f"says {m.group(1)} incident(s), the message has {len(incidents)}")
    if incidents and re.search(r"\bnoise\b", rationale.lower()):
        phrases = [str(v).lower() for i in incidents for k, v in i.items()
                   if v and isinstance(v, str) and k not in ("type", "evidence_quote")]
        quotes = [(i.get("evidence_quote") or "").lower() for i in incidents]
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\(\d\)", low) if len(re.findall(r"[a-z]{3,}", s)) > 2]
        spare = [s for s in sentences if not any(s in q or q and q in s for q in quotes)
                 and not any(p in s for p in phrases)
                 and not re.fullmatch(r"[\w\s,]*digest[\w\s,.]*", s)]
        if not spare:
            issues.append("calls part of the message noise, but every sentence belongs to an incident")
    return issues


def _incident_label(r: dict) -> str:
    t = r.get("type")
    if t == "supplier_delay":
        return f"supplier delay of {r.get('part_id')} to {r.get('plant_id')} ({r.get('original_eta') or r.get('shipment_id')} -> {r.get('new_eta')})"
    if t == "plant_outage":
        return f"plant outage at {r.get('plant_id')} ({r.get('start')} to {r.get('end')})"
    if t == "quality_hold":
        return f"quality hold on {r.get('lot_id') or r.get('part_id')} ({r.get('window_from')} to {r.get('window_to')})"
    from .policy_model import event_type
    et = event_type(t)
    name = (et.name if et else t or "incident").lower()
    return f"{name} at {r.get('plant_id')} ({r.get('start') or r.get('blocked_from')} to {r.get('end') or r.get('window_to')})"


# ----------------------------------------------------------------------------- gate
REQUIRED = {
    "supplier_delay": "part + plant + new ETA + (original ETA or shipment id)",
    "plant_outage": "plant + start + end",
    "quality_hold": "lot id, or part + plant + build window",
}


def missing_fields(r: dict) -> list[str]:
    from .policy_model import missing_field_names
    return missing_field_names(r)


def gate(extraction: Extraction, resolved: list[dict], text: str) -> dict:
    """Deterministic category gate: noise / unconfirmed / needs_review / incident."""
    hedges = find_hedges(text)
    missing = {i: missing_fields(r) for i, r in enumerate(resolved)}
    review = {i: r["needs_review"] for i, r in enumerate(resolved) if r["needs_review"]}
    all_missing = sorted({f for v in missing.values() for f in v})
    if extraction.category == "noise":
        cross = rule_extract(text)
        if cross.category == "incident" and not hedges:
            cross_resolved = [resolve_incident(i.model_dump(), text) for i in cross.incidents]
            if all(not missing_fields(r) for r in cross_resolved):
                return {"result": "needs_review", "reason": "LLM said noise but the message names a complete "
                        "incident (rule-based cross-check); a human should decide.", "missing_fields": [],
                        "hedges": hedges}
        return {"result": "noise", "reason": "Not about our operations: the LLM classified it as noise and the "
                "rule-based cross-check found no complete incident (no plant, part or lot with dates).",
                "missing_fields": [], "hedges": hedges}
    if extraction.category == "unconfirmed" or not resolved:
        fields = all_missing or ["part", "plant", "dates", "confirmation"]
        return {"result": "unconfirmed", "reason": "Unconfirmed or unspecific report"
                + (f" (hedges: {', '.join(hedges)})" if hedges else "") + f"; missing: {', '.join(fields)}.",
                "missing_fields": fields, "hedges": hedges}
    if hedges and (all_missing or any(not r["is_confirmed"] for r in resolved)):
        return {"result": "unconfirmed", "reason": f"Hedged wording ({', '.join(hedges)}) and missing specifics: "
                f"{', '.join(all_missing) or 'confirmation'}.", "missing_fields": all_missing or ["confirmation"],
                "hedges": hedges}
    if all_missing or review:
        from .policy_model import required_summary
        notes = [f"incident {i + 1} ({resolved[i]['type']}) missing {', '.join(v)} [required: "
                 f"{required_summary(resolved[i]['type'])}]" for i, v in missing.items() if v]
        notes += [f"incident {i + 1}: {'; '.join(v)}" for i, v in review.items()]
        return {"result": "needs_review", "reason": "Cannot act safely: " + " | ".join(notes) + ".",
                "missing_fields": all_missing + [n for v in review.values() for n in v], "hedges": hedges}
    found = "; ".join(_incident_label(r) for r in resolved)
    return {"result": "incident", "reason": f"{len(resolved)} confirmed incident(s), every phrase quoted from the "
            f"message and every id resolved: {found}.", "missing_fields": [], "hedges": hedges}


def main() -> None:
    ap = argparse.ArgumentParser(description="Run LLM extraction + gate over the event feed")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--events", default=None, help="comma-separated event ids")
    args = ap.parse_args()
    events = json.loads(config.EVENTS_PATH.read_text(encoding="utf-8"))
    if args.events:
        wanted = set(args.events.split(","))
        events = [e for e in events if e["event_id"] in wanted]
    print(f"model={config.LLM_MODEL} base={config.LLM_BASE_URL}")
    print(f"{'event':6} {'category':12} {'#':>2} {'types':32} {'gate':13} {'fb':3} {'s':>5}  missing / key phrases")
    for e in events:
        t0 = time.time()
        res = extract(e["text"])
        ex = res["extraction"]
        resolved = [resolve_incident(i.model_dump(), e["text"]) for i in ex.incidents]
        g = gate(ex, resolved, e["text"])
        types = ",".join(i.type for i in ex.incidents) or "-"
        phrases = "; ".join(f"{x['phrase']}->{x['resolved']}" for r in resolved for x in r["extracted"])
        print(f"{e['event_id']:6} {ex.category:12} {len(ex.incidents):>2} {types:32} {g['result']:13} "
              f"{'Y' if res['llm_fallback'] else 'N':3} {time.time() - t0:5.1f}  "
              f"{','.join(g['missing_fields']) or phrases}")


if __name__ == "__main__":
    main()
