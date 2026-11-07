"""Gate + coordinator behaviour on synthetic messages (LLM disabled -> deterministic rule extractor)."""
import pytest

from control_tower import config, llm
from control_tower.agents.coordinator import Coordinator
from control_tower.resolvers import resolve_incident
from control_tower.tools_client import ToolsClient


@pytest.fixture(autouse=True)
def no_llm(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LLM_DISABLED", True)
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "llm")


def _gate(text):
    ex = llm.rule_extract(text)
    return llm.gate(ex, [resolve_incident(i.model_dump(), text) for i in ex.incidents], text)


def test_gate_categories():
    assert _gate("The cafeteria will serve tacos on Friday.")["result"] == "noise"
    assert _gate("Someone said brakes might be late at some point. Not confirmed.")["result"] == "unconfirmed"
    g = _gate("Greensboro is dark from Wednesday Mar 31 through Thursday Apr 1 after a fire.")
    assert g["result"] == "incident"
    g = _gate("Power failure at a plant, production is stopped from 2027-03-24.")
    assert g["result"] in ("needs_review", "unconfirmed") and g["missing_fields"]


def test_gate_flags_weekday_mismatch():
    g = _gate("Quality alert: the leather seats sent to Huntsville are faulty. Anything built Tuesday Mar 2 "
              "through Monday Mar 3 is suspect.")
    assert g["result"] == "needs_review"


def test_noise_makes_zero_calls_and_rumor_one_escalate():
    client = ToolsClient(dry_run=True)
    coord = Coordinator(client)
    t = coord.handle({"event_id": "X-1", "source": "chat", "received_at": "", "text": "Lunch menu: pizza today."})
    assert t["actions"] == [] and client.calls == []
    t = coord.handle({"event_id": "X-2", "source": "chat", "received_at": "",
                      "text": "Rumor: a battery supplier may slip soon. Nothing confirmed."})
    assert [a["tool"] for a in t["actions"]] == ["escalate"]
    assert t["escalation"]["escalated"] and t["escalation"]["missing_fields"]


def test_incident_runs_through_twin_with_zero_failures():
    client = ToolsClient(dry_run=True)
    t = Coordinator(client).handle({"event_id": "X-3", "source": "alert", "received_at": "",
                                    "text": "Greensboro is dark from Wednesday Mar 31 through Thursday Apr 1."})
    assert t["metrics"]["failed"] == 0
    tools = {a["tool"] for a in t["actions"] if a["kind"] == "write"}
    assert {"dealer.notify"} <= tools and tools & {"mes.reschedule", "mes.transfer"}
    assert all(c["ok"] for c in t["verifier"]["plan_checks"] if c["blocking"])
