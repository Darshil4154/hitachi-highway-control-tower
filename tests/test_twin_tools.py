import pytest

from control_tower.data_loader import get_store, idx_to_date
from control_tower.tools_client import ToolsClient, WriteBlocked
from control_tower.twin import Twin


def test_twin_rejects_overbooking_and_reports_it():
    twin = Twin("T-1")
    plant, idx = "P_TX", 5
    day = idx_to_date(idx).isoformat()
    others = sorted(po for po, (p, i) in twin.state["loc"].items() if p == plant and i != idx)
    free = twin.free_slots(plant, idx_to_date(idx))
    plan = [{"seq": n, "tool": "mes.reschedule", "args": {"production_order_id": po, "new_date": day}}
            for n, po in enumerate(others[: free + 1])]
    res = twin.apply(plan)
    assert all(r["ok"] for r in res[:free])
    assert res[free]["ok"] is False and "no free slot" in res[free]["error"]


def test_twins_are_isolated():
    a, b = Twin("A"), Twin("B")
    dealer = next(iter(a.state["loaners"]))
    co = next(c for c in get_store().customer_orders.values() if c.dealer_id == dealer)
    if a.loaner_pool(dealer) > 0:
        assert a.apply([{"tool": "crm.assign_loaner", "args": {"customer_order_id": co.customer_order_id}}])[0]["ok"]
        assert b.loaner_pool(dealer) == a.loaner_pool(dealer) + 1


def test_write_guard_blocks_noise_and_unconfirmed():
    client = ToolsClient(dry_run=True)
    client.mark("N-1", "noise")
    with pytest.raises(WriteBlocked):
        client.act("N-1", "dealer.notify", {"dealer_id": "D01", "customer_order_ids": ["CO-00001"], "message": "x"})
    with pytest.raises(WriteBlocked):
        client.act("N-1", "escalate", {"reason": "x"})
    client.mark("U-1", "unconfirmed")
    with pytest.raises(WriteBlocked):
        client.act("U-1", "quality.hold_lot", {"lot_id": "LOT-0001"})
    ok, _ = client.act("U-1", "escalate", {"reason": "rumor"})
    assert ok
    with pytest.raises(WriteBlocked):
        client.act("X-1", "escalate", {"reason": "unclassified"})
    assert len(client.calls) == 1
