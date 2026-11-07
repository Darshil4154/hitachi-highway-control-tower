# Build prompts - run them in order

How to use this file:
- **Codex** builds the engine (`control_tower/`, `eval/`, `tests/`). **Antigravity** builds the UI (`ui/`) and does
  independent reviews. Never let both edit the same folder at the same time.
- Paste each prompt as written. After each one, run the **Check** commands yourself. Do not move on until they pass.
- Commit after every green step: `git add . ; git commit -m "step N" ; git push`
- If an agent drifts, paste: `Re-read AGENTS.md and docs/SPEC.md. Your change violates <rule>. Fix only that.`

Times are rough targets for a solo builder (about 20 hours total).

---------------------------------------------------------------------------------------------------
## Step 0 - Repo setup (you, 15 min, no agent)

In PowerShell, inside your repo folder (`C:\Users\darsh\Documents\TAMU_Datathon_2026`):
```
mkdir enterprise, docs, control_tower, control_tower\agents, eval, ui, tests, traces, runs, cache, exports
Expand-Archive ~\Downloads\hack_the_highway_student_package.zip -DestinationPath $env:TEMP\hth -Force
Copy-Item $env:TEMP\hth\hack_the_highway_package\* .\enterprise\ -Recurse -Force
```
Copy this kit's `AGENTS.md` to the repo root (replace the old team one) and `docs/SPEC.md` into `docs\`.
Then:
```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install networkx pandas pydantic requests openai rapidfuzz rdflib streamlit pyvis plotly pytest
pip freeze > requirements.txt
```
LLM (local, free, small model = efficiency points):
```
winget install Ollama.Ollama
ollama pull qwen2.5:7b-instruct
```
(If your laptop has under 16 GB RAM, use `qwen2.5:3b-instruct` instead.)

Smoke test the organizer server in a second terminal:
```
cd enterprise
python enterprise_server.py --data data --events data/events.json --out ..\runs\smoke --port 8000
```
Open http://127.0.0.1:8000/events in a browser. You should see 15 events. Stop it with Ctrl+C.

Add to `.gitignore`: `.venv/`, `cache/`, `runs/smoke/`, `__pycache__/`.

---------------------------------------------------------------------------------------------------
## Step 1 - Data loader + calendar (Codex, 30 min)

```
Read AGENTS.md and docs/SPEC.md fully before writing code.

Implement control_tower/config.py and control_tower/data_loader.py per SPEC sections 1 and 9.
- config.py: all interpretation switches from SPEC section 9 with the listed defaults, plus paths
  (DATA_DIR = enterprise/data), SERVER_URL default http://127.0.0.1:8000, LLM env vars.
- data_loader.py: a DataStore class that loads every CSV in enterprise/data into typed dataclasses, keyed by their
  ids, and exposes: plants (in file order), plant_models, bom (model -> set of parts), shipments, production_orders,
  customer_orders (also indexed by production_order_id and by dealer), customers, dealers, loaners, part_lots,
  vehicles (also indexed by production_order_id), aliases.
- Calendar helpers identical to enterprise.py: TODAY=2027-03-08 index 0, LAST index 19, idx_to_date, date_to_idx,
  working_days(start, end), next_working_day. Import them from enterprise/enterprise.py if convenient
  (add enterprise/ to sys.path inside the helper, do not modify enterprise files).
Write tests/test_data_loader.py: row counts match the CSVs, every production order's plant can build its model,
calendar round trips for all 30 days, weekends raise.
```
**Check:** `pytest -q` green.

---------------------------------------------------------------------------------------------------
## Step 2 - Knowledge graph / ontology (Codex, 60 min)

```
Implement control_tower/ontology.py per SPEC section 2 using networkx MultiDiGraph and the DataStore.
- Node ids "Type:id", every node has type/label/attributes. Use EXACTLY the edge names in the SPEC table.
- Traversal functions listed in SPEC 2, each returning (result_ids, path_edges) so traces can cite the path.
- explain_path() producing a readable chain.
- Export functions writing exports/knowledge_graph.graphml, exports/ontology.ttl (rdflib, namespace
  https://wackywheels.example/ontology#, classes + object properties + instances), exports/graph_stats.json,
  and exports/ontology_schema.png (schema-level diagram: one node per type, edges labeled; matplotlib is fine).
- CLI: python -m control_tower.ontology --export
Tests in tests/test_ontology.py:
- orders_needing_part only returns orders at the given plant, whose model BOM has the part, in [from, until_excl)
- orders_at_plant is inclusive on both ends
- vehicles_for_lot returns only vehicles at the lot plant, inside the lot build dates, of models using the part
- every CustomerOrder node has exactly one FULFILLS in-edge, one SOLD_THROUGH and one ORDERED_BY out-edge
Use synthetic checks derived from the tables, never hard-coded event answers.
```
**Check:** `python -m control_tower.ontology --export` creates 4 files in `exports\`. Open the PNG. `pytest -q` green.

---------------------------------------------------------------------------------------------------
## Step 3 - Resolvers: aliases + relative dates (Codex, 45 min)

```
Implement control_tower/resolvers.py per SPEC section 3.
- resolve_entity(mention, kind) -> (entity_id | None, method, confidence). Order: exact id regex, aliases.csv
  (case-insensitive, longest match), name fields with singular/plural normalization, fuzzy >= 90 as suggestion only
  (method "fuzzy", flagged needs_review).
- resolve_date(phrase) -> (date | None, rule_name). Implement every row of the SPEC 3.2 table, driven by
  config.NEXT_WEEKDAY. Validate weekday-name vs date when both are present.
- find_ids_in_text(text) -> all explicit ids (plants, suppliers, shipments, lots, parts, POs).
Tests in tests/test_resolvers.py covering: "the Texas plant", "Huntsville", "Volt", "heavy-duty wiring harness",
"60 kWh battery packs", "surround-view cameras", "infotainment chip", "Kestrel", "Quanta", "Lumen", "Orbit";
dates: "next Monday" -> 2027-03-15, "next Friday" -> 2027-03-19, "next Tuesday" -> 2027-03-16,
"last Monday" -> 2027-03-01, "Thursday Feb 25" -> 2027-02-25, "Monday Mar 29" -> 2027-03-29,
"Thursday Apr 1" -> 2027-04-01, "Friday Mar 26" -> 2027-03-26, "2027-03-24" literal,
and a mismatch case ("Tuesday Mar 29" -> flagged).
```
**Check:** `pytest -q` green.

---------------------------------------------------------------------------------------------------
## Step 4 - LLM extraction + gate (Codex, 60 min)

```
Implement control_tower/llm.py per SPEC section 4.
- OpenAI-compatible client using env LLM_BASE_URL (default http://localhost:11434/v1), LLM_MODEL
  (default qwen2.5:7b-instruct), LLM_API_KEY (default "ollama"). temperature 0, JSON response.
- System prompt: role = extraction only, return phrases exactly as written, no date math, no ids invented,
  one incident object per incident, categories incident/noise/unconfirmed with clear definitions. Add 3 short
  few-shot examples that WE write (a cheese-plant outage, a tire rumor, a lunch-menu email) - do not copy
  the real 15 events.
- Pydantic schema from SPEC section 4; on invalid JSON retry once with the error, then fall back to a regex
  extractor (ids, ISO dates, "Mon Mar 29" style dates) and set llm_fallback=true.
- Cache responses in cache/llm/<sha256>.json; record prompt/completion token counts.
- gate(extraction, resolved) implementing the deterministic gate in SPEC section 4 (noise / unconfirmed /
  needs_review / incident), with the hedge-word detector and required-field checks per incident type.
- CLI: python -m control_tower.llm --all  -> prints a table: event_id, category, #incidents, types, key phrases,
  gate result, missing fields.
Do not branch on event ids anywhere.
```
**Check:** run Ollama, then `python -m control_tower.llm --all`. Read the table against the messages yourself:
3 brochure questions = noise, 2 rumors = unconfirmed, the daily digest = 2 incidents, quality bulletins = quality_hold.
If one is wrong, improve the prompt or few-shots, not with id-specific code.

---------------------------------------------------------------------------------------------------
## Step 5 - Digital twin + tools client (Codex, 30 min)

```
Implement control_tower/twin.py and control_tower/tools_client.py per AGENTS.md rule 4 and SPEC section 6.
- twin.py: Twin(event_id) wraps a fresh enterprise.Enterprise(DATA_DIR) (import by path, no edits), exposes
  apply(planned_actions) -> list of results/errors without touching the server, snapshot_slots(plant, day range)
  for before/after heatmaps, and loaner_pool(dealer).
- tools_client.py: ToolsClient(base_url) with get_events(), get_tools(), act(event_id, tool, args) -> (ok, result).
  Log every call (with timestamp, kind read/write) into an in-memory list for the trace. Write guard: refuse write
  tools when the coordinator marked the event noise/unconfirmed/needs_review (raise, never send). No automatic
  retries of writes.
Tests: twin rejects overbooking and reports it; write guard blocks writes for a noise-marked event.
```
**Check:** `pytest -q` green.

---------------------------------------------------------------------------------------------------
## Step 6 - Specialist agents (Codex, 2.5 h) - the 50% part, go slow

```
Implement the three specialists in control_tower/agents/ exactly per SPEC section 5 and control_tower/policy.py
(R1..R10 constants with short text, used as rule_id citations).

supply_chain.py - SupplyChainPlanner
- resolve_delay(incident) -> shipment, part, plant, original ETA, new ETA with validations (SPEC 5.1)
- affected_orders(incident) using ontology traversals (R1 / R2), returning orders + graph path + excluded reasons
- plan_moves(incidents, ledger) implementing the shared slot ledger, blocked(plant, day, model), same-plant first,
  then transfer with config.TRANSFER_LOWER_BOUND and config.PLANT_TIEBREAK, else config.NO_SLOT_ACTION.
  Deterministic order: original build date, then production_order_id.

dealer_network.py - DealerNetwork
- plan_notifications(affected_customer_orders) -> one dealer.notify per dealer (config.NOTIFY_SCOPE), sorted ids,
  message text with reason + new date/plant per order.
- plan_stop_sales(vehicles_unsold) -> one dealer.stop_sale per dealer, sorted VINs.

customer_quality.py - CustomerCareQuality
- plan_loaners(affected_customer_orders, pools) -> ranking per SPEC 5.3, assigned + skipped with reasons.
- resolve_lot(incident) per SPEC 5.3 with validations, plan_quality(lot) -> hold_lot, owners to notify
  (distinct, sorted), unsold vehicles for DealerNetwork.

Every planned action: {seq, agent, tool, args, rule_id, reason, evidence_path, incident_id}.
Tests in tests/test_specialists.py built from synthetic mini-fixtures (tiny fake tables), including:
capacity overflow forces a transfer; transfer never goes to a plant that cannot build the model; blocked days
are never used; loaner priority Platinum > Gold > earlier promise > lower id with a pool of 1; Standard tier gets
nothing; stop_sale only includes in_stock; one notify per dealer with exactly its affected orders.
```
**Check:** `pytest -q` green. Then paste this follow-up into Codex:
```
Write a 1-page explanation in docs/rules_walkthrough.md of how each handbook rule R1-R10 is implemented,
with function names and file paths. Quote the handbook sentence for each rule.
```

---------------------------------------------------------------------------------------------------
## Step 7 - Coordinator, verifier, traces, run CLI (Codex, 2 h)

```
Implement control_tower/agents/coordinator.py, control_tower/verifier.py, control_tower/trace.py and
control_tower/run.py per SPEC sections 6 and 7.

Coordinator.handle(event):
  extract (llm) -> resolve entities/dates (record method per mention) -> gate ->
  noise: no calls; unconfirmed/needs_review: exactly one escalate (reason lists missing fields) ->
  incidents: specialists build one merged plan with a shared slot ledger and shared loaner ranking ->
  verifier.check_plan -> twin.apply (must be 0 errors) -> verifier.check_world ->
  execute on server in order: reschedule/transfer, dealer.notify, assign_loaner, hold_lot, stop_sale,
  notify_customer -> read-back verification with mes.get_schedule on touched plant/days ->
  trace.write.
If any verifier check fails: do NOT execute writes; escalate with the failing check as reason.

verifier.py: all invariants listed in SPEC section 6, each returning {name, ok, detail}.
trace.py: writes traces/<event_id>.json exactly per SPEC section 7 + traces/run_summary.json +
  traces/audit_log.csv (one row per executed action: event, seq, agent, tool, target, rule_id, reason, ok).
  Include config_snapshot in every trace.
run.py: python -m control_tower.run [--dry-run] [--events E-08,E-12] [--server http://127.0.0.1:8000]
  --dry-run uses only the twin (no server). Prints a final table: event, category, writes by tool, failed, verifier.
```
**Check (dry run, no server):** `python -m control_tower.run --dry-run` -> 15 events, 0 failed, all verifier green.
Open 3 trace files and read them like a judge would.

---------------------------------------------------------------------------------------------------
## Step 8 - Self-check evaluator (Codex, 45 min) - "we scored ourselves before submitting"

```
Implement eval/self_check.py:
- Input: --log runs/<run>/action_log.jsonl
- Rebuild a fresh enterprise.Enterprise per event, replay that event's calls in order, and independently
  re-derive the expected affected sets from the CSVs using a SEPARATE minimal implementation of rules R1, R2, R4,
  R5, R6 written from the handbook text (do not import control_tower planner code - independent check).
- Report per event: failed calls, orders moved that were not affected, affected orders not moved, notify
  correctness per dealer, loaner correctness, lot/stop-sale/owner correctness, noise calls, escalation correctness,
  distinct write kinds (R9). Output a markdown table to eval/self_check_report.md.
```
**Check:** start the server fresh, run for real, then self-check:
```
# terminal 1
cd enterprise
python enterprise_server.py --data data --events data/events.json --out ..\runs\run1 --port 8000
# terminal 2 (repo root, venv active)
python -m control_tower.run
python eval/self_check.py --log runs/run1/action_log.jsonl
```
All green -> commit. Anything red -> paste the red row into Codex and ask it to fix the root cause with a test.

---------------------------------------------------------------------------------------------------
## Step 9 - Independent rule review (Antigravity, 30 min)

Use a different model than Codex so the review is truly independent.
```
You are an auditor. Read enterprise/data/policy_handbook.md, AGENTS.md and docs/SPEC.md. Then review
control_tower/agents/*.py, control_tower/verifier.py and eval/self_check.py ONLY for policy compliance.
Do not edit code. Produce docs/review_findings.md with a table: rule, file:line, finding, severity, suggested fix.
Check especially: [orig ETA, new ETA) half-open window, outage inclusive window and next-working-day restart,
receiving-plant-only rule, same-plant lower bound, transfer plant eligibility, one notify per dealer with exact ids,
loaner priority order and pool limits, Standard tier gets nothing, quality vehicles = lot plant + lot dates +
models using the part, sold vs in_stock split, noise zero calls, unconfirmed exactly one escalate,
no event-id-specific code anywhere.
```
Give the findings file to Codex: `Fix every High and Medium finding in docs/review_findings.md, with tests.`

---------------------------------------------------------------------------------------------------
## Step 10 - Control tower UI (Antigravity, 3-4 h)

```
Read AGENTS.md and docs/SPEC.md section 8. Build ui/app.py with Streamlit. It only READS traces/*.json,
traces/audit_log.csv, traces/run_summary.json and exports/*. It never calls the enterprise server.

Design: clean operations "control tower" look, dark sidebar, consistent category colors
(delay amber, outage red, quality purple, noise gray, escalated blue, compound teal), no clutter.
Sections:
1. KPI header: events, incidents handled, escalations, noise filtered, write actions, failed calls, model used.
2. Event feed (left column): cards with source icon, received time, category badge, one-line summary; filter chips.
3. Event detail (main): original message with evidence quotes highlighted and resolved entity chips; extraction table
   (phrase -> id -> method); interactive graph of the event subgraph (pyvis embedded via components.html) with the
   graph_path edges highlighted and node colors by type; decisions table (order, from -> to, same plant or transfer,
   reason, rule); loaner ranking (assigned / skipped with reason); action log with rule ids and OK ticks;
   verifier checklist; summary paragraph. For compound events, tabs per incident plus a "shared resources" note.
4. Before/after schedule heatmap (plant x working day utilization) for the selected event, from the trace.
5. Human-in-the-loop inbox: escalated events with a "missing information" card (missing_fields) and Approve /
   Dismiss buttons that only write to ui/hitl_decisions.json.
6. Audit trail page: filterable table + CSV download.
7. Ontology page: schema PNG, graph stats, download links for ontology.ttl and graphml.
Use st.set_page_config(layout="wide"). Add a "Replay run" button that animates events arriving one by one
(sleep 1s each) for the demo video. Test it in the browser and fix layout issues you see.
Run with: streamlit run ui/app.py
```
**Check:** `streamlit run ui/app.py` - click every event; noise and escalated events must look intentional, not empty.

---------------------------------------------------------------------------------------------------
## Step 11 - Stretch: "Ask the control tower" (Codex for backend, Antigravity for UI, 1.5 h)

Only if steps 0-10 are green. This answers the speaker's question "what would you ask the system?".
```
Add control_tower/ask.py: read-only graph query functions (who_is_affected(event_id), dealers_for_event,
loaners_for_dealer, orders_at_plant_day, vehicles_in_lot, path_between(a, b)) exposed to the LLM as tools
(OpenAI tool calling). The LLM only picks a function and arguments; answers are rendered from function results
with the graph path. Never call /act from here. Add 6 example questions and tests.
```
Then in Antigravity: `Add an "Ask the control tower" chat panel to ui/app.py that calls control_tower.ask.`

---------------------------------------------------------------------------------------------------
## Step 12 - Final run + submission pack (Codex, 1.5 h)

```
1. Create docs/design_card.md (one page): problem and personas (Production Planner, Dealer Relations Manager,
   Customer Care Lead, Quality Engineer, Auditor); architecture diagram (mermaid); LLM vs code table; agent roles;
   guardrails (gate, write guard, digital twin dry run, verifier, read-back, HITL); evaluation (self_check results,
   0 failed calls, tests count); interpretation switches and their values; model cited with size and why;
   what we would improve.
2. Create README.md: what it is, setup (venv, ollama pull), how to run server + run.py + self_check + UI,
   repo map, model citation.
3. Create docs/video_script.md: 2.5 minute demo script (problem in 15s, architecture 20s, live replay of 4 events:
   one delay, the compound digest, one quality hold, one rumor escalation; graph path; audit trail; self-check; close).
```
Final run (fresh server, new out folder):
```
cd enterprise
python enterprise_server.py --data data --events data/events.json --out ..\runs\final --port 8000
# other terminal, repo root
python -m control_tower.run
python eval/self_check.py --log runs/final/action_log.jsonl
python -m control_tower.ontology --export
streamlit run ui/app.py
```
Submit: `runs/final/action_log.jsonl`, repo link, `traces/`, `exports/`, `docs/design_card.md`, video.

---------------------------------------------------------------------------------------------------
## Step 13 - 3D "agent village" control tower view (only after steps 0-10 are green, 3-4 h)

Inspired by isometric "agent town" visualizations: the company as a hex-tile world, agents as robots,
events as floating task cards. It is a demo and pitch layer on top of the same traces; the Streamlit app
stays as the detailed audit view.

Install Node.js once (PowerShell): `winget install OpenJS.NodeJS.LTS`, then reopen the terminal.

### 13a - Data export (Codex, 20 min)
```
Add control_tower/export_ui3d.py (CLI: python -m control_tower.export_ui3d). It writes ui3d/public/data/:
- world.json: plants (id, name, slots_per_day, models), suppliers (id, name), dealers (id, name, region),
  plus a deterministic layout: x/z coordinates on a hex grid grouped into districts
  (suppliers west, plants center, dealers east grouped by region, a "customers" district south,
  a "human review" desk and an "audit office" north). Layout comes from code, not hand-placed.
- events.json: for each trace, a timeline of steps the 3D view can animate:
  [{t, agent, kind: walk|glow|move_order|transfer|notify|loaner|hold|stop_sale|notify_owner|escalate|ignore,
    target ids, label, rule_id}], built only from the trace's plan/actions/decisions.
- copies traces/run_summary.json.
Never invent steps that are not in the trace.
```

### 13b - 3D app (Antigravity, 3 h)
```
Create a new web app in ui3d/ with Vite + React + TypeScript + @react-three/fiber + @react-three/drei.
It only reads ui3d/public/data/world.json, events.json and run_summary.json. No backend, no external 3D assets:
build everything from simple primitives (hex prism tiles, boxes, cylinders, cones) in a clean low-poly,
soft-shadow, pastel style on a warm desert ground, similar to an isometric "agent village".

World:
- Hex tile districts from world.json: Suppliers (warehouses + trucks), 6 Plants (factories with 5 small roof
  lights = build slots for the selected day; lit = occupied), Dealers (small shops, use instancing for 50),
  Customers (tiny houses), Human Review desk, Audit office. Name labels on hover.
- 5 robot agents (Coordinator, Supply Chain Planner, Dealer Network, Customer & Quality, Verifier), each with
  its own color and a name tag; idle animation (bob) at the Coordinator HQ.

Playback (from events.json):
- Right sidebar: event feed with category badges (delay amber, outage red, quality purple, noise gray,
  escalated blue, compound teal) and status (queued / working / resolved / escalated / ignored).
- When an event plays: a floating glass card appears above the target ("Supplier delay: battery packs at
  Huntsville - Working", progress bar), the responsible robot walks to each target in order, buildings glow
  (red disrupted, amber rescheduled, green resolved), a truck animates between plants for transfers, small cars
  drive from dealer to customer for loaners, a padlock appears on a lot hold, "STOP SALE" tags on dealers,
  envelopes fly to customer houses for owner notifications, a "?" bubble goes to the Human Review desk for
  escalations, and noise cards fade out with "Ignored - not operational".
- Each step shows its rule id (R3, R5...) in the card. Final card state: "Resolved - 6 orders moved,
  3 dealers notified, 2 loaners" from the trace numbers.
- Controls: Play all, Next event, Pause, speed 1x/2x/4x, OrbitControls camera with a smooth fly-to on each
  target, "Cinematic" toggle that hides UI chrome for screen recording.
- Click any building: side panel with its details for the current event (orders, dealers, customers) and a
  button "Open audit view" linking to the Streamlit app (http://localhost:8501).
Performance: 60 fps on a laptop (instancing, no heavy shadows on 300+ meshes).
Run: cd ui3d; npm install; npm run dev. Open the browser, play all 15 events, and fix anything that overlaps,
clips or looks empty.
```
**Check:** `python -m control_tower.export_ui3d`, then `cd ui3d ; npm install ; npm run dev`. Play all 15 events.
Every animation must match the trace (spot-check 3 events against the Streamlit audit view).

---------------------------------------------------------------------------------------------------
## Emergency prompts

- Agent changed enterprise/: `Revert every change under enterprise/. It is read-only per AGENTS.md rule 3.`
- Hard-coded event logic found: `Search the repo for "E-0" and "E-1" outside traces/tests fixtures. Remove any
  event-id-specific logic; derive behavior from text and tables only.`
- Failed calls in the log: `Here is the failing call and server error: <paste>. Find why the twin did not catch it,
  make the twin/verifier catch it, add a test, then fix the planner.`
- LLM misclassifies: `Improve the system prompt definitions and few-shots for category <x>. Do not reference event
  ids or copy event text. Re-run python -m control_tower.llm --all and show the table.`
