# Voiceover script (timed to chapter clips)

Speak at about 140 words per minute. Digits as you would say them. No em dashes.
Slide chapters are placeholders - swap in your PowerPoint.

Judging keys: **A** action accuracy · **E** explainability · **G** guardrails / HITL · **F** efficiency (0 failed) · **U** UX

---

## 00 [SLIDE] Title
"Hack the Highway. Wacky Wheels Control Tower. The LLM reads, code decides."

## 01 [SLIDE] Problem
"We build cars just in time. There is no parts inventory. A late shipment, a plant outage, or a bad lot ripples into schedules, dealers, loaners, and owners. Messages arrive as messy emails and chats."

## 02 [SLIDE] Architecture
"One small local model only classifies and copies phrases. Everything else is deterministic: a knowledge graph, specialist agents, a verifier, and a digital twin that dry-runs every plan before the real server sees it."

## 03 Official run  **A F**
"Here is the official pipeline command from the README, running live. Events move through extract, resolve, gate, plan, verify, twin, execute, and read-back.
Then the independent self-check and the test suite.
Read the final line: every scored event green, the write count from the run, zero failed calls, and the pytest total."

## 04 Event operations overview  **U E**
"This is the Event Operations desk after the scored run.
On the KPI strip: the event count equals actionable plus escalated plus noise. The incident count is higher than actionable events because E-01 is compound and carries two incidents.
Point at the model name and the LLM call and token line.
Click Replay run and watch the feed arrive one by one."

## 05 E-09 supplier delay  **A E**
"Open E-09. Highlight Orbit, surround-view cameras, and Huntsville in the message.
The extraction table shows the LLM copying phrases. The method column shows code resolving them to ids.
Open Excluded on purpose - rule 10.
Open Schedule before/after and scroll to the heatmap so blocked days are visible.
Open the Action log and cite three rows with their rules.
Open Verifier and show plan checks and twin world checks, all green."

## 06 E-01 compound  **A E**
"E-01 is one message with two incidents. Open both sub-incident tabs.
Highlight next Friday in the message, then the resolved date, then the sidebar switch NEXT_WEEKDAY equals following_week.
Show one slot ledger for the whole event, and one merged dealer notify in the action log."

## 07 E-03 quality  **A**
"Quality hold. Show vehicles stopped and owners contacted.
In the Action log highlight hold_lot, stop_sale, and notify_customer with their rules."

## 08 E-05 noise  **G F**
"Noise. The panel says Ignored - not operational, handbook rule 7.
The Action log is empty. Zero tool calls."

## 09 Guardrail  **G**
"Open the Guardrail details. The grounding check rejected ungrounded LLM text. Code made the decision."

## 10 Human review  **G U**
"E-02 is escalated under rule 8 with missing-field chips.
In the Human review inbox, type a note, click Approve.
Say clearly: this page never calls the enterprise server."

## 11 Knowledge graph  **E**
"Ontology diagram, then zoom on node and edge counts from the export stats.
Tie it back to an incident graph path."

## 12 Ask the control tower  **U E**
"Type a live question. Show the answer and which read-only functions ran."

## 13 Live Incident Desk  **A G**
"Paste a brand-new supplier delay that is not one of the 15.
Watch extract, resolve, plan, and verify on the twin.
Highlight: simulation, nothing sent."

## 14 Scenario Lab and What-if  **A U**
"Glance at Scenario Lab.
In What-if, run Scenario A as a plant outage on P_NC for March 8 to 12.
Run Scenario B as a different case - longer window or quality hold.
Show the side-by-side diff: orders, units, Platinum and Gold, dealers, loaners needed versus available.
Label: simulation, not executed."

## 15 Policy Studio  **G E**
"handbook_v1 is the locked scored baseline.
Make a small draft change, click Preview impact, zoom the diff.
Publish a new version on the demo copy.
Say: the official run still refuses edited profiles unless you pass --policy."

## 16 Audit trail  **E U**
"Filter Rule to R5, then a dealer. Show the row count change and reason text. Click Download CSV."

## 17 Operations health  **F U**
"Per-stage timing chart from traces: extract through read-back.
Totals, slowest events, cache hit rate, failure count zero, model used."

## 18 Daily briefing  **U**
"Scroll the business summary.
Click Download one-page PDF and show the PDF."

## 19 [SLIDE] Results  **A F**
"Read the auto card: events green, writes, failed calls, tests, model, graph size."

## 20 [SLIDE] Close
"Repo link. Team. The LLM reads, code decides."
