"""Typed loading of every CSV in enterprise/data plus calendar helpers that mirror enterprise.py."""
from __future__ import annotations

import csv
import importlib.util
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from . import config


def load_enterprise_module():
    """Import the organizer's enterprise.py by path, read-only."""
    if "enterprise" in sys.modules:
        return sys.modules["enterprise"]
    path = config.ENTERPRISE_DIR / "enterprise.py"
    spec = importlib.util.spec_from_file_location("enterprise", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["enterprise"] = module
    spec.loader.exec_module(module)
    return module


_ent = load_enterprise_module()

TODAY: date = _ent.START
FIRST_IDX: int = _ent.FIRST_IDX
LAST_IDX: int = _ent.LAST_IDX
TIER_RANK: dict[str, int] = dict(_ent.TIER_RANK)
LOANER_TIERS: tuple[str, ...] = tuple(_ent.LOANER_TIERS)


def idx_to_date(i: int) -> date:
    return _ent.idx_to_date(i)


def date_to_idx(d: date) -> int:
    return _ent.date_to_idx(d)


def is_working_day(d: date) -> bool:
    return d.weekday() < 5


def working_days(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if is_working_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def next_working_day(d: date) -> date:
    d += timedelta(days=1)
    while not is_working_day(d):
        d += timedelta(days=1)
    return d


LAST_DATE: date = idx_to_date(LAST_IDX)


# ---------------------------------------------------------------- records
@dataclass(frozen=True)
class Plant:
    plant_id: str
    name: str
    city: str
    slots_per_day: int


@dataclass(frozen=True)
class Part:
    part_id: str
    name: str
    category: str


@dataclass(frozen=True)
class Supplier:
    supplier_id: str
    name: str
    city: str


@dataclass(frozen=True)
class Shipment:
    shipment_id: str
    supplier_id: str
    part_id: str
    plant_id: str
    eta_date: date
    covers_days: int


@dataclass(frozen=True)
class ProductionOrder:
    production_order_id: str
    plant_id: str
    build_date: date
    model: str
    units: int

    @property
    def idx(self) -> int:
        return date_to_idx(self.build_date)


@dataclass(frozen=True)
class CustomerOrder:
    customer_order_id: str
    production_order_id: str
    dealer_id: str
    customer_id: str
    model: str
    promised_date: date


@dataclass(frozen=True)
class Customer:
    customer_id: str
    name: str
    tier: str


@dataclass(frozen=True)
class Dealer:
    dealer_id: str
    name: str
    city: str
    region: str
    transit_days: int


@dataclass(frozen=True)
class PartLot:
    lot_id: str
    part_id: str
    supplier_id: str
    plant_id: str
    first_build_date: date
    last_build_date: date


@dataclass(frozen=True)
class Vehicle:
    vin: str
    production_order_id: str
    model: str
    plant_id: str
    build_date: date
    dealer_id: str
    status: str
    customer_id: str | None


@dataclass(frozen=True)
class Alias:
    alias: str
    entity_type: str
    entity_id: str


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _d(s: str) -> date:
    return date.fromisoformat(s)


@dataclass
class DataStore:
    data_dir: Path
    plants: dict[str, Plant] = field(default_factory=dict)
    plant_models: dict[str, set[str]] = field(default_factory=dict)
    models: dict[str, str] = field(default_factory=dict)
    parts: dict[str, Part] = field(default_factory=dict)
    bom: dict[str, set[str]] = field(default_factory=dict)
    suppliers: dict[str, Supplier] = field(default_factory=dict)
    shipments: dict[str, Shipment] = field(default_factory=dict)
    production_orders: dict[str, ProductionOrder] = field(default_factory=dict)
    customer_orders: dict[str, CustomerOrder] = field(default_factory=dict)
    customer_orders_by_po: dict[str, list[CustomerOrder]] = field(default_factory=dict)
    customer_orders_by_dealer: dict[str, list[CustomerOrder]] = field(default_factory=dict)
    customers: dict[str, Customer] = field(default_factory=dict)
    dealers: dict[str, Dealer] = field(default_factory=dict)
    loaners: dict[str, int] = field(default_factory=dict)
    part_lots: dict[str, PartLot] = field(default_factory=dict)
    vehicles: dict[str, Vehicle] = field(default_factory=dict)
    vehicles_by_po: dict[str, list[Vehicle]] = field(default_factory=dict)
    aliases: list[Alias] = field(default_factory=list)
    calendar: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def load(cls, data_dir: Path | str | None = None) -> "DataStore":
        p = Path(data_dir) if data_dir else config.DATA_DIR
        ds = cls(data_dir=p)
        for r in _read(p / "plants.csv"):
            ds.plants[r["plant_id"]] = Plant(r["plant_id"], r["name"], r["city"], int(r["slots_per_day"]))
        ds.plant_models = {pid: set() for pid in ds.plants}
        for r in _read(p / "plant_models.csv"):
            ds.plant_models[r["plant_id"]].add(r["model"])
        ds.models = {r["model"]: r["segment"] for r in _read(p / "models.csv")}
        ds.parts = {r["part_id"]: Part(r["part_id"], r["name"], r["category"]) for r in _read(p / "parts.csv")}
        bom: dict[str, set[str]] = defaultdict(set)
        for r in _read(p / "bom.csv"):
            bom[r["model"]].add(r["part_id"])
        ds.bom = dict(bom)
        ds.suppliers = {
            r["supplier_id"]: Supplier(r["supplier_id"], r["name"], r["city"]) for r in _read(p / "suppliers.csv")
        }
        for r in _read(p / "inbound_shipments.csv"):
            ds.shipments[r["shipment_id"]] = Shipment(
                r["shipment_id"], r["supplier_id"], r["part_id"], r["plant_id"], _d(r["eta_date"]), int(r["covers_days"])
            )
        for r in _read(p / "production_orders.csv"):
            ds.production_orders[r["production_order_id"]] = ProductionOrder(
                r["production_order_id"], r["plant_id"], _d(r["build_date"]), r["model"], int(r["units"])
            )
        by_po: dict[str, list[CustomerOrder]] = defaultdict(list)
        by_dealer: dict[str, list[CustomerOrder]] = defaultdict(list)
        for r in _read(p / "customer_orders.csv"):
            co = CustomerOrder(
                r["customer_order_id"], r["production_order_id"], r["dealer_id"], r["customer_id"], r["model"],
                _d(r["promised_date"]),
            )
            ds.customer_orders[co.customer_order_id] = co
            by_po[co.production_order_id].append(co)
            by_dealer[co.dealer_id].append(co)
        ds.customer_orders_by_po = dict(by_po)
        ds.customer_orders_by_dealer = dict(by_dealer)
        ds.customers = {r["customer_id"]: Customer(r["customer_id"], r["name"], r["tier"]) for r in _read(p / "customers.csv")}
        ds.dealers = {
            r["dealer_id"]: Dealer(r["dealer_id"], r["name"], r["city"], r["region"], int(r["transit_days"]))
            for r in _read(p / "dealers.csv")
        }
        ds.loaners = {r["dealer_id"]: int(r["loaners_available"]) for r in _read(p / "loaners.csv")}
        for r in _read(p / "part_lots.csv"):
            ds.part_lots[r["lot_id"]] = PartLot(
                r["lot_id"], r["part_id"], r["supplier_id"], r["plant_id"], _d(r["first_build_date"]), _d(r["last_build_date"])
            )
        v_by_po: dict[str, list[Vehicle]] = defaultdict(list)
        for r in _read(p / "finished_vehicles.csv"):
            v = Vehicle(
                r["vin"], r["production_order_id"], r["model"], r["plant_id"], _d(r["build_date"]), r["dealer_id"],
                r["status"], r["customer_id"] or None,
            )
            ds.vehicles[v.vin] = v
            v_by_po[v.production_order_id].append(v)
        ds.vehicles_by_po = dict(v_by_po)
        ds.aliases = [Alias(r["alias"], r["entity_type"], r["entity_id"]) for r in _read(p / "aliases.csv")]
        ds.calendar = _read(p / "calendar.csv")
        return ds

    def plant_order(self) -> list[str]:
        if config.PLANT_TIEBREAK == "plant_id_alpha":
            return sorted(self.plants)
        return list(self.plants)


@lru_cache(maxsize=1)
def get_store() -> DataStore:
    return DataStore.load()
