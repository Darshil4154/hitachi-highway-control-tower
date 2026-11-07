from datetime import date

from control_tower.data_loader import get_store
from control_tower.ontology import get_graph, nid


def test_orders_needing_part_matches_tables():
    ds, kg = get_store(), get_graph()
    for part_id in ("CAM-360", "BATT-60", "CHIP-IVI"):
        for plant_id in ("P_IN", "P_AL"):
            lo, hi = date(2027, 3, 15), date(2027, 3, 25)
            got, edges = kg.orders_needing_part(part_id, plant_id, lo, hi)
            expected = sorted(
                po.production_order_id for po in ds.production_orders.values()
                if po.plant_id == plant_id and part_id in ds.bom[po.model] and lo <= po.build_date < hi
            )
            assert sorted(got) == expected
            for po_id in got:
                po = ds.production_orders[po_id]
                assert po.plant_id == plant_id and part_id in ds.bom[po.model]
                assert po.build_date != hi
            if got:
                assert any(e[1] == "USED_IN" for e in edges)


def test_orders_at_plant_inclusive_both_ends():
    ds, kg = get_store(), get_graph()
    lo, hi = date(2027, 3, 24), date(2027, 3, 25)
    got, _ = kg.orders_at_plant("P_KY", lo, hi)
    expected = sorted(p.production_order_id for p in ds.production_orders.values()
                      if p.plant_id == "P_KY" and lo <= p.build_date <= hi)
    assert sorted(got) == expected
    dates = {ds.production_orders[p].build_date for p in got}
    assert lo in dates and hi in dates


def test_vehicles_for_lot():
    ds, kg = get_store(), get_graph()
    for lot in list(ds.part_lots.values())[::37]:
        got, _ = kg.vehicles_for_lot(lot.lot_id)
        expected = sorted(
            v.vin for v in ds.vehicles.values()
            if v.plant_id == lot.plant_id and lot.first_build_date <= v.build_date <= lot.last_build_date
            and lot.part_id in ds.bom[v.model]
        )
        assert got == expected
        for vin in got:
            v = ds.vehicles[vin]
            assert v.plant_id == lot.plant_id and lot.part_id in ds.bom[v.model]


def test_customer_order_edges():
    kg = get_graph()
    for n, d in kg.g.nodes(data=True):
        if d["type"] != "CustomerOrder":
            continue
        assert len([1 for _, _, k in kg.g.in_edges(n, keys=True) if k == "FULFILLS"]) == 1
        assert len([1 for _, _, k in kg.g.out_edges(n, keys=True) if k == "SOLD_THROUGH"]) == 1
        assert len([1 for _, _, k in kg.g.out_edges(n, keys=True) if k == "ORDERED_BY"]) == 1


def test_find_shipment_and_lots():
    ds, kg = get_store(), get_graph()
    sh = next(iter(ds.shipments.values()))
    got, _ = kg.find_shipment(sh.part_id, sh.plant_id, sh.supplier_id, sh.eta_date)
    assert got == [sh.shipment_id]
    lot = next(iter(ds.part_lots.values()))
    got, _ = kg.find_lots(lot.part_id, lot.plant_id, lot.supplier_id, lot.first_build_date, lot.last_build_date)
    assert got == [lot.lot_id]


def test_explain_path_readable():
    kg = get_graph()
    _, edges = kg.find_shipment("CAM-360", "P_IN")
    text = kg.explain_path(edges)
    assert "-[" in text and "CAM-360" in text
    assert kg.path_between(nid("Part", "CAM-360"), nid("Plant", "P_IN"))
