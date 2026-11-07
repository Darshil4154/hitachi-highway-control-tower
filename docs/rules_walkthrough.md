# How each handbook rule is implemented

Source of truth: `enterprise/data/policy_handbook.md`. Rule ids `R1`..`R10` are defined in `control_tower/policy.py`
and cited on every planned action (`rule_id`) and in `traces/audit_log.csv`. Every rule is checked twice: once by
the verifier before execution (`control_tower/verifier.py`, computed from the tables, not from the planners) and
once after the run by `eval/self_check.py` (a separate minimal re-implementation replaying the action log).

**R1 Supplier delay.** *"Builds that need the delayed part cannot run from the original ETA up to (but not
including) the new ETA ... A production order needs a part if its model's bill of materials includes it, and only
at the receiving plant."*
`SupplyChainPlanner.resolve_delay` (`agents/supply_chain.py`) finds and validates the shipment
(`KnowledgeGraph.find_shipment`; explicit `SH-` ids are checked against part, plant, supplier and ETA).
`SupplyChainPlanner.delay_incident` calls `KnowledgeGraph.orders_needing_part(part, plant, orig, new)`
(`ontology.py`), which walks `Part -USED_IN-> Model <-BUILDS- ProductionOrder -SCHEDULED_AT-> Plant` with a half-open
`[orig, new)` window. The block applies only to models whose BOM has the part. Restart = new ETA.

**R2 Plant outage.** *"No builds at the plant during the outage (inclusive) ... the plant restarts the next working
day."* `SupplyChainPlanner.outage_incident` uses `KnowledgeGraph.orders_at_plant(plant, start, end)` (inclusive on
both ends), blocks every model at that plant, restart = `next_working_day(end)`.

**R3 Rescheduling.** *"Move each affected production order to the earliest feasible slot. At the same plant the new
day must be at or after the end of the disruption ... If no same-plant slot is free, transfer the order to another
plant that builds the model on any day with a free slot. Never move orders that are not affected."*
`SupplyChainPlanner.plan_moves` / `_place` with one `SlotLedger` per event (capacity = `slots_per_day`, blocks from
every incident of the event). Orders are placed in (original build date, id) order: first the earliest same-plant
day ≥ restart that is free and not blocked (`mes.reschedule`), else the earliest day at another plant that can build
the model (`plant_models.csv`), ties broken by `plants.csv` order (`mes.transfer`). No slot → one `escalate`
(`config.NO_SLOT_ACTION`). Verifier: `R3 earliest feasible slot chosen`, `no slot over capacity`, `no move into a
blocked day`, `same-plant moves on/after restart`, `transfers go to another plant that builds the model`.

**R4 Dealer notification.** *"Every dealer with at least one affected customer order gets exactly one
dealer.notify listing those customer order ids, and only those."* `DealerNetwork.plan_notifications`
(`agents/dealer_network.py`) groups all affected customer orders of the event (merged across incidents) by dealer
and emits one call per dealer with sorted ids and the new date/plant per order.

**R5 Loaners.** *"A customer in tier Platinum or Gold gets one loaner from their dealer's pool ... the priority is
Platinum before Gold, then the earlier promised date, then the lower customer order id. Standard customers get no
loaner."* The coordinator reads each live pool with the free `crm.loaner_availability` tool;
`CustomerCareQuality.plan_loaners` (`agents/customer_quality.py`) ranks eligible orders per dealer by
(tier, promised date, id) across all incidents of the event and assigns the top `pool`. Skipped and Standard orders
are recorded in the trace with reasons.

**R6 Quality hold.** *"Hold the lot. The affected vehicles are the finished vehicles built at that plant, on the
lot's build dates, from production orders of models that use the part. Unsold vehicles (in_stock) are stopped from
sale at their dealer. For sold vehicles, contact the owner."* `CustomerCareQuality.resolve_lot` validates an explicit
lot id or finds the lot whose build dates equal the message window (`KnowledgeGraph.find_lots`);
`CustomerCareQuality.plan_quality` uses `KnowledgeGraph.vehicles_for_lot` (`PartLot -LOT_OF-> Part -USED_IN-> Model
<-BUILDS- ProductionOrder <-BUILT_FROM- Vehicle`) → `quality.hold_lot`, `DealerNetwork.plan_stop_sales` (one call per
dealer, in_stock only), and one `crm.notify_customer` per distinct owner.

**R7 Noise.** *"Do nothing operational. Do not call any write tool."* `llm.gate` returns `noise`; the coordinator
makes no call, and `ToolsClient._guard` (`tools_client.py`) raises `WriteBlocked` for any write or escalate on a
noise event.

**R8 Unconfirmed or unclear.** *"Do not take any operational action. Use escalate."* `llm.gate` returns
`unconfirmed` (LLM category or hedge words + missing specifics) or `needs_review` (missing required fields, fuzzy-only
match, weekday/date mismatch, shipment/lot that does not match). `Coordinator._escalate_only` makes exactly one
`escalate` listing the missing fields; the write guard blocks everything else.

**R9 Completeness.** *"A real incident should end with at least three different kinds of action."* Verifier check
`R9 at least three different kinds of action` (non-blocking warning; we never invent actions to reach three).

**R10 Do not touch what is not affected.** Verifier `R10 only affected orders are moved` recomputes the affected set
from the tables; the planner only ever iterates over the affected set. Excluded candidates (e.g. "RANGER does not use
CAM-360", "already built") are listed per incident in the trace.
