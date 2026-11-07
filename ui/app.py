"""Wacky Wheels Control Tower - Streamlit UI. Reads only traces/ and exports/; never calls the enterprise server.

streamlit run ui/app.py
"""
from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
TRACES = ROOT / "traces"
EXPORTS = ROOT / "exports"
HITL = ROOT / "ui" / "hitl_decisions.json"

CAT = {
    "delay": ("#f59e0b", "Supplier delay"), "outage": ("#ef4444", "Plant outage"),
    "quality": ("#a855f7", "Quality hold"), "noise": ("#64748b", "Noise"),
    "escalated": ("#3b82f6", "Escalated"), "compound": ("#14b8a6", "Compound"),
}
SOURCE_ICON = {"daily digest": "🗞️", "ops chat": "💬", "quality bulletin": "🧪", "news wire": "📰",
               "plant alert": "🚨", "supplier email": "✉️"}
NODE_COLOR = {"Supplier": "#f59e0b", "Shipment": "#fbbf24", "PartLot": "#a855f7", "Part": "#fb923c",
              "Model": "#22c55e", "Plant": "#ef4444", "ProductionOrder": "#3b82f6", "CustomerOrder": "#06b6d4",
              "Customer": "#14b8a6", "Dealer": "#6366f1", "Vehicle": "#8b5cf6", "LoanerPool": "#94a3b8"}
AGENT_COLOR = {"Coordinator": "#e2e8f0", "SupplyChainPlanner": "#f59e0b", "DealerNetwork": "#6366f1",
               "CustomerCareQuality": "#14b8a6", "Verifier": "#22c55e"}

st.set_page_config(page_title="Wacky Wheels Control Tower", page_icon="🗼", layout="wide")

st.markdown("""
<style>
[data-testid="stSidebar"] {background: #0b1220;}
[data-testid="stSidebar"] * {color: #e2e8f0 !important;}
.block-container {padding-top: 1.4rem; padding-bottom: 2rem;}
.kpi {background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 14px 16px; height: 100%;}
.kpi .v {font-size: 1.65rem; font-weight: 700; color: #0f172a; line-height: 1.1;}
.kpi .l {font-size: .78rem; color: #64748b; text-transform: uppercase; letter-spacing: .04em;}
.kpi.good .v {color: #16a34a;}
.badge {display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .72rem; font-weight: 600;
        color: white; letter-spacing: .02em;}
.card {border: 1px solid #e2e8f0; border-radius: 12px; padding: 10px 12px; margin-bottom: 8px; background: #fff;}
.card.sel {border: 2px solid #0f172a; box-shadow: 0 2px 10px rgba(15,23,42,.08);}
.card .meta {font-size: .74rem; color: #64748b;}
.card .sum {font-size: .84rem; color: #0f172a; margin-top: 4px;}
.msg {background: #f8fafc; border-left: 4px solid #94a3b8; padding: 12px 16px; border-radius: 8px;
      font-size: .98rem; line-height: 1.6; white-space: pre-wrap;}
mark.ev {background: #fef3c7; padding: 0 2px; border-radius: 3px;}
.chip {display: inline-block; background: #eef2ff; color: #3730a3; border: 1px solid #c7d2fe; border-radius: 999px;
       padding: 1px 9px; font-size: .78rem; margin: 2px 4px 2px 0; font-family: ui-monospace, monospace;}
.why {border-radius: 12px; padding: 16px 18px; color: #0f172a;}
.check {font-size: .86rem; margin: 2px 0;}
.path {font-family: ui-monospace, monospace; font-size: .8rem; background: #0b1220; color: #e2e8f0;
       padding: 10px 12px; border-radius: 8px; overflow-x: auto; white-space: nowrap;}
.small {font-size: .8rem; color: #64748b;}
</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------------------------------- data
@st.cache_data(show_spinner=False)
def load_traces(mtime: float) -> dict[str, dict]:
    out = {}
    for p in sorted(TRACES.glob("E-*.json")):
        out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


@st.cache_data(show_spinner=False)
def load_summary(mtime: float) -> dict:
    p = TRACES / "run_summary.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def traces_mtime() -> float:
    files = list(TRACES.glob("*.json"))
    return max((f.stat().st_mtime for f in files), default=0.0)


def badge(cat: str) -> str:
    color, label = CAT.get(cat, ("#334155", cat))
    return f'<span class="badge" style="background:{color}">{label}</span>'


def short_summary(t: dict) -> str:
    cat = t["ui_category"]
    if cat == "noise":
        return "Not operational - no action taken."
    if cat == "escalated":
        return "Sent to human review: " + (t["escalation"].get("reason") or "")[:90]
    parts = []
    for i in t["incidents"]:
        d, a = i.get("disruption") or {}, i.get("affected") or {}
        if i["type"] == "quality_hold":
            parts.append(f"{d.get('lot_id')} hold · {len(a.get('vehicles_unsold', []))} stop-sale · "
                         f"{len(a.get('customers', []))} owners")
        else:
            parts.append(f"{d.get('plant_id')} · {len(a.get('production_orders', []))} orders moved · "
                         f"{len(a.get('dealers', []))} dealers")
    return " | ".join(parts)


def load_hitl() -> dict:
    return json.loads(HITL.read_text(encoding="utf-8")) if HITL.exists() else {}


def save_hitl(d: dict) -> None:
    HITL.write_text(json.dumps(d, indent=2), encoding="utf-8")


traces = load_traces(traces_mtime())
summary = load_summary(traces_mtime())

# ------------------------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("## 🗼 Control Tower")
    st.markdown("<span class='small'>Wacky Wheels Co. · operations</span>", unsafe_allow_html=True)
    page = st.radio("View", ["Event operations", "Human review inbox", "Audit trail", "Knowledge graph"],
                    label_visibility="collapsed")
    st.divider()
    if summary:
        st.markdown(f"**Run mode:** {summary.get('mode', '?')}")
        st.markdown(f"**Model:** `{summary.get('llm_model', '?')}`")
        st.markdown("**Interpretation switches**")
        for k, v in (summary.get("config_snapshot") or {}).items():
            if k not in ("LLM_MODEL", "FUZZY_THRESHOLD"):
                st.markdown(f"<span class='small'>{k} = <b>{v}</b></span>", unsafe_allow_html=True)
    st.divider()
    st.markdown("<span class='small'>Personas: Production Planner · Dealer Relations · Customer Care · "
                "Quality Engineer · Auditor</span>", unsafe_allow_html=True)

if not traces:
    st.title("Wacky Wheels Control Tower")
    st.info("No traces yet. Run the agents first:\n\n`python -m control_tower.run --dry-run` (twin only) or start "
            "the enterprise server and run `python -m control_tower.run`.")
    st.stop()

order = sorted(traces, key=lambda e: traces[e]["event"]["received_at"] or e)


# ------------------------------------------------------------------------------------------- KPIs
def kpis() -> None:
    tot = summary.get("totals", {})
    incidents = sum(len(t["incidents"]) for t in traces.values() if t["ui_category"] not in ("noise", "escalated"))
    escal = sum(1 for t in traces.values() if t["ui_category"] == "escalated")
    noise = sum(1 for t in traces.values() if t["ui_category"] == "noise")
    writes = sum(t["metrics"]["writes"] for t in traces.values())
    failed = sum(t["metrics"]["failed"] for t in traces.values())
    model = summary.get("llm_model") or next(iter(traces.values()))["metrics"]["llm_model"]
    cells = [("Events", len(traces), ""), ("Incidents handled", incidents, ""), ("Escalations", escal, ""),
             ("Noise filtered", noise, ""), ("Write actions", writes, ""),
             ("Failed calls", failed, "good" if failed == 0 else ""), ("Model", model.replace("-instruct", ""), "")]
    cols = st.columns([1, 1.2, 1, 1, 1, 1, 1.5])
    for c, (label, value, cls) in zip(cols, cells):
        size = "font-size:1.05rem;padding-top:.45rem" if label == "Model" else ""
        c.markdown(f"<div class='kpi {cls}'><div class='l'>{label}</div><div class='v' style='{size}'>{value}</div>"
                   f"</div>", unsafe_allow_html=True)
    if tot.get("prompt_tokens") is not None:
        st.markdown(f"<div class='small' style='margin-top:6px'>LLM: {tot.get('llm_calls', 0)} calls this run "
                    f"(cached responses are free) · {tot.get('prompt_tokens', 0):,} prompt / "
                    f"{tot.get('completion_tokens', 0):,} completion tokens · {tot.get('reads', 0)} free read checks"
                    f"</div>", unsafe_allow_html=True)


# ------------------------------------------------------------------------------------------- graph
def graph_html(item: dict, max_extra: int = 70) -> str:
    from pyvis.network import Network

    gp = item.get("graph_path") or {}
    chain = [tuple(e) for e in gp.get("chain", [])]
    edges = [tuple(e) for e in gp.get("edges", [])]
    chain_set = set(chain)
    rest = [e for e in edges if e not in chain_set]
    shown = chain + rest[:max_extra]
    net = Network(height="470px", width="100%", directed=True, bgcolor="#0b1220", font_color="#e2e8f0",
                  cdn_resources="in_line")
    net.barnes_hut(gravity=-6000, spring_length=110)
    hot = {n for e in chain for n in (e[0], e[2])}
    for e in shown:
        for n in (e[0], e[2]):
            if n not in net.get_nodes():
                kind, _, key = n.partition(":")
                net.add_node(n, label=key, title=f"{kind}: {key}", color=NODE_COLOR.get(kind, "#cbd5e1"),
                             size=24 if n in hot else 12, borderWidth=3 if n in hot else 1,
                             font={"size": 15 if n in hot else 10, "color": "#e2e8f0"})
        net.add_edge(e[0], e[2], label=e[1] if e in chain_set else "", title=e[1],
                     color="#facc15" if e in chain_set else "#334155", width=3.5 if e in chain_set else 1)
    return net.generate_html(notebook=False)


def legend() -> str:
    return " ".join(f"<span class='chip' style='background:{c};color:white;border-color:{c}'>{k}</span>"
                    for k, c in NODE_COLOR.items())


# ------------------------------------------------------------------------------------------- heatmap
def heatmap(t: dict) -> None:
    sch = t.get("schedule")
    if not sch:
        st.caption("No schedule change for this event.")
        return
    plants = sch["plants"]
    show = [p for p in plants if p in set(sch["touched_plants"]) | set(sch["transfer_targets"])] or plants
    days = list(next(iter(sch["before"].values())).keys())
    cols = st.columns(2)
    for col, key, title in ((cols[0], "before", "Before"), (cols[1], "after", "After")):
        z = [[sch[key][p][d] for d in days] for p in show]
        cap = [[sch["capacity"][p]] * len(days) for p in show]
        text = [[f"{z[i][j]}/{cap[i][j]}" for j in range(len(days))] for i in range(len(show))]
        fig = go.Figure(go.Heatmap(z=z, x=[d[5:] for d in days], y=show, text=text, texttemplate="%{text}",
                                   zmin=0, zmax=max(sch["capacity"].values()),
                                   colorscale=[[0, "#f1f5f9"], [0.6, "#93c5fd"], [1, "#1e3a8a"]], showscale=False,
                                   hovertemplate="%{y} %{x}: %{text} slots<extra></extra>"))
        blocked = []
        for it in t["incidents"]:
            d = it.get("disruption") or {}
            f, to = d.get("blocked_from"), d.get("blocked_to_incl") or d.get("blocked_until_excl")
            if f and d.get("plant_id") in show:
                for j, day in enumerate(days):
                    inside = f <= day <= to if d.get("blocked_to_incl") else f <= day < to
                    if inside:
                        blocked.append((show.index(d["plant_id"]), j))
        for i, j in blocked:
            fig.add_shape(type="rect", x0=j - .5, x1=j + .5, y0=i - .5, y1=i + .5,
                          line=dict(color="#ef4444", width=2.5))
        fig.update_layout(title=f"{title} (slots used / capacity)", height=110 + 46 * len(show),
                          margin=dict(l=10, r=10, t=40, b=10), xaxis=dict(tickangle=-60, tickfont=dict(size=9)))
        col.plotly_chart(fig, width="stretch", key=f"hm-{t['event']['event_id']}-{key}")
    st.caption("Red outline = blocked by the disruption. Only the disrupted plant and transfer targets are shown.")


# ------------------------------------------------------------------------------------------- detail
def highlight(text: str, t: dict) -> str:
    out = html.escape(text)
    quotes = sorted({i.get("evidence_quote") or "" for i in t["incidents"]}, key=len, reverse=True)
    for q in quotes:
        if q and q != text and html.escape(q) in out:
            out = out.replace(html.escape(q), f"<mark class='ev'>{html.escape(q)}</mark>", 1)
    return out


def why_card(t: dict) -> None:
    cat = t["ui_category"]
    c = t["classification"]
    if cat == "noise":
        st.markdown(f"""<div class='why' style='background:#f1f5f9;border:1px solid #cbd5e1'>
            <div style='font-size:1.05rem;font-weight:700'>🛑 Ignored - not operational (handbook rule 7)</div>
            <div style='margin-top:6px'>{html.escape(c.get('gate_reason') or c.get('rationale') or '')}</div>
            <div class='small' style='margin-top:8px'>LLM category <b>{c['category']}</b> (confidence
            {c.get('confidence')}), confirmed by the deterministic gate. The tool client hard-blocks every write for
            noise events, so <b>zero calls</b> were made.</div></div>""", unsafe_allow_html=True)
    else:
        e = t["escalation"]
        miss = "".join(f"<span class='chip' style='background:#dbeafe;border-color:#93c5fd;color:#1e40af'>{html.escape(m)}"
                       f"</span>" for m in e.get("missing_fields", []))
        hedges = ", ".join(c.get("hedges") or []) or "none"
        st.markdown(f"""<div class='why' style='background:#eff6ff;border:1px solid #93c5fd'>
            <div style='font-size:1.05rem;font-weight:700'>🙋 Escalated to a human - no operational change
            (handbook rule 8)</div>
            <div style='margin-top:6px'>{html.escape(e.get('reason') or '')}</div>
            <div style='margin-top:8px'><b>Missing information:</b> {miss or '-'}</div>
            <div class='small' style='margin-top:6px'>Hedge words detected: {html.escape(hedges)} · exactly one
            <code>escalate</code> call, writes blocked by the tool client.</div></div>""", unsafe_allow_html=True)


def incident_view(t: dict, it: dict) -> None:
    d = it.get("disruption") or {}
    a = it.get("affected") or {}
    rows = [{"field": x["field"].replace("_phrase", "").replace("_mention", ""), "phrase": x["phrase"],
             "resolved": str(x["resolved"] or "—"), "method": x["method"]} for x in it.get("extracted", [])]
    c1, c2 = st.columns([1.1, 1])
    with c1:
        st.markdown("**Extraction → resolution** <span class='small'>(LLM copies phrases; code resolves)</span>",
                    unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=min(38 * len(rows) + 40, 300))
        vals = it.get("validation", [])
        if vals:
            st.markdown("**Validation**")
            for v in vals:
                st.markdown(f"<div class='check'>{'✅' if v['ok'] else '❌'} {html.escape(v['check'])}</div>",
                            unsafe_allow_html=True)
    with c2:
        st.markdown("**Disruption**")
        if it["type"] == "quality_hold":
            st.markdown(f"Lot **{d.get('lot_id')}** · {d.get('part_id')} from {d.get('supplier_id')} at "
                        f"**{d.get('plant_id')}** · built {d.get('window_from')} → {d.get('window_to')}  \n"
                        f"<span class='small'>Lot match: {d.get('lot_match')}</span>", unsafe_allow_html=True)
        elif it["type"] == "supplier_delay":
            st.markdown(f"Shipment **{d.get('shipment_id')}** of **{d.get('part_id')}** from {d.get('supplier_id')} "
                        f"to **{d.get('plant_id')}**  \nBlocked **{d.get('blocked_from')} → "
                        f"{d.get('blocked_until_excl')} (excl.)** for {', '.join(d.get('models_blocked') or [])}  \n"
                        f"Same-plant restart: **{d.get('restart')}**")
        else:
            st.markdown(f"Plant **{d.get('plant_id')}** dark **{d.get('blocked_from')} → {d.get('blocked_to_incl')} "
                        f"(incl.)**, all models  \nRestart: **{d.get('restart')}**")
        m = st.columns(3)
        if it["type"] == "quality_hold":
            m[0].metric("Vehicles", len(a.get("vehicles_unsold", [])) + len(a.get("vehicles_sold", [])))
            m[1].metric("Stop-sale (unsold)", len(a.get("vehicles_unsold", [])))
            m[2].metric("Owners contacted", len(a.get("customers", [])))
        else:
            m[0].metric("Production orders", len(a.get("production_orders", [])))
            m[1].metric("Customer orders", len(a.get("customer_orders", [])))
            m[2].metric("Dealers", len(a.get("dealers", [])))
        exc = it.get("excluded", [])
        if exc:
            with st.expander(f"Excluded on purpose ({len(exc)}) - rule 10"):
                st.dataframe(pd.DataFrame(exc), hide_index=True, width="stretch")

    st.markdown("**Graph path** <span class='small'>(evidence chain; yellow = cited path, full subgraph sampled)"
                "</span>", unsafe_allow_html=True)
    st.markdown(f"<div class='path'>{html.escape(it['graph_path'].get('text') or '')}</div>", unsafe_allow_html=True)
    if it["graph_path"].get("edges"):
        st.iframe(graph_html(it), height=490)
        st.markdown(legend(), unsafe_allow_html=True)

    rs = it["decisions"].get("reschedule", [])
    if rs:
        st.markdown("**Rescheduling decisions** (rule 3)")
        df = pd.DataFrame([{"order": r["po"], "model": r["model"], "from": r["from"], "to": r["to"] or "-",
                            "kind": {"same_plant": "same plant", "transfer": "transfer",
                                     "no_slot": "no slot → escalate"}[r["kind"]],
                            "rule": r["rule_id"], "reason": r["reason"]} for r in rs])
        st.dataframe(df, hide_index=True, width="stretch")
    ln = it["decisions"].get("loaners", [])
    if ln:
        assigned = [x for x in ln if x["decision"] == "assigned"]
        skipped = [x for x in ln if x["decision"] == "skipped"]
        st.markdown(f"**Loaner ranking** (rule 5) - {len(assigned)} assigned, {len(skipped)} skipped (pool "
                    f"exhausted), {len(ln) - len(assigned) - len(skipped)} Standard tier")
        df = pd.DataFrame([{"decision": {"assigned": "✅ assigned", "skipped": "⏭ skipped",
                                         "not_eligible": "— standard"}[x["decision"]], "dealer": x["dealer"],
                            "customer order": x["co"], "tier": x["tier"], "promised": x["promised"],
                            "rank": str(x["rank"] or ""), "reason": x["reason"]} for x in ln])
        flt = st.segmented_control("Show", ["Platinum/Gold", "All"], default="Platinum/Gold",
                                   key=f"ln-{it['incident_id']}")
        if flt != "All":
            df = df[df["decision"] != "— standard"]
        st.dataframe(df, hide_index=True, width="stretch", height=260)


def actions_view(t: dict) -> None:
    plan = {a["seq"]: a for a in t["plan"]}
    rows = []
    for a in t["actions"]:
        p = plan.get(a["seq"], {}) if a["seq"] else {}
        args = a["args"]
        target = (args.get("production_order_id") or args.get("dealer_id") or args.get("customer_order_id")
                  or args.get("customer_id") or args.get("lot_id") or args.get("plant_id") or "")
        extra = ""
        if a["tool"] in ("mes.reschedule", "mes.transfer"):
            extra = f"→ {args.get('to_plant_id', '')} {args['new_date']}".replace("  ", " ")
        elif a["tool"] == "dealer.notify":
            extra = f"{len(args['customer_order_ids'])} orders"
        elif a["tool"] == "dealer.stop_sale":
            extra = f"{len(args['vins'])} VINs"
        elif a["tool"] == "mes.get_schedule":
            extra = args["date"]
        rows.append({"ok": "✅" if a["ok"] else "❌", "seq": str(a["seq"] or ""), "agent": a["agent"], "tool": a["tool"],
                     "kind": a["kind"], "target": f"{target} {extra}".strip(), "rule": p.get("rule_id", ""),
                     "reason": p.get("reason") or (args.get("reason") or "read-only check")})
    if not rows:
        st.markdown("<div class='small'>No tool calls for this event - by design.</div>", unsafe_allow_html=True)
        return
    df = pd.DataFrame(rows)
    counts = df[df["kind"] != "read"].groupby("tool").size().to_dict()
    st.markdown(" ".join(f"<span class='chip'>{k} × {v}</span>" for k, v in counts.items()), unsafe_allow_html=True)
    st.dataframe(df, hide_index=True, width="stretch", height=330)


def verifier_view(t: dict) -> None:
    v = t["verifier"]
    groups = [("Plan checks (before execution)", v.get("plan_checks", [])),
              ("Digital-twin world checks", v.get("world_checks", [])),
              ("Read-back on the live server", v.get("readback_checks", []))]
    cols = st.columns(3)
    for col, (title, checks) in zip(cols, groups):
        with col:
            st.markdown(f"**{title}**")
            if not checks:
                st.markdown("<div class='small'>Not applicable.</div>", unsafe_allow_html=True)
            for c in checks:
                icon = "✅" if c["ok"] else ("⚠️" if not c.get("blocking", True) else "❌")
                detail = f" <span class='small'>{html.escape(c.get('detail') or '')}</span>" if c.get("detail") else ""
                st.markdown(f"<div class='check'>{icon} {html.escape(c['name'])}{detail}</div>", unsafe_allow_html=True)


def event_detail(eid: str) -> None:
    t = traces[eid]
    e, cat = t["event"], t["ui_category"]
    st.markdown(f"### {SOURCE_ICON.get(e['source'], '📨')} {eid} &nbsp; {badge(cat)}", unsafe_allow_html=True)
    st.markdown(f"<span class='small'>{e['source']} · received {e['received_at']} · LLM "
                f"<code>{t['classification']['llm_model']}</code>"
                f"{' (rule fallback)' if t['classification']['llm_fallback'] else ''} · gate "
                f"<b>{t['classification']['gate']}</b></span>", unsafe_allow_html=True)
    st.markdown(f"<div class='msg'>{highlight(e['text'], t)}</div>", unsafe_allow_html=True)
    chips = "".join(f"<span class='chip'>{html.escape(m)}</span>" for m in e.get("mentions", []))
    if chips:
        st.markdown(f"<div style='margin-top:6px'><span class='small'>Resolved entities:</span> {chips}</div>",
                    unsafe_allow_html=True)
    st.markdown(f"<div style='margin:12px 0 6px 0;padding:10px 14px;background:#f0fdf4;border:1px solid #bbf7d0;"
                f"border-radius:10px'><b>Summary.</b> {html.escape(t['summary'])}</div>", unsafe_allow_html=True)

    if cat in ("noise", "escalated"):
        why_card(t)
        if t["incidents"] and any(i.get("extracted") for i in t["incidents"]):
            with st.expander("What the extractor found"):
                for it in t["incidents"]:
                    st.dataframe(pd.DataFrame(it["extracted"]), hide_index=True, width="stretch")
        st.markdown("#### Action log")
        actions_view(t)
        return

    tabs = st.tabs(["Incidents & graph", "Schedule before / after", "Action log", "Verifier"])
    with tabs[0]:
        if len(t["incidents"]) > 1:
            sr = t.get("shared_resources", {})
            st.info(f"**Compound event - {len(t['incidents'])} incidents handled in one plan.** "
                    f"{sr.get('slot_ledger_note', '')} {sr.get('loaner_ledger_note', '')}")
            itabs = st.tabs([f"{i['incident_id']} · {i['type'].replace('_', ' ')}" for i in t["incidents"]])
            for tab, it in zip(itabs, t["incidents"]):
                with tab:
                    incident_view(t, it)
        else:
            incident_view(t, t["incidents"][0])
    with tabs[1]:
        heatmap(t)
    with tabs[2]:
        actions_view(t)
    with tabs[3]:
        verifier_view(t)


def feed(visible: list[str], selected: str | None) -> str | None:
    cats = ["all"] + [c for c in CAT if any(traces[e]["ui_category"] == c for e in visible)]
    pick = st.pills("Filter", cats, default="all", key="feed-filter", label_visibility="collapsed")
    choice = None
    for eid in visible:
        t = traces[eid]
        if pick and pick != "all" and t["ui_category"] != pick:
            continue
        e = t["event"]
        sel = " sel" if eid == selected else ""
        st.markdown(f"<div class='card{sel}'><div class='meta'>{SOURCE_ICON.get(e['source'], '📨')} {eid} · "
                    f"{e['source']} · {e['received_at'][11:16]} &nbsp; {badge(t['ui_category'])}</div>"
                    f"<div class='sum'>{html.escape(short_summary(t))}</div></div>", unsafe_allow_html=True)
        if st.button("Open", key=f"open-{eid}", width="stretch", type="secondary"):
            choice = eid
    return choice


# ------------------------------------------------------------------------------------------- pages
if page == "Event operations":
    st.markdown("## Wacky Wheels Control Tower")
    st.markdown("<span class='small'>Event-driven multi-agent operations: Coordinator · Supply Chain Planner · "
                "Dealer Network · Customer Care & Quality · Verifier. LLM reads, code decides.</span>",
                unsafe_allow_html=True)
    kpis()
    st.write("")
    if "selected" not in st.session_state:
        st.session_state.selected = order[0]
    if "visible" not in st.session_state:
        st.session_state.visible = len(order)
    left, right = st.columns([1, 2.6], gap="large")
    with left:
        h1, h2 = st.columns([1.2, 1])
        h1.markdown("#### Event feed")
        replay = h2.button("▶ Replay run", width="stretch")
        slot = st.empty()
        if replay:
            for n in range(1, len(order) + 1):
                with slot.container():
                    st.markdown(f"<div class='small'>Replaying… {n}/{len(order)} events arrived</div>",
                                unsafe_allow_html=True)
                    for eid in order[:n][::-1][:6]:
                        t = traces[eid]
                        st.markdown(f"<div class='card'><div class='meta'>{eid} · {t['event']['source']} · "
                                    f"{t['event']['received_at'][11:16]} {badge(t['ui_category'])}</div>"
                                    f"<div class='sum'>{html.escape(short_summary(t))}</div></div>",
                                    unsafe_allow_html=True)
                st.session_state.selected = order[n - 1]
                time.sleep(1)
            slot.empty()
            st.rerun()
        with slot.container():
            picked = feed(order, st.session_state.selected)
            if picked:
                st.session_state.selected = picked
                st.rerun()
    with right:
        event_detail(st.session_state.selected)

elif page == "Human review inbox":
    st.markdown("## Human-in-the-loop inbox")
    st.markdown("<span class='small'>Events the agents refused to act on. Decisions are stored locally in "
                "<code>ui/hitl_decisions.json</code>; the enterprise server is never called from here.</span>",
                unsafe_allow_html=True)
    decisions = load_hitl()
    esc = [e for e in order if traces[e]["escalation"].get("escalated")]
    if not esc:
        st.success("Inbox empty - nothing needs a human right now.")
    for eid in esc:
        t = traces[eid]
        dec = decisions.get(eid)
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(f"**{eid}** · {t['event']['source']} · {t['event']['received_at']} "
                            f"{badge(t['ui_category'])}", unsafe_allow_html=True)
                st.markdown(f"<div class='msg'>{html.escape(t['event']['text'])}</div>", unsafe_allow_html=True)
                miss = "".join(f"<span class='chip'>{html.escape(m)}</span>"
                               for m in t["escalation"].get("missing_fields", []))
                st.markdown(f"**Missing information:** {miss or '-'}", unsafe_allow_html=True)
                st.markdown(f"<span class='small'>Agent reason: {html.escape(t['escalation'].get('reason', ''))}"
                            f"</span>", unsafe_allow_html=True)
            with c2:
                if dec:
                    st.markdown(f"**{dec['decision'].title()}** ✔︎  \n<span class='small'>{dec['at']}</span>",
                                unsafe_allow_html=True)
                    if st.button("Reopen", key=f"re-{eid}"):
                        decisions.pop(eid, None)
                        save_hitl(decisions)
                        st.rerun()
                else:
                    note = st.text_input("Note", key=f"note-{eid}", placeholder="e.g. asked supplier rep for details")
                    b1, b2 = st.columns(2)
                    for b, label in ((b1, "approved"), (b2, "dismissed")):
                        if b.button("Approve" if label == "approved" else "Dismiss", key=f"{label}-{eid}",
                                    type="primary" if label == "approved" else "secondary",
                                    width="stretch"):
                            decisions[eid] = {"decision": label, "note": note,
                                              "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                            save_hitl(decisions)
                            st.rerun()

elif page == "Audit trail":
    st.markdown("## Audit trail")
    p = TRACES / "audit_log.csv"
    if not p.exists():
        st.warning("traces/audit_log.csv not found - run the agents first.")
        st.stop()
    df = pd.read_csv(p, dtype=str).fillna("")
    c = st.columns(4)
    ev = c[0].multiselect("Event", sorted(df["event_id"].unique()))
    tool = c[1].multiselect("Tool", sorted(df["tool"].unique()))
    agent = c[2].multiselect("Agent", sorted(df["agent"].unique()))
    rule = c[3].multiselect("Rule", sorted(x for x in df["rule_id"].unique() if x))
    q = st.text_input("Search target / reason", placeholder="e.g. D12, PO-0436, LOT-0191")
    f = df
    for col, sel in (("event_id", ev), ("tool", tool), ("agent", agent), ("rule_id", rule)):
        if sel:
            f = f[f[col].isin(sel)]
    if q:
        f = f[f["target"].str.contains(q, case=False, regex=False) | f["reason"].str.contains(q, case=False,
                                                                                               regex=False)]
    m = st.columns(4)
    m[0].metric("Rows", len(f))
    m[1].metric("Writes", int((f["kind"] == "write").sum()))
    m[2].metric("Reads (free)", int((f["kind"] == "read").sum()))
    m[3].metric("Failed", int((f["ok"] != "True").sum()))
    st.dataframe(f, hide_index=True, width="stretch", height=560)
    st.download_button("⬇ Download CSV", f.to_csv(index=False).encode("utf-8"), "audit_log_filtered.csv", "text/csv")
    sc = ROOT / "eval" / "self_check_report.md"
    if sc.exists():
        with st.expander("Self-check report (independent replay of the action log)"):
            st.markdown(sc.read_text(encoding="utf-8"))

else:
    st.markdown("## Knowledge graph & ontology")
    stats_p = EXPORTS / "graph_stats.json"
    if (EXPORTS / "ontology_schema.png").exists():
        st.image(str(EXPORTS / "ontology_schema.png"), width="stretch")
    if stats_p.exists():
        stats = json.loads(stats_p.read_text(encoding="utf-8"))
        m = st.columns(3)
        m[0].metric("Nodes", f"{stats['nodes_total']:,}")
        m[1].metric("Edges", f"{stats['edges_total']:,}")
        m[2].metric("Node types", len(stats["nodes_by_type"]))
        c1, c2 = st.columns(2)
        for col, key, title in ((c1, "nodes_by_type", "Nodes by type"), (c2, "edges_by_type", "Edges by type")):
            s = pd.Series(stats[key]).sort_values()
            fig = go.Figure(go.Bar(x=s.values, y=s.index, orientation="h", marker_color="#3b82f6"))
            fig.update_layout(title=title, height=420, margin=dict(l=10, r=10, t=40, b=10))
            col.plotly_chart(fig, width="stretch")
    d = st.columns(3)
    for col, name, mime in ((d[0], "ontology.ttl", "text/turtle"), (d[1], "knowledge_graph.graphml", "application/xml"),
                            (d[2], "graph_stats.json", "application/json")):
        p = EXPORTS / name
        if p.exists():
            col.download_button(f"⬇ {name} ({p.stat().st_size / 1e6:.1f} MB)", p.read_bytes(), name, mime,
                                width="stretch")
    st.markdown("**Edge vocabulary** (identical in code, traces, UI and diagram)")
    st.markdown(re.sub(r"\s+", " ", " ".join(
        f"<span class='chip'>{e}</span>" for e in ["SUPPLIES", "SENT_BY", "DELIVERS", "RECEIVED_AT", "USED_IN",
                                                   "CAN_BUILD", "SCHEDULED_AT", "BUILDS", "FULFILLS", "SOLD_THROUGH",
                                                   "ORDERED_BY", "LOT_OF", "LOT_FROM", "INSTALLED_AT", "BUILT_FROM",
                                                   "AT_DEALER", "OWNED_BY", "HAS_POOL", "REFERS_TO", "MENTIONS",
                                                   "AFFECTS"])), unsafe_allow_html=True)
