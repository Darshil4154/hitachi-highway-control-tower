"""Specialist agents on a tiny synthetic world (not the real event data)."""
from datetime import date
from pathlib import Path

import pytest

from control_tower import verifier
from control_tower.agents.customer_quality import CustomerCareQuality
from control_tower.agents.dealer_network import DealerNetwork
from control_tower.agents.supply_chain import SlotLedger, SupplyChainPlanner
from control_tower.data_loader import DataStore
from control_tower.ontology import KnowledgeGraph

TABLES = {
    "plants.csv": "plant_id,name,city,slots_per_day\nP_AA,Alpha,\"Alpha, TX\",1\nP_BB,Beta,\"Beta, KY\",1\n"
                  "P_CC,Gamma,\"Gamma, AL\",1\n",
    "plant_models.csv": "plant_id,model\nP_AA,XMOD\nP_BB,YMOD\nP_CC,XMOD\nP_CC,YMOD\n",
    "models.csv": "model,segment\nXMOD,SUV\nYMOD,Sedan\n",
    "parts.csv": "part_id,name,category\nPT-1,widget,electronics\nPT-2,gizmo,body\n",
    "bom.csv": "model,part_id\nXMOD,PT-1\nXMOD,PT-2\nYMOD,PT-2\n",
    "suppliers.csv": "supplier_id,name,city\nSUP-01,Acme Widgets,\"Here, TX\"\n",
    "inbound_shipments.csv": "shipment_id,supplier_id,part_id,plant_id,eta_date,covers_days\n"
                             "SH-0001,SUP-01,PT-1,P_AA,2027-03-29,5\n",
    "production_orders.csv": "production_order_id,plant_id,build_date,model,units\n"
                             "PO-0001,P_AA,2027-03-29,XMOD,10\n"
                             "PO-0002,P_AA,2027-03-30,XMOD,10\n"
                             "PO-0003,P_BB,2027-03-30,YMOD,10\n"
                             "PO-0010,P_CC,2027-03-08,XMOD,10\nPO-0011,P_CC,2027-03-09,YMOD,10\n"
                             "PO-0012,P_CC,2027-03-10,XMOD,10\nPO-0013,P_CC,2027-03-11,YMOD,10\n"
                             "PO-0014,P_CC,2027-03-12,XMOD,10\n"
                             "PO-0020,P_AA,2027-03-01,XMOD,10\n",
    "customers.csv": "customer_id,name,tier\nC1,Ann,Gold\nC2,Bob,Platinum\nC3,Cy,Gold\nC4,Di,Standard\nC5,Ed,Gold\n"
                     "C6,Flo,Gold\n",
    "dealers.csv": "dealer_id,name,city,region,transit_days\nD01,One,\"A, TX\",South,1\nD02,Two,\"B, TX\",South,1\n"
                   "D03,Three,\"C, TX\",South,1\n",
    "loaners.csv": "dealer_id,loaners_available\nD01,1\nD02,0\nD03,5\n",
    "customer_orders.csv": "customer_order_id,production_order_id,dealer_id,customer_id,model,promised_date\n"
                           "CO-00001,PO-0001,D01,C1,XMOD,2027-04-01\n"
                           "CO-00002,PO-0001,D01,C2,XMOD,2027-04-09\n"
                           "CO-00003,PO-0002,D01,C3,XMOD,2027-03-31\n"
                           "CO-00004,PO-0002,D02,C4,XMOD,2027-04-02\n"
                           "CO-00005,PO-0002,D02,C5,XMOD,2027-04-02\n"
                           "CO-00006,PO-0003,D03,C6,YMOD,2027-04-02\n",
    "part_lots.csv": "lot_id,part_id,supplier_id,plant_id,first_build_date,last_build_date\n"
                     "LOT-0001,PT-1,SUP-01,P_AA,2027-03-01,2027-03-02\n",
    "finished_vehicles.csv": "vin,production_order_id,model,plant_id,build_date,dealer_id,status,customer_id\n"
                             "VIN01,PO-0020,XMOD,P_AA,2027-03-01,D01,in_stock,\n"
                             "VIN02,PO-0020,XMOD,P_AA,2027-03-01,D02,sold,C1\n"
                             "VIN03,PO-0020,XMOD,P_AA,2027-03-01,D02,in_stock,\n"
                             "VIN04,PO-0020,XMOD,P_AA,2027-03-01,D01,sold,C1\n",
    "aliases.csv": "alias,entity_type,entity_id\nthe Alpha plant,plant,P_AA\n",
    "calendar.csv": "day_index,date,weekday\n",
}


@pytest.fixture()
def world(tmp_path: Path):
    for name, body in TABLES.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    ds = DataStore.load(tmp_path)
    kg = KnowledgeGraph(ds)
    return ds, kg, SupplyChainPlanner(ds, kg), DealerNetwork(ds), CustomerCareQuality(ds, kg)


def _outage(sc, start, end):
    return sc.outage_incident("I1", {"plant_id": "P_AA", "start": start, "end": end})


def test_capacity_overflow_forces_transfer_to_eligible_plant(world):
    ds, _, sc, _, _ = world
    inc = _outage(sc, date(2027, 3, 29), date(2027, 4, 1))
    assert inc["affected_pos"] == ["PO-0001", "PO-0002"]
    ledger = SlotLedger.from_store(ds)
    actions, decisions = sc.plan_moves([inc], ledger)
    assert actions[0]["tool"] == "mes.reschedule" and actions[0]["args"]["new_date"] == "2027-04-02"
    t = actions[1]
    assert t["tool"] == "mes.transfer"
    assert t["args"]["to_plant_id"] == "P_CC"  # P_BB cannot build XMOD
    assert t["args"]["new_date"] == "2027-03-15"  # P_CC is full Mar 8-12
    assert all(d["kind"] != "no_slot" for d in decisions)


def test_slot_priority_promised_date_serves_earliest_promise_first(world, monkeypatch):
    from control_tower import config

    ds, _, sc, _, _ = world
    monkeypatch.setattr(config, "SLOT_PRIORITY", "promised_date")
    inc = _outage(sc, date(2027, 3, 29), date(2027, 4, 1))
    actions, _ = sc.plan_moves([inc], SlotLedger.from_store(ds))
    # PO-0002 has the earlier promise (Mar 31 vs Apr 1), so it takes the only same-plant slot
    assert actions[0]["args"] == {"production_order_id": "PO-0002", "new_date": "2027-04-02"}
    assert actions[1]["tool"] == "mes.transfer" and actions[1]["args"]["production_order_id"] == "PO-0001"


def test_blocked_days_never_used_and_past_orders_excluded(world):
    ds, _, sc, _, _ = world
    inc = _outage(sc, date(2027, 3, 1), date(2027, 3, 30))
    assert "PO-0020" not in inc["affected_pos"]
    assert any(e["id"] == "PO-0020" for e in inc["excluded"])
    actions, _ = sc.plan_moves([inc], SlotLedger.from_store(ds))
    for a in actions:
        if a["tool"] == "mes.reschedule":
            assert date.fromisoformat(a["args"]["new_date"]) > date(2027, 3, 30)


def test_delay_only_affects_models_using_the_part_at_receiving_plant(world):
    ds, _, sc, _, _ = world
    d = sc.resolve_delay({"part_id": "PT-1", "plant_id": "P_AA", "supplier_id": "SUP-01",
                          "original_eta": date(2027, 3, 29), "new_eta": date(2027, 3, 31), "shipment_id": None})
    assert d["ok"] and d["shipment_id"] == "SH-0001"
    inc = sc.delay_incident("I1", d)
    assert inc["affected_pos"] == ["PO-0001", "PO-0002"]
    bad = sc.resolve_delay({"part_id": "PT-1", "plant_id": "P_AA", "supplier_id": None,
                            "original_eta": date(2027, 3, 22), "new_eta": date(2027, 3, 31), "shipment_id": None})
    assert not bad["ok"]
    mismatch = sc.resolve_delay({"part_id": "PT-2", "plant_id": "P_AA", "supplier_id": None,
                                 "original_eta": None, "new_eta": date(2027, 3, 31), "shipment_id": "SH-0001"})
    assert not mismatch["ok"]


def test_loaner_priority_and_pool_limits(world):
    ds, _, _, _, cq = world
    affected = {c: "I1" for c in ("CO-00001", "CO-00002", "CO-00003", "CO-00004", "CO-00005")}
    actions, decisions = cq.plan_loaners(affected, {"D01": 1, "D02": 0})
    assert [a["args"]["customer_order_id"] for a in actions] == ["CO-00002"]  # Platinum beats earlier Gold
    by_co = {d["co"]: d for d in decisions}
    assert by_co["CO-00003"]["rank"] == 2 and by_co["CO-00003"]["decision"] == "skipped"
    assert by_co["CO-00001"]["rank"] == 3  # later promise than CO-00003
    assert by_co["CO-00004"]["decision"] == "not_eligible"  # Standard
    assert by_co["CO-00005"]["decision"] == "skipped"  # pool 0


def test_loaner_tiebreak_lower_id(world):
    _, _, _, _, cq = world
    actions, _ = cq.plan_loaners({"CO-00001": "I1", "CO-00003": "I1"}, {"D01": 1})
    assert [a["args"]["customer_order_id"] for a in actions] == ["CO-00003"]


def test_one_notify_per_dealer_with_exactly_its_orders(world):
    _, _, _, dn, _ = world
    affected = {"CO-00001": "I1", "CO-00003": "I2", "CO-00004": "I1"}
    acts = dn.plan_notifications(affected, {"PO-0001": "moved", "PO-0002": "moved"},
                                 {c: "an outage" for c in affected})
    assert [(a["args"]["dealer_id"], a["args"]["customer_order_ids"]) for a in acts] == [
        ("D01", ["CO-00001", "CO-00003"]), ("D02", ["CO-00004"])]


def test_quality_stop_sale_only_in_stock_and_owners_once(world):
    _, _, _, dn, cq = world
    lot = cq.resolve_lot({"part_id": "PT-1", "plant_id": "P_AA", "supplier_id": "SUP-01",
                          "window_from": date(2027, 3, 1), "window_to": date(2027, 3, 2), "lot_id": None})
    assert lot["ok"] and lot["lot_id"] == "LOT-0001"
    qp = cq.plan_quality("I1", "LOT-0001")
    assert qp["unsold"] == ["VIN01", "VIN03"] and qp["owners"] == ["C1"]
    stops = dn.plan_stop_sales(qp["unsold"], "I1", "LOT-0001")
    assert [(s["args"]["dealer_id"], s["args"]["vins"]) for s in stops] == [("D01", ["VIN01"]), ("D02", ["VIN03"])]
    assert len(qp["notify_customers"]) == 1
    wrong = cq.resolve_lot({"lot_id": "LOT-0001", "part_id": "PT-2", "plant_id": None, "supplier_id": None,
                            "window_from": None, "window_to": None})
    assert not wrong["ok"]


def test_verifier_catches_unaffected_move_and_bad_notify(world):
    ds, _, sc, dn, _ = world
    inc = _outage(sc, date(2027, 3, 29), date(2027, 4, 1))
    actions, _ = sc.plan_moves([inc], SlotLedger.from_store(ds))
    disruption = {**inc["disruption"], "type": "plant_outage"}
    good = verifier.check_plan(ds, actions, [disruption], {}, set())
    assert all(c["ok"] for c in good if c["name"].startswith("R3") or c["name"].startswith("R10"))
    extra = actions + [{"tool": "mes.reschedule", "args": {"production_order_id": "PO-0003",
                                                           "new_date": "2027-04-02"}}]
    bad = {c["name"]: c["ok"] for c in verifier.check_plan(ds, extra, [disruption], {}, set())}
    assert bad["R10 only affected orders are moved"] is False
    r4 = {c["name"]: c["ok"] for c in verifier.check_plan(ds, actions, [disruption], {}, set())}
    assert r4["R4 exactly one notify per affected dealer with exactly its orders"] is False
