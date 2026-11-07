# AGENTS.md - Wacky Wheels Control Tower (Hitachi "Hack the Highway")

Every coding agent working in this repo (Codex, Antigravity, Claude, etc.) must read this file
and `docs/SPEC.md` before writing code. If anything here conflicts with `enterprise/data/policy_handbook.md`,
the handbook wins - stop and flag it.

## 1. What we are building
An event-driven multi-agent "control tower" for a fictional just-in-time automaker (Wacky Wheels Co.).
It reads 15 operational messages (`enterprise/data/events.json`), understands them with a small LLM,
traverses a knowledge graph built from the CSVs, executes corrective actions through the provided
enterprise server (`POST /act`), and shows a graph path, reasoning trace and audit trail per event.

Scoring (from organizers):
- 50% Event handling accuracy: our `action_log.jsonl` is replayed on a fresh world and compared to the
  handbook rules. Wrong, missing or extra actions cost points. Failed calls are counted.
- 20% Knowledge graph and reasoning (ontology quality, traversal, graph path per event).
- 10% Agent architecture and guardrails (roles, LLM vs code split, validation before acting, escalation).
- 10% Efficiency (few wasted/failed calls, small cheap model; cite the model).
- 10% UX and explainability (control tower UI, graph + trace visualization, audit summaries).
Organizer clarifications: only these 15 events are judged; reading the CSVs directly to build the graph is allowed.

## 2. Golden rules for agents
1. **LLM reads, code decides.** The LLM only classifies the message and extracts raw phrases.
   All id resolution, date math, traversal, rescheduling, loaner ranking and tool arguments are plain,
   deterministic, unit-tested Python. Never let an LLM choose an id, a date or an action list.
2. **Never hard-code answers.** No event-id-specific branches, no precomputed results. Everything must be
   derived from event text + tables. Code is reviewed by judges.
3. **Do not edit** anything in `enterprise/` (their `enterprise.py`, `enterprise_server.py`, `data/`).
   We may import `enterprise.Enterprise` read-only as a local simulator ("digital twin").
4. **Plan, simulate, verify, then execute.** Every write is first applied to a local `Enterprise` twin.
   Only if the whole plan succeeds in the twin and passes the policy verifier do we call the real server.
   Target: **zero failed calls** in the real action log.
5. **Noise = zero calls. Unconfirmed = exactly one `escalate`, nothing else.** The tool client must hard-block
   write tools for events classified as noise/unconfirmed.
6. **Every action cites a handbook rule** (`rule_id` like `R3`, `R5`) and an evidence graph path.
7. Deterministic and reproducible: temperature 0, LLM responses cached in `cache/llm/`, stable sort orders.
8. Small, typed, tested modules. Use `pytest`. Each new module gets tests in `tests/`.
9. Windows-friendly: pathlib only, UTF-8 everywhere, no bash-only scripts (provide `.py` entry points).

## 3. Repo layout (target)
```
enterprise/                 # organizer package, untouched (enterprise.py, enterprise_server.py, data/, Usecase.md)
control_tower/
  config.py                 # all tunable interpretations (see SPEC section 9) in one place
  data_loader.py            # typed loading of all CSVs + calendar helpers (date <-> working-day index)
  ontology.py               # KnowledgeGraph (networkx MultiDiGraph), schema, traversals, exports
  resolvers.py              # alias resolution + relative date resolution
  llm.py                    # OpenAI-compatible client (Ollama default), JSON schema, cache, regex fallback
  policy.py                 # handbook rules as constants R1..R10 with text, used for citations
  twin.py                   # digital twin wrapper around enterprise.Enterprise for dry runs
  tools_client.py           # HTTP client for /events, /tools, /act; logs every call; write-guard
  agents/
    coordinator.py          # classify, split compound, gate (noise/unconfirmed), route, merge, execute
    supply_chain.py         # Supply Chain Planner: affected orders, reschedule/transfer (slot ledger)
    dealer_network.py       # Dealer Network: dealer.notify grouping, dealer.stop_sale
    customer_quality.py     # Customer Care & Quality: loaners (ranking), hold lot, notify owners
  verifier.py               # policy invariant checks on a plan and on the executed world
  trace.py                  # per-event trace JSON writer (schema in SPEC section 7)
  run.py                    # CLI: run all events end to end against the server
eval/self_check.py          # replay action_log on a fresh Enterprise and report invariants
ui/app.py                   # Streamlit control tower (Antigravity owns ui/)
docs/                       # SPEC.md, design_card.md, ontology diagrams, video script
traces/  runs/  cache/      # outputs (gitignored except final submission copies)
tests/
```

## 4. Handbook rules (summary - the source of truth is policy_handbook.md)
- Today = Monday 2027-03-08 = working-day index 0. Mon-Fri only. Planning window: today .. 2027-04-02 (index 19).
- **R1 Supplier delay:** builds that need the delayed part cannot run from original ETA up to but NOT including
  the new ETA. Affected = production orders at the **receiving plant** whose model BOM contains the part and whose
  build date is in [original ETA, new ETA).
- **R2 Plant outage:** no builds at the plant during the outage (inclusive). All that plant's orders in the window
  are affected. Plant restarts the next working day.
- **R3 Rescheduling:** move each affected order to the earliest feasible slot. Same plant: new day >= end of
  disruption (new ETA, or day after outage) and the day has a free slot (`slots_per_day`). If no same-plant slot,
  transfer to another plant that builds the model (`plant_models.csv`) on any day with a free slot.
  Never move unaffected orders.
- **R4 Dealer notification:** every dealer with >= 1 affected customer order gets exactly ONE `dealer.notify`
  listing exactly those customer order ids.
- **R5 Loaners:** affected customer orders whose customer tier is Platinum or Gold get one loaner from their
  dealer's pool. Pools are limited (`crm.loaner_availability`). Priority: Platinum before Gold, then earlier
  promised date, then lower customer order id. Standard tier: no loaner, no customer contact.
- **R6 Quality hold:** `quality.hold_lot` the lot. Affected vehicles = finished vehicles built at the lot's plant,
  on the lot's build dates, from production orders of models that use the part. Unsold (`in_stock`) ->
  `dealer.stop_sale` at their dealer. Sold -> `crm.notify_customer` to the owner.
- **R7 Noise:** no write tool calls.  **R8 Unconfirmed/unclear:** no operational action, use `escalate`.
- **R9 Completeness:** a real incident ends with >= 3 different kinds of action.
- **R10 Do not touch what is not affected.**

## 5. Agents and responsibilities
| Agent | Owns | Never does |
|---|---|---|
| Coordinator | LLM call, category gate, compound split, routing, shared ledgers, plan merge, execution, trace | domain decisions |
| Supply Chain Planner | R1, R2, R3: affected production orders, slot search, reschedule/transfer plan | notifications |
| Dealer Network | R4 dealer.notify (one per dealer, merged across incidents of the same event), R6 stop_sale grouping | loaners |
| Customer Care & Quality | R5 loaner ranking against live pools, R6 lot identification, hold_lot, owner notifications | rescheduling |
| Verifier (guardrail) | checks every plan against R1-R10 before execution and the twin state after | creating actions |

## 6. Conventions
- Python 3.11+. Formatting: black-compatible. Type hints everywhere. Dataclasses or pydantic models for
  plans/actions.
- Planned action object: `{seq, agent, tool, args, rule_id, reason, evidence_path, incident_id}`.
- Sorting for determinism: production orders by (original build date, production_order_id); customer orders by id;
  dealers by id; plants by plants.csv order.
- Never print secrets. LLM base URL/model/key come from env vars (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`).
- The server must be started fresh with a new `--out` folder for each full run (the world resets on start).

## 7. Definition of done for any change
1. `pytest -q` passes.
2. `python -m control_tower.run --dry-run` runs all 15 events against the twin with 0 failures and 0 verifier errors.
3. `python eval/self_check.py --log runs/<run>/action_log.jsonl` reports all invariants green.
4. Trace files in `traces/` validate against the schema in SPEC section 7.
