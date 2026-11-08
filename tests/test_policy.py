"""Policy registry: schema, scored-baseline identity, sandbox event types, official-run guard."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from control_tower import config, llm  # noqa: E402
from control_tower.agents.coordinator import Coordinator  # noqa: E402
from control_tower.llm import SYSTEM_PROMPT  # noqa: E402
from control_tower.policy_model import (  # noqa: E402
    POLICIES, Policy, PolicyError, PolicyRefused, build_system_prompt, desk_profile, load, load_for_official_run,
    rollback, save_new_version,
)
from control_tower.sandbox import handle_text  # noqa: E402
from control_tower.tools_client import ToolsClient  # noqa: E402

PROMPT_HASH = "adc665003c94c9225db64fb5c145631d67767dbbdb5e8c3da96ec7b04454fb4e"
PLAN_HASH = "c8cb080d69f3a0c2d7acb3fef0301ea5d3abe61006ee2b561f0345b8156942fe"
WEATHER = "Weather closure: the Texas plant is down from 2027-03-26 through 2027-03-30."


def _broken(mutator):
    data = load("handbook_v1").model_dump(mode="json")
    mutator(data)
    with pytest.raises(ValidationError):
        Policy.model_validate(data)


def test_schema_rejects_unknown_step():
    _broken(lambda d: d["playbooks"]["noise"].__setitem__("steps", ["fly_to_the_moon"]))


def test_schema_rejects_empty_playbook():
    _broken(lambda d: d["playbooks"]["noise"].__setitem__("steps", []))


def test_schema_rejects_unknown_tier():
    _broken(lambda d: d["rules"].__setitem__("loaner_tiers", ["Silver"]))


def test_handbook_prompt_and_plans_are_unchanged():
    pol = load("handbook_v1")
    assert pol.label == "Scored baseline" and pol.read_only
    built = build_system_prompt(pol)
    assert built == SYSTEM_PROMPT
    assert hashlib.sha256(built.encode()).hexdigest() == PROMPT_HASH
    events = json.loads(config.EVENTS_PATH.read_text(encoding="utf-8"))
    client = ToolsClient(dry_run=True)
    coord = Coordinator(client)
    plans = {}
    writes = 0
    for e in events:
        trace = coord.handle(e)
        plans[e["event_id"]] = trace["plan"]
        writes += trace["metrics"]["writes"]
    blob = json.dumps(plans, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(blob.encode()).hexdigest() == PLAN_HASH
    assert writes == 766


def _weather_policy() -> Policy:
    data = load("handbook_v1").model_dump(mode="json")
    plant = next(t for t in data["event_types"] if t["id"] == "plant_outage")
    weather = json.loads(json.dumps(plant))
    weather.update({
        "id": "weather_closure",
        "name": "Weather closure",
        "description": "a plant is closed because of weather",
        "keywords": "weather closure",
        "examples": ["Weather closure at a plant for a range of days."],
        "phrase_hint": "start_phrase and end_phrase of the closure.",
        "prompt_clause": None,
        "required_summary": "plant + start + end",
        "playbook": "plant_outage",
        "prompt_rank": 0,
        "shape": "plant_window",
    })
    data["event_types"].insert(0, weather)
    data.update(id="sandbox_weather", name="Sandbox weather", label="sandbox", status="draft", read_only=False,
                author="test", reason="new event type")
    return Policy.model_validate(data)


def test_weather_closure_is_classified_and_handled_in_the_sandbox():
    pol = _weather_policy()
    ruled = None
    from control_tower.policy_model import using
    with using(pol):
        ruled = llm.rule_extract(WEATHER)
        planted = llm.Extraction(category="incident", confidence=0.9, rationale="model said outage",
                                 incidents=[llm.IncidentExtraction(type="plant_outage", evidence_quote=WEATHER,
                                                                    plant_mention="the Texas plant",
                                                                    start_phrase="2027-03-26", end_phrase="2027-03-30")])
        merged = llm.merge_extra_types(planted, WEATHER)
    assert ruled.incidents[0].type == "weather_closure"
    assert merged.incidents[0].type == "weather_closure"
    assert llm.merge_extra_types(ruled, WEATHER) is not None
    with using(load("handbook_v1")):
        same = llm.rule_extract(WEATHER)
        assert llm.merge_extra_types(same, WEATHER) is same
    trace = handle_text(WEATHER, pol, event_id="WEATHER", force_rules=True)
    assert trace["incidents"][0]["type"] == "weather_closure"
    assert trace["classification"]["gate"] == "incident"
    tools = {a["tool"] for a in trace["plan"]}
    assert tools & {"mes.reschedule", "mes.transfer"}


def test_official_run_refuses_an_edited_profile_without_the_flag(tmp_path, monkeypatch):
    with pytest.raises(PolicyRefused):
        load_for_official_run("zz_policytest_v1", explicit=False)
    assert load_for_official_run(None, explicit=False).id == "handbook_v1"
    edited = load("handbook_v1").model_copy(update={
        "id": "zz_policytest_v1", "name": "ZZ", "read_only": False, "status": "published", "label": "test"})
    path = POLICIES / "zz_policytest_v1.yaml"
    path.write_text(__import__("control_tower.policy_model", fromlist=["dump_yaml"]).dump_yaml(edited), encoding="utf-8")
    desk = POLICIES / "desk.json"
    previous = desk.read_text(encoding="utf-8") if desk.exists() else None
    desk.write_text('{"profile": "zz_policytest_v1"}\n', encoding="utf-8")
    try:
        assert load_for_official_run("zz_policytest_v1", explicit=True).id == "zz_policytest_v1"
        assert load_for_official_run(None, explicit=False).id == "handbook_v1"
        py = sys.executable
        plain = subprocess.run(
            [py, "-m", "control_tower.run", "--dry-run", "--events", "E-05", "--traces", str(tmp_path / "plain")],
            cwd=ROOT, capture_output=True, text=True, check=False)
        assert plain.returncode == 0, plain.stderr
        assert "policy=handbook_v1" in plain.stdout
        named = subprocess.run(
            [py, "-m", "control_tower.run", "--dry-run", "--events", "E-05", "--policy", "zz_policytest_v1",
             "--traces", str(tmp_path / "named")],
            cwd=ROOT, capture_output=True, text=True, check=False)
        assert named.returncode == 0, named.stderr
        assert "policy=zz_policytest_v1" in named.stdout
    finally:
        path.unlink(missing_ok=True)
        if previous is None:
            desk.unlink(missing_ok=True)
        else:
            desk.write_text(previous, encoding="utf-8")
    monkeypatch.setattr("control_tower.policy_model.POLICIES", tmp_path)
    monkeypatch.setattr("control_tower.policy_model.DESK_PATH", tmp_path / "desk.json")
    monkeypatch.setattr("control_tower.policy_model.HISTORY_PATH", tmp_path / "history.jsonl")
    monkeypatch.setattr("control_tower.policy_model.AUDIT_PATH", tmp_path / "policy_audit.jsonl")
    shutil.copy(ROOT / "config" / "policies" / "handbook_v1.yaml", tmp_path / "handbook_v1.yaml")
    published = save_new_version(load("handbook_v1").model_copy(update={"name": "Night shift"}), "Ada", "sandbox only")
    assert published.id == "night_shift_v1"
    assert (tmp_path / "night_shift_v1.yaml").exists()
    assert "Night shift" not in (tmp_path / "handbook_v1.yaml").read_text(encoding="utf-8")
    with pytest.raises(PolicyError):
        save_new_version(published, " ", " ")
    rollback("handbook_v1", "Ada", "return the desk to the scored baseline")
    assert desk_profile() == "handbook_v1"
    from control_tower.policy_model import audit_rows
    kinds = [row["kind"] for row in audit_rows()]
    assert "publish" in kinds and "rollback" in kinds
