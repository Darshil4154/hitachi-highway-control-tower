"""Agent World: live isometric map of agents, stages, and sandbox activity."""
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
    st.caption("Isometric live map of the control tower. Named agents, stage pipes, scored-run replay, "
               "and Live Desk / What-if activity. The Streamlit pages stay as they are - this is the 3D twin.")

    data = _refresh_bootstrap()
    live = read_live()

    c1, c2, c3, c4 = st.columns([1.2, 1.2, 1.4, 1])
    mode = c1.radio("Mode", ["Replay scored run", "Live sandbox"], horizontal=True, key="aw_mode")
    events = [e["event_id"] for e in data.get("playlist") or []]
    event = c2.selectbox("Start event", events, index=events.index("E-09") if "E-09" in events else 0,
                         key="aw_event")
    speed = c3.select_slider("Replay speed", options=[0.75, 1.0, 1.5, 2.0, 3.0], value=1.5, key="aw_speed")
    if c4.button("Refresh world data"):
        data = _refresh_bootstrap()
        st.rerun()

    if mode.startswith("Live"):
        st.info("Live mode listens for What-if and Live Incident Desk runs. "
                "Open those pages, run a scenario, then come back - or keep this tab open.")
        if live:
            st.success(f"Latest live pulse: **{live.get('label', 'sandbox')}** · stage `{live.get('stage')}`")
            st.caption(live.get("summary") or live.get("banner") or "")
        else:
            st.caption("No live pulse yet. Run What-if or Live Incident Desk.")
        if st.button("Clear live pulse"):
            clear_live()
            st.rerun()
        src = "/app/static/agent_world/index.html?mode=live&speed=1"
    else:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Events in playlist", len(data.get("playlist") or []))
        m2.metric("Agents", len(data.get("agents") or []))
        m3.metric("Graph nodes", f"{(data.get('graph') or {}).get('nodes') or '—'}")
        m4.metric("Plants on map", len(data.get("plants") or []))
        src = f"/app/static/agent_world/index.html?mode=replay&event={event}&speed={speed}"

    with st.expander("Who is who", expanded=False):
        for a in data.get("agents") or []:
            st.markdown(f"**{a['name']}** · {a['role']}")

    components.iframe(src, height=720, scrolling=False)

    st.caption("Click an avatar card or a building for detail. Beams are stage traffic through the Coordinator.")
