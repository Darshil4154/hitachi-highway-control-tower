# Technical Spec - Wacky Wheels Control Tower

Read `AGENTS.md` first. This spec defines exact behavior. Interpretations of ambiguous handbook
points live in `control_tower/config.py` (section 9) so they can be flipped in one place after
organizers answer on Discord.

---------------------------------------------------------------------------------------------------
## 1. Data model and calendar (`data_loader.py`)

Load every CSV in `enterprise/data/` into typed records (dataclasses or pandas, but expose plain dicts/lists
to the rest of the code). Tables and keys:

| Table | Key | Notes |
|---|---|---|
| plants | plant_id | slots_per_day (int). Keep file order: it is the plant tie-break order |
| plant_models | (plant_id, model) | which plant can build which model |
| models | model | segment |
| parts | part_id | name, category |
| bom | (model, part_id) | model -> set(parts) |
| suppliers | supplier_id | name, city |
| inbound_shipments | shipment_id | supplier_id, part_id, plant_id, eta_date, covers_days |
| production_orders | production_order_id | plant_id, build_date, model, units |
| customer_orders | customer_order_id | production_order_id, dealer_id, customer_id, model, promised_date |
| customers | customer_id | name, tier (Platinum / Gold / Standard) |
| dealers | dealer_id | name, city, region, transit_days |
| loaners | dealer_id | loaners_available (initial pool) |
| part_lots | lot_id | part_id, supplier_id, plant_id, first_build_date, last_build_date |
| finished_vehicles | vin | production_order_id, model, plant_id, build_date, dealer_id, status (sold / in_stock), customer_id |
| aliases | alias | entity_type (plant/part/supplier), entity_id |
| calendar | day_index | date, weekday. Index -10 .. 19, Mon-Fri only |

Calendar helpers (mirror `enterprise.py` exactly; you may import its `idx_to_date` / `date_to_idx`):
- `TODAY = 2027-03-08` (index 0), `LAST = 2027-04-02` (index 19).
- `working_days(start, end)` inclusive list of weekday dates.
- `next_working_day(d)`.
- Weekend handling: a range "from Fri through Mon" covers Fri and Mon only (no weekend builds exist).

---------------------------------------------------------------------------------------------------
## 2. Ontology / knowledge graph (`ontology.py`)

networkx `MultiDiGraph`. Node id format `"Type:id"`, e.g. `"Plant:P_KY"`, `"ProductionOrder:PO-0123"`.
Every node has `type`, `label`, and its row attributes.

Node types: Supplier, Part, Model, Plant, Shipment, PartLot, ProductionOrder, CustomerOrder, Customer,
Dealer, Vehicle, LoanerPool, Alias, Event, Incident (Event/Incident are added per run for traces).

Edges (name them exactly like this everywhere: code, traces, UI, diagram):
| Edge | From -> To |
|---|---|
| SUPPLIES | Supplier -> Part |
| SENT_BY | Shipment -> Supplier |
| DELIVERS | Shipment -> Part |
| RECEIVED_AT | Shipment -> Plant |
| USED_IN | Part -> Model (from bom.csv) |
| CAN_BUILD | Plant -> Model |
| SCHEDULED_AT | ProductionOrder -> Plant |
| BUILDS | ProductionOrder -> Model |
| FULFILLS | ProductionOrder -> CustomerOrder |
| SOLD_THROUGH | CustomerOrder -> Dealer |
| ORDERED_BY | CustomerOrder -> Customer |
| LOT_OF | PartLot -> Part |
| LOT_FROM | PartLot -> Supplier |
| INSTALLED_AT | PartLot -> Plant |
| BUILT_FROM | Vehicle -> ProductionOrder |
| AT_DEALER | Vehicle -> Dealer |
| OWNED_BY | Vehicle -> Customer (sold only) |
| HAS_POOL | Dealer -> LoanerPool |
| REFERS_TO | Alias -> Supplier/Part/Plant |
| MENTIONS | Event -> any resolved entity (runtime) |
| AFFECTS | Incident -> ProductionOrder / Vehicle (runtime) |

Traversal functions (pure, deterministic, return ids AND the path edges used, for traces):
- `orders_needing_part(part_id, plant_id, date_from, date_until_excl)` - R1
- `orders_at_plant(plant_id, date_from, date_to_incl)` - R2
- `customer_orders_of(po_ids)` -> list of CO rows
- `vehicles_for_lot(lot_id)` - R6: vehicles at lot.plant with build_date in [lot.first, lot.last] whose model's BOM
  contains lot.part
- `find_shipment(supplier_id?, part_id, plant_id, eta_date?)`
- `find_lots(part_id, plant_id, supplier_id?, window_from?, window_to?)`
- `explain_path(...)` -> human string like `SH-0182 -[DELIVERS]-> CAM-360 -[USED_IN]-> VOYAGER -[BUILDS]<- PO-0412 ...`

Exports (for the 20% graph score and the submission):
- `exports/ontology_schema.png` (node types + edge names, drawn with graphviz or matplotlib)
- `exports/knowledge_graph.graphml` (full instance graph)
- `exports/ontology.ttl` (RDF/Turtle via rdflib: classes, object properties, a few instances) - the "semantic layer"
- `exports/graph_stats.json` (counts per node/edge type)

---------------------------------------------------------------------------------------------------
## 3. Resolvers (`resolvers.py`)

### 3.1 Entity resolution
Order of attempts for each mention; record the method used in the trace:
1. Exact id in text (regex): `P_[A-Z]{2}`, `SUP-\d{2}`, `SH-\d{4}`, `LOT-\d{4}`, `PO-\d{4}`, part ids from parts.csv.
2. `aliases.csv` exact, case-insensitive, longest match first (e.g. "heavy-duty wiring harness" -> HARN-B).
3. Name fields: plant name/city, supplier name (first word, e.g. "Orbit Optics" -> Orbit), part name (singular/plural
   normalization: "60 kWh battery packs" == "60 kWh battery pack").
4. Fuzzy (rapidfuzz) with threshold >= 90 ONLY as a suggestion; a fuzzy-only match makes the incident
   `needs_review` -> escalate instead of acting.

### 3.2 Date resolution (today = Monday 2027-03-08)
| Phrase | Rule | Example -> result |
|---|---|---|
| ISO `2027-03-24` | literal | 2027-03-24 |
| `Mar 22`, `March 22`, `Monday Mar 22` | literal in 2027; if a weekday is given it must match, else flag | Mon Mar 22 |
| `next <weekday>` | that weekday in the NEXT calendar week (week of Mon 2027-03-15) | next Friday -> 2027-03-19 |
| `this <weekday>` or bare `<weekday>` (no date) | that weekday in the current week, on or after today | Wednesday -> 2027-03-10 |
| `last <weekday>` | that weekday in the PREVIOUS calendar week | last Monday -> 2027-03-01 |
| `today` / `tomorrow` / `yesterday` | +0 / +1 / -1 working-day aware | |
| `<weekday> <Mon> <dd>` with past date | literal (quality windows are in the past) | Thursday Feb 25 -> 2027-02-25 |

Self-consistency check supporting the `next <weekday>` rule: event text "can't make it next Monday ... next Friday now"
must resolve to Mon 03-15 then Fri 03-19 (new ETA after original ETA). Put this in a unit test as a sanity rule
(new ETA must be after original ETA; outage end must be >= start) - if violated, try the alternative interpretation
from config, else escalate.

---------------------------------------------------------------------------------------------------
## 4. LLM extraction (`llm.py`)

- OpenAI-compatible chat client. Default: Ollama at `http://localhost:11434/v1`, model `qwen2.5:7b-instruct`
  (fallback `qwen2.5:3b-instruct` on slow laptops). Any OpenAI-compatible endpoint works via env vars.
- temperature 0, JSON output, cache by sha256(model + prompt + event text) in `cache/llm/<hash>.json`.
- One call per event (efficiency). Retry once on invalid JSON with the validation error appended; then fall back
  to the regex extractor and mark `llm_fallback: true`.

Output schema (validate with pydantic):
```json
{
  "category": "incident | noise | unconfirmed",
  "confidence": 0.0,
  "rationale": "one sentence",
  "incidents": [
    {
      "type": "supplier_delay | plant_outage | quality_hold",
      "evidence_quote": "exact substring of the message for this incident",
      "supplier_mention": "Orbit | null",
      "part_mention": "surround-view cameras | null",
      "plant_mention": "Huntsville | null",
      "shipment_id": "SH-0182 | null",
      "lot_id": "LOT-0191 | null",
      "original_eta_phrase": "Monday Mar 29 | null",
      "new_eta_phrase": "Thursday Apr 1 | null",
      "start_phrase": "next Tuesday | null",
      "end_phrase": "next Thursday | null",
      "window_from_phrase": "Thursday Feb 25 | null",
      "window_to_phrase": "last Monday | null",
      "is_confirmed": true
    }
  ]
}
```
Prompt rules: return phrases exactly as written (no date math, no id guessing); one incident object per incident
(a "digest" with (1) and (2) yields 2); category `noise` when not about our supply, plants, quality or customers;
`unconfirmed` when it is a rumor, vague, unspecific, or explicitly unconfirmed. Include 3 short few-shot examples
written by us (NOT copies of the 15 events).

### Deterministic gate after the LLM (coordinator)
- `noise` -> no calls at all. Trace reason.
- `unconfirmed` -> exactly one `escalate` with a reason listing missing fields. No writes.
- `incident` but required fields cannot be resolved -> `escalate` (needs_review), no writes.
  Required: delay = part + plant + new ETA + (original ETA or shipment id); outage = plant + start + end;
  quality = lot id, or part + plant + window.
- Hedge-word detector (rumor, may, might, possible, unconfirmed, someone mentioned, not confirmed) combined with
  missing specifics overrides to `unconfirmed` even if the LLM said incident.

---------------------------------------------------------------------------------------------------
## 5. Specialist algorithms

### 5.1 Supply Chain Planner (R1, R2, R3)
Shipment resolution for a delay: match shipments on part + plant (+ supplier if given) with `eta_date == original ETA`.
If a shipment id is given, validate it against part/plant/ETA; mismatch -> escalate. If the original ETA is missing
but exactly one shipment matches part+plant with eta < new ETA and eta >= today, use it, else escalate.

Disruption window per incident:
- delay: blocked days = working days in [original ETA, new ETA) at the receiving plant, only for models whose BOM
  has the part. Restart (same-plant lower bound) = new ETA.
- outage: blocked days = working days in [start, end] at the plant for all models. Restart = next working day
  after end.
- Clamp to the planning window: only orders with build index >= 0 can move (past orders are already built).

Slot ledger (shared across ALL incidents of the same event):
- initial occupancy = all future production orders per (plant, day index), exactly as `enterprise.Enterprise.state`.
- capacity = slots_per_day. Moving an order frees its old slot and takes the new one.
- `blocked(plant, day, model)` = True if ANY incident in this event blocks that plant/day for that model. A candidate
  slot must not be blocked.

Rescheduling (for each affected order, sorted by original build date then production_order_id):
1. Same plant: first day d in [restart .. 19] with free capacity and not blocked -> `mes.reschedule`.
2. Else transfer: candidate plants that build the model, excluding the origin, in plants.csv order; candidate days
   in [TRANSFER_LOWER_BOUND .. 19] (config, default index 0 = today, per handbook wording "on any day with a free slot");
   pick the earliest day, tie-break by plant order -> `mes.transfer`.
3. Else: no feasible slot -> keep order, add an `escalate` for that order with reason (human decision), and still
   notify dealers (orders are still delayed). Record in trace.

Compound events: process incidents in message order (config `COMPOUND_ORDER`), all sharing one ledger.

### 5.2 Dealer Network (R4, R6 stop sale)
- affected customer orders = all customer orders whose production_order_id is in the union of affected orders
  across all incidents of the event (even if the new date still meets the promise).
- One `dealer.notify` per dealer per EVENT (merge incidents), args: dealer_id, sorted customer_order_ids, message:
  short human text with reason and new build date/plant per order.
- Quality: group affected in_stock VINs by dealer -> one `dealer.stop_sale` per dealer with sorted VINs.

### 5.3 Customer Care & Quality (R5, R6)
Loaners:
- eligible = affected customer orders whose customer tier in {Platinum, Gold}.
- per dealer, live pool = `crm.loaner_availability(dealer_id)` (read tool, free) or the twin state.
- rank by (tier rank Platinum=0 Gold=1, promised_date asc, customer_order_id asc); assign top `pool` ->
  `crm.assign_loaner(customer_order_id)`. Others recorded as `skipped: pool exhausted`.
- Standard tier: nothing (dealer was told).
- Compound: rank all eligible orders from all incidents together per dealer.

Quality hold:
- Lot resolution: if `lot_id` given, validate part/plant/supplier/window consistency. Else `find_lots(part, plant,
  supplier?)` whose [first_build_date, last_build_date] equals the message window; if none equal, lots fully inside
  the window; if still none or ambiguous -> escalate.
- `quality.hold_lot(lot_id)`.
- affected vehicles = `vehicles_for_lot(lot)`. in_stock -> stop sale (via Dealer Network). sold ->
  one `crm.notify_customer(customer_id, message)` per distinct owner (sorted).
- No rescheduling, no loaners, no dealer.notify for quality holds (not in R6).

---------------------------------------------------------------------------------------------------
## 6. Execution pipeline (coordinator) and guardrails

```
event -> LLM extract -> resolve entities/dates -> gate (noise / unconfirmed / needs_review)
      -> specialists build a PLAN (list of planned actions with rule_id, reason, evidence_path)
      -> verifier.check_plan(plan)              # static policy checks
      -> twin.apply(plan)                       # local Enterprise copy, must be 0 errors
      -> verifier.check_world(twin)             # post-state invariants
      -> tools_client.execute(plan)             # real server, ordered: reschedule/transfer, notify, loaners,
                                                #   hold_lot, stop_sale, notify_customer
      -> read-back verification (mes.get_schedule on touched days, loaner availability)
      -> trace.write(event)
```
Verifier invariants (fail = do not execute, escalate instead):
- every moved order is in the affected set (R10); every affected order was moved or escalated (R3)
- no slot over capacity; no move into a blocked day; same-plant moves are >= restart; transfers go to a plant that
  builds the model
- exactly one notify per dealer, ids exactly equal to that dealer's affected customer orders (R4)
- loaners: only Platinum/Gold, within pool, priority order respected (R5)
- quality: exactly the lot, all in_stock affected VINs stopped at the right dealer, all sold owners notified (R6)
- noise: zero calls; unconfirmed: exactly one escalate (R7, R8)
- incident completeness: >= 3 distinct write tool kinds, else trace warns (R9) - never invent actions to reach 3
Tool client: on HTTP error, log it, do not blindly retry writes; re-read state (free) to decide.

---------------------------------------------------------------------------------------------------
## 7. Trace schema (`traces/<event_id>.json`)
```
event{event_id, source, received_at, text}
classification{category, confidence, rationale, llm_model, llm_fallback}
incidents[]{incident_id, type, evidence_quote,
  extracted[]{phrase, resolved, method},             # alias table, regex, date rule name
  validation[]{check, ok},
  disruption{plant_id, blocked_from, blocked_until_excl | to_incl, restart, models_blocked},
  graph_path{nodes[], edges[[src, EDGE, dst]], text},
  affected{production_orders[], customer_orders[], dealers[], customers[], lots[], vehicles_unsold[], vehicles_sold[]},
  excluded[]{id, reason},                            # e.g. "PO-x RANGER does not use CAM-360"
  decisions{reschedule[]{po, from, to, kind, reason}, loaners[]{co, tier, promised, rank, decision, reason}}}
shared_resources{processing_order, slot_ledger_note, loaner_ledger_note}   # compound only
plan[]{seq, agent, tool, args, rule_id, reason, evidence_path, incident_id}
verifier{plan_checks[]{name, ok, detail}, world_checks[]{...}}
actions[]{seq, agent, tool, args, ok, error, kind(read|write), ts}
escalation{escalated, reason, missing_fields[]}
summary  (2-3 sentences for a business reader; may be LLM-written from the trace, never the source of facts)
metrics{llm_calls, llm_model, prompt_tokens, completion_tokens, tool_calls, reads, writes, failed, runtime_s}
```
Also write `traces/run_summary.json` (one row per event) and `traces/audit_log.csv` (one row per action with rule
citation) for auditors.

---------------------------------------------------------------------------------------------------
## 8. Control tower UI (`ui/app.py`, Streamlit) - reads only traces/ and exports/
Pages / sections:
1. **Header KPIs:** events, incidents handled, escalations, noise filtered, writes, failed calls (0), model used.
2. **Event feed:** cards with source icon, time, category badge (delay / outage / quality / noise / escalated /
   compound), one-line summary. Filters by category.
3. **Event detail:** original message with highlighted evidence quotes and resolved entities (chips); extraction
   table (phrase -> id -> method); interactive graph path (pyvis or streamlit-agraph) with the event's subgraph,
   nodes colored by type, path edges highlighted; decisions table (old slot -> new slot, reason, rule); loaner
   ranking table (assigned vs skipped); action log with rule citations and OK ticks; verifier checklist (green);
   summary.
4. **Before / after schedule:** heatmap plant x day of slot utilization before and after the event (twin snapshots).
5. **Human-in-the-loop inbox:** escalations with "missing info" card and Approve / Dismiss buttons (stored locally,
   do not call the server again).
6. **Audit trail:** filterable table from audit_log.csv, export button.
7. **Ontology:** schema diagram + stats + link to ontology.ttl.
8. (Stretch) **Ask the control tower:** natural language questions answered by read-only graph query functions
   chosen by the LLM (tool calling), e.g. "Which Platinum customers at D12 lack a loaner after E-10?".
Personas for copy and design card: Production Planner, Dealer Relations Manager, Customer Care Lead, Quality Engineer,
Auditor.

---------------------------------------------------------------------------------------------------
## 9. Interpretation switches (`config.py`) - confirm on Discord, default first
| Key | Default | Alternative | Why |
|---|---|---|---|
| NEXT_WEEKDAY | "following_week" | "nearest_upcoming" | "next Monday ... next Friday" consistency |
| TRANSFER_LOWER_BOUND | "today" (idx 0) | "restart" | handbook: transfer "on any day with a free slot" |
| PLANT_TIEBREAK | "plants_csv_order" | "plant_id_alpha" | earliest day first, then this |
| COMPOUND_ORDER | "message_order" | "earliest_disruption_first" | shared ledger order |
| NOTIFY_SCOPE | "per_event" | "per_incident" | R4 "exactly one" per dealer |
| NO_SLOT_ACTION | "escalate" | "skip" | no feasible slot in window |
| QUALITY_DEALER_NOTIFY | False | True | R6 lists only hold, stop sale, owner contact |
| ESCALATE_NOISE | False | - | R7 says do nothing |
Print the active interpretation set into every trace (`config_snapshot`) and the design card.

---------------------------------------------------------------------------------------------------
## 10. Submission checklist
- `runs/final/action_log.jsonl` from ONE clean server run over all 15 events.
- Source code (this repo), README with run steps, model cited.
- `traces/*.json` (15) + run_summary + audit_log.csv.
- `exports/ontology_schema.png`, `knowledge_graph.graphml`, `ontology.ttl`.
- `docs/design_card.md` (one page: architecture, LLM vs code table, guardrails, evaluation, improvements, model).
- Demo video (2-3 min) or screenshots: events arriving, graph path, agents acting, audit trail, HITL inbox.
