# Self-check report

Log: `runs/run1/action_log.jsonl` replayed on a fresh `enterprise.Enterprise`. Expected sets are recomputed by an independent minimal implementation of the handbook rules (no control_tower code).

| event | gate | calls | writes | failed | checks | result |
|---|---|---|---|---|---|---|
| E-01 | incident | 126 | 81 | 0 | 10/10 | PASS |
| E-02 | unconfirmed | 1 | 0 | 0 | 1/1 | PASS |
| E-03 | incident | 188 | 188 | 0 | 10/10 | PASS |
| E-04 | incident | 96 | 59 | 0 | 10/10 | PASS |
| E-05 | noise | 0 | 0 | 0 | 1/1 | PASS |
| E-06 | noise | 0 | 0 | 0 | 1/1 | PASS |
| E-07 | noise | 0 | 0 | 0 | 1/1 | PASS |
| E-08 | incident | 71 | 46 | 0 | 10/10 | PASS |
| E-09 | incident | 64 | 42 | 0 | 10/10 | PASS |
| E-10 | incident | 44 | 28 | 0 | 10/10 | PASS |
| E-11 | incident | 94 | 62 | 0 | 10/10 | PASS |
| E-12 | incident | 43 | 27 | 0 | 10/10 | PASS |
| E-13 | unconfirmed | 1 | 0 | 0 | 1/1 | PASS |
| E-14 | incident | 131 | 131 | 0 | 10/10 | PASS |
| E-15 | incident | 102 | 102 | 0 | 10/10 | PASS |

**Total:** 15 events, 961 calls, 0 failed, 15/15 events fully green.

## Checks per event

- **E-01** (incident): OK R10 no unaffected order moved, OK R1/R2 every affected order moved, OK R3 final slots equal independent greedy, OK R4 one notify per dealer, exact ids, OK R5 loaners exactly as handbook priority, OK R6 lot(s) held, OK R6 unsold vehicles stopped, OK R6 owners contacted, OK R9 >= 3 kinds of action, OK zero failed calls
- **E-02** (unconfirmed): OK unconfirmed: exactly one escalate, no writes
- **E-03** (incident): OK R10 no unaffected order moved, OK R1/R2 every affected order moved, OK R3 final slots equal independent greedy, OK R4 one notify per dealer, exact ids, OK R5 loaners exactly as handbook priority, OK R6 lot(s) held, OK R6 unsold vehicles stopped, OK R6 owners contacted, OK R9 >= 3 kinds of action, OK zero failed calls
- **E-04** (incident): OK R10 no unaffected order moved, OK R1/R2 every affected order moved, OK R3 final slots equal independent greedy, OK R4 one notify per dealer, exact ids, OK R5 loaners exactly as handbook priority, OK R6 lot(s) held, OK R6 unsold vehicles stopped, OK R6 owners contacted, OK R9 >= 3 kinds of action, OK zero failed calls
- **E-05** (noise): OK noise: zero calls
- **E-06** (noise): OK noise: zero calls
- **E-07** (noise): OK noise: zero calls
- **E-08** (incident): OK R10 no unaffected order moved, OK R1/R2 every affected order moved, OK R3 final slots equal independent greedy, OK R4 one notify per dealer, exact ids, OK R5 loaners exactly as handbook priority, OK R6 lot(s) held, OK R6 unsold vehicles stopped, OK R6 owners contacted, OK R9 >= 3 kinds of action, OK zero failed calls
- **E-09** (incident): OK R10 no unaffected order moved, OK R1/R2 every affected order moved, OK R3 final slots equal independent greedy, OK R4 one notify per dealer, exact ids, OK R5 loaners exactly as handbook priority, OK R6 lot(s) held, OK R6 unsold vehicles stopped, OK R6 owners contacted, OK R9 >= 3 kinds of action, OK zero failed calls
- **E-10** (incident): OK R10 no unaffected order moved, OK R1/R2 every affected order moved, OK R3 final slots equal independent greedy, OK R4 one notify per dealer, exact ids, OK R5 loaners exactly as handbook priority, OK R6 lot(s) held, OK R6 unsold vehicles stopped, OK R6 owners contacted, OK R9 >= 3 kinds of action, OK zero failed calls
- **E-11** (incident): OK R10 no unaffected order moved, OK R1/R2 every affected order moved, OK R3 final slots equal independent greedy, OK R4 one notify per dealer, exact ids, OK R5 loaners exactly as handbook priority, OK R6 lot(s) held, OK R6 unsold vehicles stopped, OK R6 owners contacted, OK R9 >= 3 kinds of action, OK zero failed calls
- **E-12** (incident): OK R10 no unaffected order moved, OK R1/R2 every affected order moved, OK R3 final slots equal independent greedy, OK R4 one notify per dealer, exact ids, OK R5 loaners exactly as handbook priority, OK R6 lot(s) held, OK R6 unsold vehicles stopped, OK R6 owners contacted, OK R9 >= 3 kinds of action, OK zero failed calls
- **E-13** (unconfirmed): OK unconfirmed: exactly one escalate, no writes
- **E-14** (incident): OK R10 no unaffected order moved, OK R1/R2 every affected order moved, OK R3 final slots equal independent greedy, OK R4 one notify per dealer, exact ids, OK R5 loaners exactly as handbook priority, OK R6 lot(s) held, OK R6 unsold vehicles stopped, OK R6 owners contacted, OK R9 >= 3 kinds of action, OK zero failed calls
- **E-15** (incident): OK R10 no unaffected order moved, OK R1/R2 every affected order moved, OK R3 final slots equal independent greedy, OK R4 one notify per dealer, exact ids, OK R5 loaners exactly as handbook priority, OK R6 lot(s) held, OK R6 unsold vehicles stopped, OK R6 owners contacted, OK R9 >= 3 kinds of action, OK zero failed calls
