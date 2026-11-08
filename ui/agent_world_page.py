"""Agent World: always-on isometric map that also reacts to What-if / Desk."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from control_tower.agent_world import clear_live, read_live, world_bootstrap

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "ui" / "static" / "agent_world"
BOOT = STATIC / "bootstrap.json"


def _refresh_bootstrap() -> dict:
    data = world_bootstrap()
    STATIC.mkdir(parents=True, exist_ok=True)
    BOOT.write_text(json.dumps(data), encoding="utf-8")
    return data


def page_agent_world() -> None:
    st.markdown("## Agent World")
    st.caption("Always-on isometric twin of the control tower. Named agents replay the scored run, "
               "and the map interrupts for Live Incident Desk / What-if pulses. "
               "Click a worker or plant node for detail.")

    data = _refresh_bootstrap()
    live = read_live()

    c1, c2, c3, c4 = st.columns([1.3, 1.2, 1.3, 1])
    ambient = c1.checkbox("Ambient scored-run replay", value=True, key="aw_ambient",
                          help="When on, the world cycles the 15 events. Live Desk/What-if always wins.")
    events = [e["event_id"] for e in data.get("playlist") or []]
    event = c2.selectbox("Replay start", events,
                         index=events.index("E-09") if "E-09" in events else 0, key="aw_event")
    speed = c3.select_slider("Replay speed", options=[0.75, 1.0, 1.5, 2.0, 3.0], value=1.5, key="aw_speed")
    if c4.button("Refresh world data"):
        data = _refresh_bootstrap()
        st.rerun()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Events in playlist", len(data.get("playlist") or []))
    m2.metric("Agents", len(data.get("agents") or []))
    m3.metric("Graph nodes", f"{(data.get('graph') or {}).get('nodes') or '—'}")
    m4.metric("Plants on map", len(data.get("plants") or []))

    if live:
        st.success(f"Live pulse ready: **{live.get('label', 'sandbox')}** · stage `{live.get('stage')}` "
                   f"(the world picks this up automatically)")
        st.caption(live.get("summary") or live.get("banner") or "")
        if st.button("Clear live pulse"):
            clear_live()
            st.rerun()
    else:
        st.info("Always listening for What-if and Live Incident Desk. "
                "Run either page - keep Agent World open (or reopen it) to see the pulse.")

    with st.expander("Who is who", expanded=False):
        for a in data.get("agents") or []:
            st.markdown(f"**{a['name']}** · {a['role']}")

    mode = "always" if ambient else "live"
    src = f"/app/static/agent_world/index.html?mode={mode}&event={event}&speed={speed}"
    components.iframe(src, height=720, scrolling=False)

    st.caption("Click a worker figure, building, plant node, or avatar card. "
               "Live sandbox pulses override ambient replay for a few seconds, then replay resumes.")
