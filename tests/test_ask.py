import pytest

from control_tower import ask, config


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.setattr(config, "LLM_DISABLED", True)


@pytest.mark.parametrize("question,function", [
    ("Who is affected by E-09?", "who_is_affected"),
    ("Which dealers were notified for E-01?", "dealers_for_event"),
    ("Which customers at D20 got a loaner after E-01?", "loaners_for_dealer"),
    ("What is scheduled at P_AL on 2027-04-01?", "orders_at_plant_day"),
    ("Which vehicles are in lot LOT-0191?", "vehicles_in_lot"),
    ("How is CAM-360 connected to D25?", "path_between"),
])
def test_router_picks_function(question, function):
    assert ask.route(question)[0] == function


def test_read_only_answers():
    r = ask.ask("What is scheduled at P_AL on 2027-04-01?", use_llm=False)
    assert r["method"] == "keyword_router" and "P_AL" in r["answer"]
    lot = ask.vehicles_in_lot("LOT-0191")
    assert lot["sold"] or lot["unsold"]
    p = ask.path_between("CAM-360", "P_IN")
    assert p["edges"] and "CAM-360" in p["path"]
    assert "error" in ask.loaners_for_dealer("D99")
    assert ask.ask("hello there", use_llm=False)["function"] is None


def test_never_calls_act():
    src = (config.ROOT / "control_tower" / "ask.py").read_text(encoding="utf-8")
    assert "ToolsClient" not in src and "import requests" not in src and "tools_client" not in src
