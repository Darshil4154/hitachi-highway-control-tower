"""What-if stays on the twin. Health and the briefing read traces only."""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from control_tower.config import EVENTS_PATH
from control_tower.data_loader import TODAY, get_store
from control_tower.insights import STAGES, build_briefing, health_from_traces, to_markdown, to_pdf
from control_tower.whatif import BANNER, comparison_rows, simulate

ROOT = Path(__file__).resolve().parents[1]


def _events() -> list[dict]:
    return json.loads(EVENTS_PATH.read_text(encoding="utf-8"))


def test_stage_timings_land_in_metrics_and_leave_the_plan_alone():
    from control_tower.agents.coordinator import Coordinator
    from control_tower.tools_client import ToolsClient

    event = next(e for e in _events() if e["event_id"] == "E-05")
    trace = Coordinator(ToolsClient(dry_run=True)).handle(event)
    assert "_stages" not in trace and "_clock" not in trace
    stages = trace["metrics"]["stages_s"]
    assert list(stages) == list(STAGES)
    assert stages["extract"] >= 0 and stages["execute"] == 0
    assert trace["metrics"]["cache"] in ("hit", "miss")
    assert trace["metrics"]["writes"] == 0
    assert trace["plan"] == []


def test_whatif_supplier_delay_does_not_touch_the_network(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("what-if posted to a server")

    monkeypatch.setattr("requests.post", _boom)
    monkeypatch.setattr("requests.get", _boom)
    ds = get_store()
    report = None
    for sh in ds.shipments.values():
        new = (sh.eta_date + timedelta(days=10)).isoformat()
        report = simulate({"kind": "supplier_delay", "shipment_id": sh.shipment_id, "new_eta": new}, label="A")
        if report.get("ok") and report.get("affected_orders"):
            break
    assert report is not None and report["ok"]
    assert report["banner"] == BANNER
    assert report["server_calls"] == 0
    assert report["units"] > 0
    assert report["affected_orders"] > 0
    assert "graph_path" in report and report["graph_path"]
    for miss in report["promise_misses"]:
        assert miss["arrival"] > miss["promised"]


def test_whatif_plant_outage_and_quality_hold():
    ds = get_store()
    po = next(po for po in ds.production_orders.values() if po.build_date >= TODAY)
    plant, day = po.plant_id, po.build_date
    outage = simulate({"kind": "plant_outage", "plant_id": plant, "start": day.isoformat(),
                       "end": day.isoformat()}, label="B")
    assert outage["banner"] == BANNER and outage["units"] > 0 and outage["affected_orders"] > 0
    lot = next(iter(ds.part_lots.values()))
    hold = simulate({"kind": "quality_hold", "lot_id": lot.lot_id, "part_id": lot.part_id,
                     "plant_id": lot.plant_id, "supplier_id": lot.supplier_id,
                     "window_from": lot.first_build_date.isoformat(),
                     "window_to": lot.last_build_date.isoformat()}, label="C")
    assert hold["banner"] == BANNER and hold["ok"]
    rows = comparison_rows(outage, hold)
    assert rows[0]["A"] == "Plant outage" and rows[0]["B"] == "Quality hold"
    assert any(r["Metric"] == "Units delayed" for r in rows)


def test_health_tolerates_traces_without_stages():
    traces = {"E-1": {"ui_category": "noise", "metrics": {
        "llm_model": "qwen2.5:3b-instruct", "llm_cached": True, "prompt_tokens": 10,
        "completion_tokens": 2, "reads": 0, "writes": 0, "failed": 0, "runtime_s": 0.2,
    }}}
    report = health_from_traces(traces)
    assert report["has_stages"] is False
    assert report["failed"] == 0
    assert report["cache_hit_rate"] == 1
    assert report["models"] == ["qwen2.5:3b-instruct"]
    assert report["slowest"][0]["event"] == "E-1"


def test_briefing_from_recorded_traces_is_plain_and_has_three_highlights():
    traces = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "traces").glob("E-*.json"))}
    if not traces:
        pytest.skip("no recorded traces")
    briefing = build_briefing(traces)
    assert len(briefing["highlights"]) == 3
    md = to_markdown(briefing)
    assert "What came in" in md and "Waiting on a person" in md
    assert briefing["failed"] == 0
    assert "0 failed calls." in md
    assert "Platinum" in md and "loaner" in md.lower()
    pdf = to_pdf(briefing)
    assert pdf.startswith(b"%PDF")
