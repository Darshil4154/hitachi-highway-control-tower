"""Interpretation switches stay internally consistent, and the anti-hallucination guards hold."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from control_tower import ask, config, llm

ROOT = Path(__file__).resolve().parent.parent


def _what_if():
    spec = importlib.util.spec_from_file_location("what_if", ROOT / "eval" / "what_if.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("name,value", [(n, v) for n, v, _ in _what_if().VARIANTS])
def test_every_switch_value_passes_verifier_and_self_check(name, value, monkeypatch):
    wi = _what_if()
    monkeypatch.setattr(config, name, value)
    events = json.loads(config.EVENTS_PATH.read_text(encoding="utf-8"))
    run = wi.run_all(events)
    for eid, r in run.items():
        assert r["score"]["failed"] == 0, eid
        assert all(r["score"]["checks"].values()), (eid, r["score"]["checks"])


def test_rationale_grounding_flags_invented_facts():
    text = "Quick heads up from Orbit: the cameras for Huntsville can't make it Monday Mar 29. Carrier says Apr 1."
    inc = [{"evidence_quote": "Quick heads up from Orbit: the cameras for Huntsville can't make it Monday Mar 29.",
            "new_eta_phrase": "Apr 1"}]
    assert llm.rationale_check("One concrete incident; the other is noise.", text, inc)
    assert llm.rationale_check("Two incidents about the cafeteria menu.", text, inc)
    assert llm.rationale_check("A camera shipment to Huntsville is delayed.", text, inc) == []


def test_gate_reason_is_written_by_code_not_the_llm():
    t = "Plant alert: P_KY is down from 2027-03-15 through 2027-03-17 after a fire."
    ex = llm.rule_extract(t)
    ex.rationale = "The menu line is noise."
    from control_tower.resolvers import resolve_incident

    g = llm.gate(ex, [resolve_incident(i.model_dump(), t) for i in ex.incidents], t)
    assert g["result"] == "incident" and "menu" not in g["reason"] and "P_KY" in g["reason"]


def test_ask_rejects_or_corrects_llm_args_not_in_the_question():
    q = "What is scheduled at Huntsville on Thursday Apr 1?"
    fixed, fixes = ask.normalize_args({"plant_id": "Huntsville", "day": "2023-04-01"}, q)
    assert fixed == {"plant_id": "P_AL", "day": "2027-04-01"} and len(fixes) == 2
    assert ask.ungrounded_args({"event_id": "E-03"}, "Who is affected by E-09?") == ["event_id=E-03"]
    assert ask.ungrounded_args({"event_id": "E-09"}, "Who is affected by event 9?") == []


def test_graph_path_is_independent_of_hash_seed():
    code = "from control_tower.ask import path_between; print(path_between('CAM-360', 'D25')['path'])"
    outs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT,
                           env={"PYTHONHASHSEED": s, "PATH": ""}).stdout for s in ("1", "2")}
    assert len(outs) == 1 and next(iter(outs)).strip()
