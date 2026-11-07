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
| Tool calls | 961 (all succeeded, **0 failed**) |
| Self-check | 15/15 events green against an independent re-implementation of the rules (`eval/self_check_report.md`) |
| Tests | `pytest -q` → 69 passed |
| Model | `qwen2.5:3b-instruct` (Ollama, local); rule-based extractor as fallback |

## Agents

| Agent | Owns |
|---|---|
| Coordinator (`control_tower/agents/coordinator.py`) | LLM call, deterministic gate (noise / unconfirmed / needs_review), compound split, shared ledgers, plan merge, twin dry run, execution, read-back, trace |
| Supply Chain Planner (`supply_chain.py`) | R1 delay, R2 outage, R3 reschedule/transfer with one slot ledger per event |
| Dealer Network (`dealer_network.py`) | R4 one `dealer.notify` per dealer with exact ids; R6 stop-sale grouping |
| Customer Care & Quality (`customer_quality.py`) | R5 loaner ranking against live pools; R6 lot identification, hold, owner contact |
| Verifier (`control_tower/verifier.py`) | Recomputes expected sets from the tables and blocks any plan that violates R1-R10 |

Guardrails: pydantic-validated LLM output, phrases must literally appear in the message, deterministic gate with a
hedge-word detector, tool-client write guard (noise and rumor events physically cannot write), digital-twin dry run
that must have zero errors, verifier plan and world checks, live read-back, and a human-in-the-loop inbox.

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
Any OpenAI-compatible endpoint works via `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`. If no LLM is reachable the
coordinator falls back to the deterministic rule-based extractor (`llm_fallback: true` in the trace), which also
classifies all 15 events correctly. Set `LLM_DISABLED=1` to force the fallback.

## Run

```
# 1. tests
pytest -q

# 2. dry run against the local digital twin (no server needed)
python -m control_tower.run --dry-run

# 3. real run: terminal 1 - fresh organizer server with a new out folder
cd enterprise
python enterprise_server.py --data data --events data/events.json --out ../runs/run1 --port 8000

# terminal 2 - repo root
python -m control_tower.run
python eval/self_check.py --log runs/run1/action_log.jsonl

# 4. knowledge graph exports (graphml, Turtle, stats, schema PNG)
python -m control_tower.ontology --export

# 5. control tower UI (reads traces/ and exports/ only)
streamlit run ui/app.py          # http://localhost:8517 (see .streamlit/config.toml)
```

Other CLIs: `python -m control_tower.llm --all` prints the extraction + gate table for all events;
`python -m control_tower.ask "Who is affected by E-09?"` answers read-only questions (also a page in the UI).

For a fresh run, the server needs a new `--out` folder (it refuses to overwrite a log), e.g. `--out ../runs/run2`.

## Interpretation switches

Ambiguous handbook points live in `control_tower/config.py` and are printed into every trace:

| Switch | Value | Meaning |
|---|---|---|
| `NEXT_WEEKDAY` | `following_week` | "next Friday" on Mon 03-08 = Fri 03-19 (consistent with "can't make it next Monday ... next Friday") |
| `TRANSFER_LOWER_BOUND` | `today` | transfers may use any day with a free slot (handbook wording) |
| `PLANT_TIEBREAK` | `plants_csv_order` | earliest day first, then plant order in plants.csv |
| `COMPOUND_ORDER` | `message_order` | incidents of one event share the slot ledger in message order |
| `NOTIFY_SCOPE` | `per_event` | one `dealer.notify` per dealer per event |
| `NO_SLOT_ACTION` | `escalate` | an order with no feasible slot is escalated |
| `QUALITY_DEALER_NOTIFY` | `False` | quality holds use hold + stop sale + owner contact only |

## Repo map

```
enterprise/            organizer package, untouched (server, simulator, data, handbook)
control_tower/         config, data_loader, ontology, resolvers, llm, policy, twin, tools_client,
                       verifier, trace, run, agents/
eval/self_check.py     independent replay + scoring of an action log
ui/app.py              Streamlit control tower
tests/                 pytest suite (synthetic fixtures for the specialists)
traces/                per-event traces, run_summary.json, audit_log.csv
exports/               knowledge_graph.graphml, ontology.ttl, graph_stats.json, ontology_schema.png
runs/final/            action_log.jsonl from the clean submission run (one fresh server, all 15 events)
docs/                  AGENTS/SPEC kit docs, build prompts
```
