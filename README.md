# Wacky Wheels Control Tower

An event-driven multi-agent "control tower" for the Hitachi **Hack the Highway** datathon. It reads the 15
operational messages in `enterprise/data/events.json`, understands them with a small local LLM, traverses a
knowledge graph built from the company CSVs, plans corrective actions per the policy handbook, dry-runs them in a
digital twin, verifies them, executes them through the organizer's enterprise server, and shows a graph path,
reasoning trace and audit trail for every event.

**LLM reads, code decides.** The LLM (`qwen2.5:3b-instruct` via Ollama, 3B parameters, temperature 0) only
classifies each message and copies out raw phrases. Every id, date, affected set, slot, loaner and tool argument is
computed by plain, unit-tested Python.

## Results of the current run

| | |
|---|---|
| Events | 15 (6 delays/outages, 3 quality holds, 1 compound digest, 3 noise, 2 rumors) |
| Tool calls | 961 (all succeeded, **0 failed**): 766 writes + 193 free read-back checks + 2 escalations |
| Self-check | 15/15 events green against an independent re-implementation of the rules (`eval/self_check_report.md`) |
| Tests | `pytest -q` → 92 passed |
| Hallucination audit | 50 LLM phrases: 49 used, 1 replaced by code, 0 invented; 4 ungrounded rationales caught and kept out of decisions (`docs/llm_audit.md`) |
| What-if | every open interpretation re-planned and diffed (`docs/what_if_report.md`) |
| Model | `qwen2.5:3b-instruct` (Ollama, local); rule-based extractor as fallback |

## What a successful run creates

| File or screen | What it is | Who it is for |
|---|---|---|
| `runs/final/action_log.jsonl` | every tool call the server received (written by the organizer server) | the scorer |
| `traces/E-01.json` ... `E-15.json` | one story per event: message, extraction, graph path, plan, verifier, actions, why | judges, auditors |
| `traces/audit_log.csv` | one row per call with seq, plan step, rule id and reason | auditors (Excel) |
| `exports/` | ontology diagram, GraphML, RDF/Turtle, graph stats | graph score |
| `eval/self_check_report.md` | independent grading of the action log | you, before submitting |
| `docs/what_if_report.md`, `docs/llm_audit.md` | interpretation impact and hallucination audit | judges, the Q&A session |
| `docs/architecture.png`, `docs/control_tower_deck.pptx` | architecture diagram and 10-slide deck (`python docs/make_deck.py`) | presentation |
| `docs/hitachi_session.md` | what Hitachi answered, what we changed, questions for the next session | the team |
| Streamlit UI | all of the above on screens | demo |

## Agents

| Agent | Owns |
|---|---|
| Coordinator (`control_tower/agents/coordinator.py`) | LLM call, deterministic gate (noise / unconfirmed / needs_review), compound split, shared ledgers, plan merge, twin dry run, execution, read-back, trace |
| Supply Chain Planner (`supply_chain.py`) | R1 delay, R2 outage, R3 reschedule/transfer with one slot ledger per event |
| Dealer Network (`dealer_network.py`) | R4 one `dealer.notify` per dealer with exact ids; R6 stop-sale grouping |
| Customer Care & Quality (`customer_quality.py`) | R5 loaner ranking against live pools; R6 lot identification, hold, owner contact |
| Verifier (`control_tower/verifier.py`) | Recomputes expected sets from the tables and blocks any plan that violates R1-R10 |

Guardrails: pydantic-validated LLM output, phrases must literally appear in the message, decision reasons written
by code (the LLM rationale is only a note and must pass a grounding check), deterministic gate with a hedge-word
detector, tool-client write guard (noise and rumor events physically cannot write), digital-twin dry run that must
have zero errors, verifier plan and world checks, live read-back, and a human-in-the-loop inbox.

## Setup

Python 3.11+.

```
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Local LLM (optional but recommended):
```
# install Ollama from https://ollama.com, then
ollama pull qwen2.5:3b-instruct
```
Any OpenAI-compatible endpoint works via `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`. LLM outputs are cached in
`cache/llm/`, so a re-run reproduces the scored run exactly. If no LLM is reachable the coordinator falls back to
the deterministic rule-based extractor (`llm_fallback: true` in the trace), which also classifies all 15 events
correctly. Set `LLM_DISABLED=1` to force the fallback.

## Run (4 steps)

```
# A. unit tests                                   -> 92 passed
pytest -q

# B. practice run on the digital twin (no server) -> 15 events, 0 failed, verifier green
python -m control_tower.run --dry-run

# C. real run. Window 1: a fresh organizer server with a NEW out folder
cd enterprise
python enterprise_server.py --data data --events data/events.json --out ..\runs\final --port 8000
#    Window 2 (repo root)                          -> 15 events, 0 failed calls
python -m control_tower.run

# D. grade the log, then open the screens         -> 15/15 events green
python eval/self_check.py --log runs/final/action_log.jsonl
streamlit run ui/app.py          # http://localhost:8517 (see .streamlit/config.toml)
```

Optional:
```
python eval/what_if.py           # re-plan with every alternative interpretation, write docs/what_if_report.md
python eval/llm_audit.py         # hallucination audit, write docs/llm_audit.md (part B needs the LLM)
python -m control_tower.ontology --export   # graphml, Turtle, stats, schema PNG
python -m control_tower.llm --all           # extraction + gate table for all events
python -m control_tower.ask "Who is affected by E-09?"
python docs/make_deck.py         # architecture diagram + slide deck in docs/
```

The server refuses to overwrite an existing log: delete the old folder or use a new `--out` (e.g. `..\runs\run2`).

## Interpretation switches

Ambiguous handbook points live in `control_tower/config.py` and are printed into every trace. The verifier and the
self-check follow the same switches, and `tests/test_switches_and_guards.py` proves every value stays 15/15 green.

| Switch | Value | Alternative | Writes changed by the alternative |
|---|---|---|---|
| `NEXT_WEEKDAY` | `following_week` ("next Friday" on Mon 03-08 = Fri 03-19) | `nearest_upcoming` | 140 (E-01 becomes invalid: new ETA before old) |
| `TRANSFER_LOWER_BOUND` | `today` (any day with a free slot) | `restart` | 5 transfers + 33 notification texts |
| `TRANSFER_SEARCH` | `day_first` (earliest day across plants) | `plant_first` ("plant by plant") | 0 |
| `PLANT_TIEBREAK` | `plants_csv_order` | `plant_id_alpha` | - |
| `SLOT_PRIORITY` | `build_date` | `promised_date` ("delivery first") | 2 reschedules + 14 texts (E-11) |
| `COMPOUND_ORDER` | `message_order` | `earliest_disruption_first` | 0 |
| `NOTIFY_SCOPE` | `per_event` (handbook R4: exactly one per dealer) | `per_incident` | +15 notifications (E-01) |
| `NO_SLOT_ACTION` | `escalate` | `skip` | 0 (no order lacks a slot) |

Quality holds use hold + stop sale + owner contact only: `dealer.notify` is defined for delayed customer orders,
and a quality hold has none (each dealer is told through `dealer.stop_sale`).

## Repo map

```
enterprise/            organizer package, untouched (server, simulator, data, handbook)
control_tower/         config, data_loader, ontology, resolvers, llm, policy, twin, tools_client,
                       verifier, trace, run, ask, agents/
eval/                  self_check.py (independent grading), what_if.py, llm_audit.py
ui/app.py              Streamlit control tower (ui/static/ serves vis-network once)
tests/                 pytest suite (synthetic fixtures for the specialists)
traces/                per-event traces, run_summary.json, audit_log.csv
exports/               knowledge_graph.graphml, ontology.ttl, graph_stats.json, ontology_schema.png
runs/final/            action_log.jsonl from the clean submission run (one fresh server, all 15 events)
docs/                  design card, rules walkthrough, what-if, LLM audit, Hitachi session notes, deck
```
