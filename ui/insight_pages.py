"""What-if, operations health, and the daily briefing. Health and the briefing read traces only."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from datetime import date, timedelta

from control_tower.data_loader import TODAY
from control_tower.insights import STAGE_LABEL, STAGES, build_briefing, health_from_traces, to_markdown, to_pdf
from control_tower.whatif import BANNER, catalogs, comparison_rows, simulate

_KIND = [("Plant outage", "plant_outage"), ("Supplier delay", "supplier_delay"), ("Quality hold", "quality_hold")]


def _options(rows: list[dict], extra: str | None = None) -> list[dict]:
    out = [{"id": "", "label": extra}] if extra else []
    return out + rows


def _select(label: str, rows: list[dict], key: str) -> dict | None:
    labels = [r["label"] for r in rows]
    if not labels:
        st.caption(f"Nothing to choose for {label.lower()}.")
        return None
    current = st.session_state.get(key)
    if current not in labels:
        st.session_state[key] = labels[0]
    choice = st.selectbox(label, labels, key=key)
    return rows[labels.index(choice)]


def _scenario_form(prefix: str, cat: dict) -> dict | None:
    kind_labels = [n for n, _ in _KIND]
    kind_key = f"{prefix}_kind"
    if st.session_state.get(kind_key) not in kind_labels:
        st.session_state[kind_key] = kind_labels[0]
    kind_label = st.selectbox("Scenario type", kind_labels, key=kind_key)
    kind = dict(_KIND)[kind_label]
    if kind == "plant_outage":
        today = TODAY.isoformat()
        end_day = (TODAY + timedelta(days=4)).isoformat()
        if f"{prefix}_start" not in st.session_state and today in cat["dates"]:
            st.session_state[f"{prefix}_start"] = today
        if f"{prefix}_end" not in st.session_state and end_day in cat["dates"]:
            st.session_state[f"{prefix}_end"] = end_day
        plant = _select("Plant", cat["plants"], f"{prefix}_plant")
        start = _select("Start", [{"id": d, "label": d} for d in cat["dates"]], f"{prefix}_start")
        end = _select("End", [{"id": d, "label": d} for d in cat["dates"]], f"{prefix}_end")
        if not plant or not start or not end:
            return None
        return {"kind": kind, "plant_id": plant["id"], "start": start["id"], "end": end["id"]}
    if kind == "supplier_delay":
        ship_rows = _options(cat["shipments"], "No shipment — use the fields below")
        if f"{prefix}_ship" not in st.session_state and cat["shipments"]:
            st.session_state[f"{prefix}_ship"] = cat["shipments"][0]["label"]
        ship = _select("Shipment", ship_rows, f"{prefix}_ship")
        if ship and ship["id"]:
            st.caption(f"Part {ship['part_id']} · {ship['plant_id']} · {ship['supplier_id']} · was due {ship['eta']}")
            later = [d for d in cat["dates"] if d > ship["eta"]]
            if later and st.session_state.get(f"{prefix}_new") not in later:
                target = (date.fromisoformat(ship["eta"]) + timedelta(days=7)).isoformat()
                st.session_state[f"{prefix}_new"] = target if target in later else later[0]
            new = _select("New arrival", [{"id": d, "label": d} for d in later], f"{prefix}_new")
            if not new:
                return None
            return {"kind": kind, "shipment_id": ship["id"], "new_eta": new["id"]}
        part = _select("Part", cat["parts"], f"{prefix}_part")
        plant = _select("Plant", cat["plants"], f"{prefix}_plant")
        sup = _select("Supplier", cat["suppliers"], f"{prefix}_sup")
        orig = _select("Original arrival", [{"id": d, "label": d} for d in cat["dates"]], f"{prefix}_orig")
        new = _select("New arrival", [{"id": d, "label": d} for d in cat["dates"]], f"{prefix}_new")
        if not (part and plant and sup and orig and new):
            return None
        return {"kind": kind, "part_id": part["id"], "plant_id": plant["id"], "supplier_id": sup["id"],
                "original_eta": orig["id"], "new_eta": new["id"]}
    plants = _options(cat["plants"], "Any plant")
    parts = _options(cat["parts"], "Any part")
    suppliers = _options(cat["suppliers"], "Any supplier")
    plant = _select("Plant", plants, f"{prefix}_qplant")
    part = _select("Part", parts, f"{prefix}_qpart")
    sup = _select("Supplier", suppliers, f"{prefix}_qsup")
    lots = cat["lots"]
    if plant and plant["id"]:
        lots = [r for r in lots if r["plant_id"] == plant["id"]]
    if part and part["id"]:
        lots = [r for r in lots if r["part_id"] == part["id"]]
    if sup and sup["id"]:
        lots = [r for r in lots if r["supplier_id"] == sup["id"]]
    lot = _select("Lot", lots, f"{prefix}_lot")
    if not lot:
        return None
    if st.session_state.get(f"{prefix}_lot_applied") != lot["id"]:
        st.session_state[f"{prefix}_from"] = lot["window_from"]
        st.session_state[f"{prefix}_to"] = lot["window_to"]
        st.session_state[f"{prefix}_lot_applied"] = lot["id"]
    date_ids = list(cat["dates"])
    for extra in (lot["window_from"], lot["window_to"]):
        if extra not in date_ids:
            date_ids.append(extra)
    date_ids.sort()
    dates = [{"id": d, "label": d} for d in date_ids]
    window_from = _select("Window from", dates, f"{prefix}_from")
    window_to = _select("Window to", dates, f"{prefix}_to")
    return {"kind": kind, "lot_id": lot["id"], "part_id": lot["part_id"], "plant_id": lot["plant_id"],
            "supplier_id": lot["supplier_id"],
            "window_from": (window_from or {}).get("id") or lot["window_from"],
            "window_to": (window_to or {}).get("id") or lot["window_to"]}


def _show_report(report: dict) -> None:
    st.markdown(f"**{BANNER}.** Planned and checked on the twin. Nothing was sent.")
    if not report.get("ok"):
        st.info(report.get("error") or "This scenario could not be planned.")
        return
    st.caption(report.get("summary") or "")
    if report.get("verifier_blocked"):
        detail = "; ".join(report.get("failed_checks") or []) or "The checker blocked the plan."
        st.info(f"Checker blocked this plan. {detail}")
    elif report.get("verifier_ok"):
        st.caption("Checker cleared the plan. Still a simulation, not executed.")
    m = st.columns(4)
    m[0].metric("Affected orders", report.get("affected_orders", 0))
    m[1].metric("Units delayed", report.get("units", 0))
    m[2].metric("Customers", report.get("customers", 0))
    tiers = report.get("tiers") or {}
    m[3].metric("Platinum / Gold", f"{tiers.get('Platinum', 0)} / {tiers.get('Gold', 0)}")
    n = st.columns(3)
    n[0].metric("Dealers to notify", len(report.get("dealers") or []))
    n[1].metric("Loaners needed", report.get("loaners_needed", 0))
    n[2].metric("Loaners available", report.get("loaners_available", 0))
    if report.get("dealers"):
        st.markdown("**Dealers to notify:** " + ", ".join(report["dealers"]))
    if report.get("customer_names"):
        names = report["customer_names"]
        extra = f" and {len(names) - 8} more" if len(names) > 8 else ""
        st.markdown("**Customers:** " + ", ".join(names[:8]) + extra)
    rows = report.get("order_rows") or []
    if rows:
        st.markdown("**Affected orders**")
        st.dataframe(pd.DataFrame(rows).rename(columns={
            "order": "Order", "plant": "Plant", "units": "Units", "build": "Build", "new_build": "New build",
        }), hide_index=True, width="stretch")
    if report.get("transfers"):
        st.markdown("**Transfers**")
        st.dataframe(pd.DataFrame(report["transfers"]).rename(columns={
            "order": "Order", "units": "Units", "from": "From", "to": "To", "date": "Date",
        }), hide_index=True, width="stretch")
    misses = report.get("promise_misses") or []
    st.markdown(f"**Customer orders that would miss their promise:** {len(misses)}")
    if misses:
        st.dataframe(pd.DataFrame(misses).rename(columns={
            "order": "Order", "customer": "Customer", "dealer": "Dealer",
            "promised": "Promised", "arrival": "Would arrive", "build": "Build",
        }), hide_index=True, width="stretch")
    st.markdown("**Graph path**")
    st.text(report.get("graph_path") or "No path.")


def page_whatif() -> None:
    st.markdown("## What-if")
    st.markdown(f"**{BANNER}.** Pick a scenario, run it on the twin, and compare two of them. "
                "The scored planner and checker run. Nothing is sent to a server.")
    cat = catalogs()
    left, right = st.columns(2)
    with left:
        st.markdown("### Scenario A")
        spec_a = _scenario_form("a", cat)
        if st.button("Run A", type="primary"):
            with st.spinner("Planning on the twin"):
                st.session_state.whatif_a = simulate(spec_a or {}, label="A")
        if st.session_state.get("whatif_a"):
            _show_report(st.session_state.whatif_a)
    with right:
        st.markdown("### Scenario B")
        spec_b = _scenario_form("b", cat)
        if st.button("Run B", type="primary"):
            with st.spinner("Planning on the twin"):
                st.session_state.whatif_b = simulate(spec_b or {}, label="B")
        if st.session_state.get("whatif_b"):
            _show_report(st.session_state.whatif_b)
    st.divider()
    st.markdown(f"### Side by side — {BANNER}")
    a, b = st.session_state.get("whatif_a"), st.session_state.get("whatif_b")
    if not a and not b:
        st.caption("Run at least one scenario. The comparison fills in as each side finishes.")
        return
    st.dataframe(pd.DataFrame(comparison_rows(a, b)), hide_index=True, width="stretch")


def page_health(traces: dict) -> None:
    st.markdown("## Operations health")
    st.caption("Read only from traces/. Nothing is re-run from this page.")
    report = health_from_traces(traces)
    rate = report["cache_hit_rate"]
    top = st.columns(4)
    top[0].metric("Events", report["events"])
    top[1].metric("Failed calls", report["failed"])
    top[2].metric("Cache hit rate", "—" if rate is None else f"{rate * 100:.0f}%")
    top[3].metric("Model", ", ".join(report["models"]) or "—")
    more = st.columns(3)
    more[0].metric("Tokens", f"{report['tokens']:,}")
    more[1].metric("Reads", f"{report['reads']:,}")
    more[2].metric("Writes", f"{report['writes']:,}")
    st.markdown("**Time by stage**")
    if report["has_stages"]:
        fig = go.Figure()
        events = [row["event"] for row in report["rows"]]
        for name in STAGES:
            fig.add_bar(name=STAGE_LABEL[name], x=events,
                        y=[row["stages_s"][name] for row in report["rows"]])
        fig.update_layout(barmode="stack", height=420, margin=dict(l=10, r=10, t=10, b=10),
                          yaxis_title="Seconds", legend_title="Stage")
        st.plotly_chart(fig, width="stretch")
        totals = [{"Stage": STAGE_LABEL[name], "Seconds": report["stage_totals"][name]} for name in STAGES]
        st.markdown("**Totals**")
        st.dataframe(pd.DataFrame(totals), hide_index=True, width="stretch")
    else:
        st.caption("These traces have a total runtime and no per-stage split yet. "
                   "Stage bars appear after the next recorded run.")
        fig = go.Figure(go.Bar(x=[row["event"] for row in report["rows"]],
                               y=[row["runtime_s"] for row in report["rows"]], name="Runtime"))
        fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="Seconds")
        st.plotly_chart(fig, width="stretch")
    st.markdown("**Slowest events**")
    slow = pd.DataFrame([{
        "Event": row["event"], "Type": row["type"], "Runtime (s)": row["runtime_s"],
        "Stages (s)": row["stage_sum_s"] if report["has_stages"] else "—",
        "Cache": row["cache"], "Failed": row["failed"], "Model": row["model"],
    } for row in report["slowest"]])
    st.dataframe(slow, hide_index=True, width="stretch")
    if report["failed"] == 0:
        st.caption("Failure count is 0.")


def page_briefing(traces: dict) -> None:
    st.markdown("## Daily briefing")
    st.caption("Generated from the recorded traces. This page does not call the server.")
    briefing = build_briefing(traces)
    md = to_markdown(briefing)
    try:
        pdf = to_pdf(briefing)
    except Exception as exc:
        pdf = b""
        st.caption(f"The PDF could not be built ({exc}). The Markdown note is still available.")
    c1, c2 = st.columns(2)
    c1.download_button("Download Markdown", md, file_name="daily_briefing.md", mime="text/markdown")
    if pdf:
        c2.download_button("Download one-page PDF", pdf, file_name="daily_briefing.pdf", mime="application/pdf")
    st.markdown(md)
