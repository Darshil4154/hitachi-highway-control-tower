import csv
from datetime import date, timedelta

import pytest

from control_tower import config
from control_tower.data_loader import (
    LAST_IDX,
    TODAY,
    date_to_idx,
    get_store,
    idx_to_date,
    next_working_day,
    working_days,
)


def _count(name: str) -> int:
    with (config.DATA_DIR / name).open(encoding="utf-8") as f:
        return sum(1 for _ in csv.DictReader(f))


def test_row_counts_match_csvs():
    ds = get_store()
    assert len(ds.plants) == _count("plants.csv")
    assert sum(len(v) for v in ds.plant_models.values()) == _count("plant_models.csv")
    assert sum(len(v) for v in ds.bom.values()) == _count("bom.csv")
    assert len(ds.shipments) == _count("inbound_shipments.csv")
    assert len(ds.production_orders) == _count("production_orders.csv")
    assert len(ds.customer_orders) == _count("customer_orders.csv")
    assert len(ds.customers) == _count("customers.csv")
    assert len(ds.dealers) == _count("dealers.csv")
    assert len(ds.loaners) == _count("loaners.csv")
    assert len(ds.part_lots) == _count("part_lots.csv")
    assert len(ds.vehicles) == _count("finished_vehicles.csv")
    assert len(ds.aliases) == _count("aliases.csv")


def test_plants_keep_file_order():
    ds = get_store()
    with (config.DATA_DIR / "plants.csv").open(encoding="utf-8") as f:
        assert list(ds.plants) == [r["plant_id"] for r in csv.DictReader(f)]


def test_every_production_order_plant_can_build_model():
    ds = get_store()
    for po in ds.production_orders.values():
        assert po.model in ds.plant_models[po.plant_id], po


def test_customer_order_indexes():
    ds = get_store()
    assert sum(len(v) for v in ds.customer_orders_by_po.values()) == len(ds.customer_orders)
    assert sum(len(v) for v in ds.customer_orders_by_dealer.values()) == len(ds.customer_orders)


def test_calendar_round_trip_all_30_days():
    ds = get_store()
    assert len(ds.calendar) == 30
    for row in ds.calendar:
        i, d = int(row["day_index"]), date.fromisoformat(row["date"])
        assert idx_to_date(i) == d
        assert date_to_idx(d) == i
    assert idx_to_date(0) == TODAY == date(2027, 3, 8)
    assert idx_to_date(LAST_IDX) == date(2027, 4, 2)


def test_weekends_raise():
    for d in (date(2027, 3, 6), date(2027, 3, 7), date(2027, 3, 13), date(2027, 3, 14)):
        with pytest.raises(ValueError):
            date_to_idx(d)


def test_working_days_and_next_working_day():
    assert working_days(date(2027, 3, 19), date(2027, 3, 22)) == [date(2027, 3, 19), date(2027, 3, 22)]
    assert next_working_day(date(2027, 3, 19)) == date(2027, 3, 22)
    assert next_working_day(date(2027, 3, 8)) == date(2027, 3, 9)
    assert all(d.weekday() < 5 for d in working_days(TODAY, TODAY + timedelta(days=30)))
