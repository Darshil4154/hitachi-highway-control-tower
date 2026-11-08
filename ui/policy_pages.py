"""Policy Studio, Live Incident Desk and Scenario Lab. Sandbox only: the scored run stays on handbook_v1."""
from __future__ import annotations

import json
import re

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from control_tower import config
from control_tower.policy_model import (
    KNOWN_TIERS, STEP_LIBRARY, SWITCH_OPTIONS, Policy, audit_rows, desk_profile, dump_yaml, history,
    list_policies, load, rollback, save_new_version, set_desk, yaml_diff,
)
from control_tower.sandbox import SCENARIOS, handle_text, preview_impact

_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}


def _draft() -> dict:
    if "policy_draft" not in st.session_state:
        st.session_state.policy_draft = load("handbook_v1").model_dump(mode="json")
        st.session_state.policy_source = "handbook_v1"
    return st.session_state.policy_draft


def _validate(data: dict) -> Policy | None:
    try:
        return Policy.model_validate(data)
    except (ValidationError, ValueError) as e:
        st.error(f"This draft is not a valid policy yet. {e}")
        return None


def _sync_rule_labels(data: dict) -> None:
    tiers = "/".join(data["rules"]["loaner_tiers"])
    n = int(data["rules"]["min_action_kinds"])
    word = _WORDS.get(n, str(n))
    for check in data["verifier"]:
        if check["id"] == "r5_loaners":
            check["name"] = f"R5 loaners: only {tiers}, within pool, priority respected"
        elif check["id"] == "r9_kinds":
            check["name"] = f"R9 at least {word} different kinds of action"
    topics = ", ".join(data["rules"]["noise_topics"])
    prompt = data.get("noise_prompt") or ""
    found = re.search(r"\(([^)]*)\)", prompt, re.S)
    current = re.sub(r"\s+", " ", found.group(1)).strip() if found else ""
    if current != topics and found:
        data["noise_prompt"] = re.sub(r"\([^)]*\)", f"({topics})", prompt, count=1, flags=re.S)


def page_studio() -> None:
    st.markdown("## Policy Studio (manager)")
    st.markdown(
        "handbook_v1 is the **Scored baseline** and cannot be overwritten. "
        "Publish stores a new file under `config/policies/`. "
        "The official run (`python -m control_tower.run`) keeps using handbook_v1 unless `--policy` names a file. "
        "The Live Incident Desk and the Scenario Lab are the only places an edited profile is applied."
    )
    data = _draft()
    names = [p.id for p in list_policies()] or ["handbook_v1"]
    src = st.selectbox("Start from", names, index=names.index(st.session_state.get("policy_source", "handbook_v1"))
                       if st.session_state.get("policy_source", "handbook_v1") in names else 0)
    if st.button("Load this profile into the draft"):
        st.session_state.policy_draft = load(src).model_dump(mode="json")
        st.session_state.policy_source = src
        st.session_state.policy_draft["read_only"] = False
        st.session_state.policy_draft["status"] = "draft"
        st.rerun()
    if data.get("read_only") or data.get("id") == "handbook_v1":
        st.info("You are looking at the scored baseline. Edits stay in this draft until you publish a new version.")

    section = st.radio(
        "Section",
        ["Event types", "Playbooks", "Rules", "Switches", "Verifier", "Preview impact", "Publish"],
        horizontal=True, label_visibility="collapsed", key="policy_section",
    )
    if section == "Event types":
        _event_types(data)
    elif section == "Playbooks":
        _playbooks(data)
    elif section == "Rules":
        _rules(data)
    elif section == "Switches":
        _switches(data)
    elif section == "Verifier":
        _checks(data)
    elif section == "Preview impact":
        _preview(data)
    else:
        _publish(data)


def _event_types(data: dict) -> None:
    types = data["event_types"]
    ids = [t["id"] for t in types]
    pick = st.selectbox("Event type", ids + ["+ new"], key="et_pick")
    if pick == "+ new":
        with st.form("new_type"):
            new_id = st.text_input("Id", placeholder="weather_closure")
            name = st.text_input("Name", placeholder="Weather closure")
            if st.form_submit_button("Add event type") and new_id.strip():
                types.append({
                    "id": new_id.strip(), "name": name.strip() or new_id.strip(),
                    "description": "", "category": "incident", "keywords": new_id.replace("_", " "),
                    "examples": [], "phrase_hint": "", "prompt_clause": None, "required_summary": "",
                    "required_if_absent": None, "required": [], "playbook": list(data["playbooks"])[0],
                    "prompt_rank": 50, "shape": "plant_window", "window_start": "inclusive",
                    "window_end": "inclusive", "date_fields": [], "sanity_left": None, "sanity_right": None,
                    "sanity_allow_equal": True,
                })
                st.rerun()
        return
    et = next(t for t in types if t["id"] == pick)
    with st.form(f"et_{pick}"):
        et_name = st.text_input("Name", et.get("name") or "")
        desc = st.text_area("Description", et.get("description") or "")
        keywords = st.text_input("Keywords (regex)", et.get("keywords") or "")
        category = st.selectbox("Category", ["incident", "noise", "unconfirmed"],
                                 index=["incident", "noise", "unconfirmed"].index(et.get("category") or "incident"))
        playbook = st.selectbox("Playbook", list(data["playbooks"]),
                                 index=list(data["playbooks"]).index(et["playbook"]) if et["playbook"] in data["playbooks"] else 0)
        shape = st.selectbox("Window shape", ["part_window", "plant_window", "lot", "none"],
                              index=["part_window", "plant_window", "lot", "none"].index(et.get("shape") or "none"))
        c1, c2 = st.columns(2)
        w0 = c1.selectbox("Window start", ["inclusive", "exclusive"],
                           index=0 if et.get("window_start", "inclusive") == "inclusive" else 1)
        w1 = c2.selectbox("Window end", ["inclusive", "exclusive"],
                          index=0 if et.get("window_end", "inclusive") == "inclusive" else 1)
        summary = st.text_input("Required-fields summary", et.get("required_summary") or "")
        required = st.text_area("Required fields (JSON list)", json.dumps(et.get("required") or [], indent=2))
        dates = st.text_area("Date fields (JSON list of [phrase, resolved])",
                             json.dumps(et.get("date_fields") or [], indent=2))
        if st.form_submit_button("Save event type into the draft"):
            try:
                et["required"] = json.loads(required or "[]")
                et["date_fields"] = json.loads(dates or "[]")
            except json.JSONDecodeError as e:
                st.error(f"JSON: {e}")
                return
            et.update(name=et_name, description=desc, keywords=keywords, category=category, playbook=playbook,
                      shape=shape, window_start=w0, window_end=w1, required_summary=summary)
            st.success(f"{pick} updated in the draft.")


def _playbooks(data: dict) -> None:
    st.caption("Steps come from the fixed library. Order here is the playbook order; the coordinator still runs "
               "moves, notifications, loaners and quality actions in the existing phase order.")
    name = st.selectbox("Playbook", list(data["playbooks"]), key="pb_name")
    state_key = f"pb_steps_{name}"
    stored = data["playbooks"][name]["steps"]
    if st.session_state.get("pb_loaded") != name:
        st.session_state[state_key] = list(stored)
        st.session_state.pb_loaded = name
    steps = st.session_state.setdefault(state_key, list(stored))
    for i, step in enumerate(list(steps)):
        cols = st.columns([7, 1, 1, 1])
        cols[0].markdown(f"**{i + 1}. `{step}`**  \n{STEP_LIBRARY[step]}")
        if cols[1].button("Up", key=f"pb_up_{name}_{i}", disabled=i == 0):
            steps[i - 1], steps[i] = steps[i], steps[i - 1]
            st.rerun()
        if cols[2].button("Down", key=f"pb_dn_{name}_{i}", disabled=i == len(steps) - 1):
            steps[i + 1], steps[i] = steps[i], steps[i + 1]
            st.rerun()
        if cols[3].button("Remove", key=f"pb_rm_{name}_{i}"):
            steps.pop(i)
            st.rerun()
    choices = [s for s in STEP_LIBRARY if s not in steps]
    add = st.selectbox("Add a step", ["—"] + choices, key=f"pb_add_{name}")
    if st.button("Add step", disabled=add == "—"):
        steps.append(add)
        st.rerun()
    if st.button("Save playbook into the draft"):
        if not steps:
            st.error("A playbook needs at least one step.")
        else:
            data["playbooks"][name] = {"steps": list(steps)}
            st.success(f"{name} saved into the draft.")


def _rules(data: dict) -> None:
    rules = data["rules"]
    with st.form("rules"):
        tiers = st.multiselect("Loaner tiers", list(KNOWN_TIERS), default=[t for t in rules["loaner_tiers"] if t in KNOWN_TIERS])
        priority = st.multiselect("Priority order (first is served first)", list(KNOWN_TIERS),
                                   default=[t for t in rules["tier_priority"] if t in KNOWN_TIERS])
        kinds = st.number_input("Minimum distinct action kinds (R9)", min_value=1, max_value=7,
                                 value=int(rules["min_action_kinds"]))
        hedges = st.text_area("Hedge patterns, one regex per line", "\n".join(rules["hedge_patterns"]))
        topics = st.text_area("Noise topics, comma separated", ", ".join(rules["noise_topics"]))
        if st.form_submit_button("Save rules into the draft"):
            rules["loaner_tiers"] = tiers
            rules["tier_priority"] = priority
            rules["min_action_kinds"] = int(kinds)
            rules["hedge_patterns"] = [ln.strip() for ln in hedges.splitlines() if ln.strip()]
            rules["noise_topics"] = [t.strip() for t in topics.split(",") if t.strip()]
            _sync_rule_labels(data)
            st.success("Rules saved into the draft. R5 and R9 labels follow the tiers and the minimum.")


def _switches(data: dict) -> None:
    switches = data["switches"]
    with st.form("switches"):
        edited = {}
        for key, options in SWITCH_OPTIONS.items():
            current = switches.get(key, options[0])
            labels = [str(o) for o in options]
            idx = labels.index(str(current)) if str(current) in labels else 0
            choice = st.selectbox(key, labels, index=idx)
            edited[key] = options[labels.index(choice)]
        fuzzy = st.number_input("FUZZY_THRESHOLD", min_value=0, max_value=100,
                                 value=int(switches.get("FUZZY_THRESHOLD", 90)))
        if st.form_submit_button("Save switches into the draft"):
            edited["FUZZY_THRESHOLD"] = int(fuzzy)
            switches.update(edited)
            st.success("Switches saved into the draft.")


def _checks(data: dict) -> None:
    with st.form("checks"):
        edited = []
        for check in data["verifier"]:
            c1, c2, c3 = st.columns([5, 1, 2])
            enabled = c2.checkbox("On", value=bool(check["enabled"]), key=f"en_{check['id']}")
            severity = c3.selectbox("Severity", ["block", "warn"],
                                     index=0 if check["severity"] == "block" else 1, key=f"sev_{check['id']}",
                                     label_visibility="collapsed")
            c1.markdown(f"`{check['id']}`  \n{check['name']}")
            edited.append({**check, "enabled": enabled, "severity": severity})
        if st.form_submit_button("Save verifier into the draft"):
            data["verifier"] = edited
            st.success("Verifier checks saved into the draft.")


def _flush_playbook(data: dict) -> None:
    name = st.session_state.get("pb_loaded")
    steps = st.session_state.get(f"pb_steps_{name}") if name else None
    if name and steps is not None:
        data["playbooks"][name]["steps"] = list(steps)


def _preview(data: dict) -> None:
    st.markdown("Replays the 15 events in the twin and the Scenario Lab sentences, then diffs the plan "
                "against handbook_v1. Nothing is written to `traces/`.")
    if st.button("Preview impact"):
        _flush_playbook(data)
        pol = _validate(data)
        if pol is None:
            return
        with st.spinner("Replaying the 15 events and the Scenario Lab in the twin..."):
            st.session_state.policy_preview = preview_impact(pol)
    report = st.session_state.get("policy_preview")
    if not report:
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Robustness", f"{report['robust_n']}/{report['robust_of']}")
    c2.metric("Baseline writes", report["baseline_writes"])
    c3.metric("Draft writes", report["draft_writes"])
    st.caption("Robustness is the share of the 15 events whose blocking verifier checks pass under the draft.")
    if not report["rows"]:
        st.success("No planned action on the 15 events differs from handbook_v1.")
    else:
        for row in report["rows"]:
            with st.expander(f"{row['event']}: {len(row['added'])} added, {len(row['removed'])} removed"):
                if row["removed"]:
                    st.markdown("**Removed**")
                    st.write(row["removed"])
                if row["added"]:
                    st.markdown("**Added**")
                    st.write(row["added"])
    st.markdown("### Scenario Lab")
    lab = pd.DataFrame(report["scenarios"])
    st.dataframe(lab, hide_index=True, width="stretch")


def _publish(data: dict) -> None:
    st.markdown("Publishing writes a new file. handbook_v1 stays untouched.")
    with st.form("publish"):
        name = st.text_input("Profile name", value=data.get("name") or "Plant profile")
        author = st.text_input("Author")
        reason = st.text_area("Reason")
        go = st.form_submit_button("Publish as new version")
    if go:
        _flush_playbook(data)
        pol = _validate({**data, "name": name or data.get("name")})
        if pol is not None:
            try:
                saved = save_new_version(pol, author, reason)
            except (ValidationError, ValueError) as e:
                st.error(str(e))
            else:
                st.success(f"Published {saved.id}. The scored run still uses handbook_v1.")
                st.session_state.policy_draft = saved.model_dump(mode="json")
    st.divider()
    rows = history()
    st.markdown("### Version history")
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.caption("No publishes or rollbacks yet.")
    versions = [p.id for p in list_policies()]
    left, right = st.columns(2)
    a = left.selectbox("Compare", versions, index=0)
    b = right.selectbox("With", versions, index=min(1, len(versions) - 1))
    if st.button("Show side-by-side diff"):
        st.session_state.policy_diff = yaml_diff(load(a), load(b)) or "(no differences)"
    if st.session_state.get("policy_diff"):
        st.code(st.session_state.policy_diff, language="diff")
    st.divider()
    target = st.selectbox("Roll the sandbox back to", versions)
    with st.form("rollback"):
        rb_author = st.text_input("Rollback author")
        rb_reason = st.text_area("Rollback reason")
        if st.form_submit_button("Roll back"):
            try:
                rollback(target, rb_author, rb_reason)
            except (ValueError, OSError) as e:
                st.error(str(e))
            else:
                st.success(f"Live Incident Desk now uses {target}. The file was kept.")
    st.divider()
    desk = st.selectbox("Live Incident Desk profile", versions,
                         index=versions.index(desk_profile()) if desk_profile() in versions else 0)
    if st.button("Use this profile on the Live Incident Desk"):
        try:
            set_desk(desk, "manager", "desk profile chosen in Policy Studio")
        except (ValueError, OSError) as e:
            st.error(str(e))
        else:
            st.success(f"The desk and the Scenario Lab now use {desk}.")


def _selected_policy() -> Policy:
    name = desk_profile()
    try:
        return load(name)
    except (OSError, ValueError, ValidationError):
        return load("handbook_v1")


def page_desk() -> None:
    st.markdown("## Live Incident Desk")
    pol = _selected_policy()
    badge = "Scored baseline" if pol.read_only else pol.label or pol.status
    st.markdown(f"Profile **{pol.id}** · {badge}. This desk does not call the enterprise server and does not "
                f"change the scored run. Choose the profile in Policy Studio.")
    events = json.loads(config.EVENTS_PATH.read_text(encoding="utf-8"))
    ids = ["(paste a message)"] + [e["event_id"] for e in events]
    pick = st.selectbox("Event", ids)
    default = ""
    if pick != "(paste a message)":
        default = next(e["text"] for e in events if e["event_id"] == pick)
    text = st.text_area("Message", value=default, height=140)
    if st.button("Run in the twin", disabled=not text.strip()):
        with st.spinner("Planning in the twin..."):
            eid = pick if pick != "(paste a message)" else "DESK"
            st.session_state.desk_trace = handle_text(text, pol, event_id=eid, force_rules=pick == "(paste a message)")
    trace = st.session_state.get("desk_trace")
    if trace:
        _show_trace(trace)


def page_lab() -> None:
    st.markdown("## Scenario Lab")
    pol = _selected_policy()
    st.markdown(f"Same sandbox profile as the desk (**{pol.id}**). Sentences are classified from the policy "
                f"keywords, then planned in the twin. handbook_v1 is not modified.")
    labels = [s["name"] for s in SCENARIOS] + ["Custom"]
    pick = st.selectbox("Scenario", labels)
    if pick == "Custom":
        text = st.text_area("Message", height=120, placeholder="Weather closure: the Texas plant is down from 2027-03-26 through 2027-03-30.")
    else:
        text = next(s["text"] for s in SCENARIOS if s["name"] == pick)
        st.code(text)
    if st.button("Run scenario", disabled=not (text or "").strip()):
        with st.spinner("Planning in the twin..."):
            base = handle_text(text, load("handbook_v1"), event_id="LAB", force_rules=True)
            alt = handle_text(text, pol, event_id="LAB", force_rules=True)
            st.session_state.lab_result = (base, alt)
    result = st.session_state.get("lab_result")
    if not result:
        return
    base, alt = result
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**handbook_v1**")
        _show_trace(base)
    with c2:
        st.markdown(f"**{pol.id}**")
        _show_trace(alt)


def _show_trace(trace: dict) -> None:
    gate = trace["classification"]["gate"]
    st.markdown(f"Gate: **{gate}**")
    st.caption(trace["classification"].get("gate_reason") or "")
    if trace["incidents"]:
        st.write(pd.DataFrame([{"incident": i["incident_id"], "type": i["type"]} for i in trace["incidents"]]))
    plan = trace.get("plan") or []
    if plan:
        st.dataframe(pd.DataFrame([{"seq": a.get("seq"), "tool": a["tool"], "rule": a.get("rule_id"),
                                     "why": a.get("reason")} for a in plan]),
                     hide_index=True, width="stretch")
    else:
        st.caption("No planned actions.")
    checks = trace["verifier"]["plan_checks"] + trace["verifier"]["world_checks"]
    if checks:
        bad = [c["name"] for c in checks if not c["ok"] and c.get("blocking", True)]
        st.caption("Verifier blocking checks: " + ("all green" if not bad else "failed " + ", ".join(bad)))


def audit_section() -> None:
    st.markdown("### Policy publish and rollback")
    rows = audit_rows()
    if not rows:
        st.caption("No policy publishes or rollbacks yet. They are appended to traces/policy_audit.jsonl.")
        return
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
