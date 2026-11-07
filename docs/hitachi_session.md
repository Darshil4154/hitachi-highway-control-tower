# Hitachi Q&A sessions: answers, decisions, next questions

## Session 1: what Hitachi said, and what we did with it

| Our question | Hitachi's answer (paraphrased from the call) | Effect on our run (`docs/what_if_report.md`) | Decision |
|---|---|---|---|
| No free same-plant slot: transfer to the earliest slot, even before the disruption ends? | "If there are no free slots available then definitely the earliest slot should be considered." | Our default already takes the earliest free slot from today (`TRANSFER_LOWER_BOUND=today`). The alternative (on/after restart) would move 5 transfers (PO-0442, PO-0444 in E-09; PO-0259, PO-0260, PO-0261 in E-11) from Mar 8 to Mar 31 / Apr 1. | Keep `today`. |
| Earliest day across all plants, or plant by plant? | "You go plant by plant." | New switch `TRANSFER_SEARCH=plant_first`. On this data it produces **identical writes** (0 changes), so either reading scores the same. | Keep `day_first`; answer is moot for scoring. |
| Two incidents at once: one plan or two? How are notifications handled? | "It's a different plan ... you can notify both of them ... they'll have their own graph to traverse." For the hackathon, "process it in sequence". In the real world, weigh units and impact. | We already process incidents in sequence with one shared slot ledger. Per-incident notification (`NOTIFY_SCOPE=per_incident`) would send **15 extra `dealer.notify`** in E-01 (15 dealers are hit by both the San Antonio outage and the Princeton chip delay). Handbook R4 says "exactly one `dealer.notify`" per dealer. | Keep `per_event` (handbook wording); confirm in session 2. |
| Several affected orders compete for one free slot: who goes first? | "Delivery first would be the priority" ... "round robin or a weighted approach" ... "we are assessing your thought process". | New switch `SLOT_PRIORITY=promised_date`. Only E-11 changes: PO-0256 and PO-0258 (both P_MS, both built Mar 29) swap Apr 1 / Apr 2, because PO-0258 has an order promised Mar 31. 2 reschedules + 14 notification texts. | Keep `build_date` for scoring (deterministic, handbook-neutral); show the delivery-first variant as business thinking; confirm in session 2. |
| Deliverables | Video, architecture diagram, PPT; DevOps angle. | `docs/make_deck.py` builds `docs/architecture.png` and `docs/control_tower_deck.pptx`. | Done. |

Every switch value is tested: `tests/test_switches_and_guards.py` runs all 15 events under each alternative and
asserts zero failed calls and 15/15 green in both the verifier and the independent self-check, so a confirmed
answer is a one-line change in `control_tower/config.py` plus one clean run with a new `--out` folder.

## Session 2: cross-questions to ask

Ask the scoring ones first, with the concrete example in hand.

**Scoring (these change actions)**

1. "R4 says every dealer gets exactly one `dealer.notify`. In the morning digest (E-01) 15 dealers are affected by
   both the outage and the supplier delay. Does the scorer expect one notification per dealer for the event, or one
   per incident (30 instead of 15)?"
2. "For orders competing for the same slot, does the scorer order them by original build date, or by customer
   promise date? In E-11 this only swaps PO-0256 and PO-0258 between Apr 1 and Apr 2."
3. "To confirm: a transferred order may go to another plant today (Mar 8), before the disruption at its own plant
   ends? That is how we read 'on any day with a free slot'."
4. "'Next Friday' said on Monday Mar 8: we read it as Mar 19 (the following week). With Mar 12 the digest's new ETA
   would be before the original ETA, so we think Mar 19 is intended. Correct?"
5. "Is accuracy scored per action or per event? Is there partial credit when most actions in an event are right?"
6. "Do free read calls (`mes.get_schedule`, `crm.loaner_availability`) count toward efficiency at all? We use 193 of
   them as read-back checks."

**Thought process (Hitachi said this matters)**

7. "If we had to weigh two simultaneous incidents in production, we would rank by units at risk, customers with a
   promise inside the disruption, and Platinum/Gold exposure. Is that the kind of weighting you use?"
8. "When the same-plant slot keeps the plant but breaks the promise date, and a transfer keeps the promise but adds
   logistics cost, which wins in your operations?"
9. "Our LLM's free-text rationales were wrong in 4 of 15 events (it copied wording from its examples), so decision
   reasons are written by code and the rationale is only a checked note. Would you accept an LLM explanation in an
   audit trail, or must every reason be reproducible?"
10. "For DevOps: we ship one command per step, cached LLM outputs for exact reproduction, a digital-twin dry run,
    and a self-check report. What would you need in CI before trusting this in production (approval gates for
    high-impact actions, monitoring, rollback)?"

**Submission**

11. "Is a local 3B model through Ollama acceptable for the judged run, and should we include the LLM cache so you can
    reproduce without the model?"
12. "How long is the video, and should the PPT follow a template? Is the architecture diagram separate from the
    deck?"
