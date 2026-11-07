# Demo video script (about 2.5 minutes)

**0:00-0:15 Problem.** "Wacky Wheels builds cars just in time: no parts inventory. A late shipment or a bad lot
ripples into schedules, dealers, loaner cars and owners. Messages arrive as messy emails and chats. Our control
tower turns each one into exactly the actions the handbook demands, and proves why."

**0:15-0:35 Architecture.** Show `docs/design_card.md` diagram. "One small local LLM, qwen2.5 3B, only classifies
and copies phrases. Everything else is deterministic code: a knowledge graph of 17 thousand nodes, three specialist
agents, a verifier, and a digital twin that dry-runs every plan before the real server sees it."

**0:35-1:50 Live replay (UI, Event operations).** Click **Replay run**; events arrive one by one.
1. **E-09 supplier delay.** Message highlights "Orbit", "surround-view cameras", "Huntsville". Extraction table:
   phrase → id → method. Graph path `P_AL <-RECEIVED_AT- SH-0256 -DELIVERS-> CAM-360 -USED_IN-> SUMMIT <-BUILDS-
   PO-0436 -FULFILLS-> CO ... -SOLD_THROUGH-> D25`. Decisions: 4 same-plant on/after Apr 1, 2 transfers because
   Huntsville is full. Loaner ranking: Platinum first, pool limits respected.
2. **E-01 compound digest.** Two incident tabs (San Antonio outage + Quanta chip delay to Princeton). "next Friday"
   resolved to Mar 19. Shared-resources note: one slot ledger, one notify per dealer, loaners ranked together.
   Before/after heatmap with blocked days outlined.
3. **E-03 quality hold.** "Kestrel ... Thursday Feb 25 through last Monday" → LOT-0130; 110 unsold vehicles stopped
   at 37 dealers, 150 owners contacted. Sold vs in-stock split.
4. **E-02 rumor.** Blue "Escalated" card: missing part, plant, dates, confirmation; exactly one escalate.
   Briefly show a noise card (E-05): "Ignored - not operational", zero calls.

**1:50-2:10 Guardrails + audit.** Verifier tab: plan checks, twin world checks, live read-back, all green.
Audit trail page: filter by rule R5 or dealer D12, download CSV. Human review inbox: approve E-13.

**2:10-2:25 Self-check.** Terminal: `python eval/self_check.py --log runs/run1/action_log.jsonl` → 15/15 green,
961 calls, 0 failed. Knowledge graph page: schema PNG, Turtle and GraphML downloads.

**2:25-2:30 Close.** "LLM reads, code decides. Zero failed calls, every action cites a rule and a graph path."
