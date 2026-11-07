# What-if report: open interpretation questions

Each row re-plans all 15 events in the digital twin with one switch flipped (`control_tower/config.py`) and compares the write calls with the default run. Every variant is also graded by the independent self-check (`eval/self_check.py`), which follows the same switch.

Default run: 766 writes, 15/15 events green.

"Decisions changed" counts write calls whose target or arguments differ (which order moves where, which dealer is notified about which orders, who gets a loaner). "Message text only" counts dealer notifications that go to the same dealer about the same orders but quote different new dates.

| switch | alternative | meaning | decisions changed | message text only | events | self-check |
|---|---|---|---|---|---|---|
| `TRANSFER_LOWER_BOUND` | `restart` (default `today`) | Transfer day must be on/after the end of the disruption | 5 | 33 | E-09, E-11 | 15/15 green |
| `TRANSFER_SEARCH` | `plant_first` (default `day_first`) | Transfers go plant by plant (first plant in plants.csv with any free slot) | 0 | 0 | - | 15/15 green |
| `SLOT_PRIORITY` | `promised_date` (default `build_date`) | Contested slots go to the order with the earliest customer promise date | 2 | 14 | E-11 | 15/15 green |
| `NOTIFY_SCOPE` | `per_incident` (default `per_event`) | Compound event: one dealer.notify per incident instead of per event | 15 | 0 | E-01 | 15/15 green |
| `COMPOUND_ORDER` | `earliest_disruption_first` (default `message_order`) | Compound event: plan the earliest disruption first | 0 | 0 | - | 15/15 green |
| `NEXT_WEEKDAY` | `nearest_upcoming` (default `following_week`) | "next Friday" = the nearest upcoming Friday (Mar 12) | 140 | 0 | E-01, E-04 | 15/15 green |
| `NO_SLOT_ACTION` | `skip` (default `escalate`) | Order with no slot anywhere: skip instead of escalate | 0 | 0 | - | 15/15 green |

## Differences

### `TRANSFER_LOWER_BOUND = restart`

- **E-09**: 2 decision(s) replaced by 2, 14 notification text(s) changed
  - default: mes.transfer PO-0442 -> P_TX 2027-03-08
  - default: mes.transfer PO-0444 -> P_KY 2027-03-08
  - alternative: mes.transfer PO-0442 -> P_TX 2027-04-01
  - alternative: mes.transfer PO-0444 -> P_KY 2027-04-01
- **E-11**: 3 decision(s) replaced by 3, 19 notification text(s) changed
  - default: mes.transfer PO-0259 -> P_KY 2027-03-08
  - default: mes.transfer PO-0260 -> P_IN 2027-03-08
  - default: mes.transfer PO-0261 -> P_TX 2027-03-08
  - alternative: mes.transfer PO-0259 -> P_KY 2027-03-31
  - alternative: mes.transfer PO-0260 -> P_IN 2027-03-31
  - alternative: mes.transfer PO-0261 -> P_TX 2027-03-31

### `SLOT_PRIORITY = promised_date`

- **E-11**: 2 decision(s) replaced by 2, 14 notification text(s) changed
  - default: mes.reschedule PO-0256 -> same plant 2027-04-01
  - default: mes.reschedule PO-0258 -> same plant 2027-04-02
  - alternative: mes.reschedule PO-0256 -> same plant 2027-04-02
  - alternative: mes.reschedule PO-0258 -> same plant 2027-04-01

### `NOTIFY_SCOPE = per_incident`

- **E-01**: 15 decision(s) replaced by 30, 0 notification text(s) changed
  - default: dealer.notify D02 (7 orders)
  - default: dealer.notify D04 (3 orders)
  - default: dealer.notify D06 (6 orders)
  - default: dealer.notify D08 (9 orders)
  - default: dealer.notify D15 (2 orders)
  - default: dealer.notify D20 (4 orders)
  - default: dealer.notify D23 (4 orders)
  - default: dealer.notify D25 (6 orders)
  - default: dealer.notify D26 (8 orders)
  - default: dealer.notify D27 (5 orders)
  - default: dealer.notify D31 (9 orders)
  - default: dealer.notify D33 (2 orders)
  - default: dealer.notify D35 (2 orders)
  - default: dealer.notify D45 (9 orders)
  - default: dealer.notify D46 (5 orders)
  - alternative: dealer.notify D02 (3 orders)
  - alternative: dealer.notify D02 (4 orders)
  - alternative: dealer.notify D04 (1 orders)
  - alternative: dealer.notify D04 (2 orders)
  - alternative: dealer.notify D06 (2 orders)
  - alternative: dealer.notify D06 (4 orders)
  - alternative: dealer.notify D08 (2 orders)
  - alternative: dealer.notify D08 (7 orders)
  - alternative: dealer.notify D15 (1 orders)
  - alternative: dealer.notify D15 (1 orders)
  - alternative: dealer.notify D20 (1 orders)
  - alternative: dealer.notify D20 (3 orders)
  - alternative: dealer.notify D23 (2 orders)
  - alternative: dealer.notify D23 (2 orders)
  - alternative: dealer.notify D25 (3 orders)
  - alternative: dealer.notify D25 (3 orders)
  - alternative: dealer.notify D26 (2 orders)
  - alternative: dealer.notify D26 (6 orders)
  - alternative: dealer.notify D27 (1 orders)
  - alternative: dealer.notify D27 (4 orders)
  - alternative: dealer.notify D31 (3 orders)
  - alternative: dealer.notify D31 (6 orders)
  - alternative: dealer.notify D33 (1 orders)
  - alternative: dealer.notify D33 (1 orders)
  - alternative: dealer.notify D35 (1 orders)
  - alternative: dealer.notify D35 (1 orders)
  - alternative: dealer.notify D45 (2 orders)
  - alternative: dealer.notify D45 (7 orders)
  - alternative: dealer.notify D46 (2 orders)
  - alternative: dealer.notify D46 (3 orders)

### `NEXT_WEEKDAY = nearest_upcoming`

- **E-01**: 81 decision(s) replaced by 0, 0 notification text(s) changed
  - default: crm.assign_loaner CO-00247
  - default: crm.assign_loaner CO-00249
  - default: crm.assign_loaner CO-00263
  - default: crm.assign_loaner CO-00278
  - default: crm.assign_loaner CO-00283
  - default: crm.assign_loaner CO-00296
  - default: crm.assign_loaner CO-01761
  - default: crm.assign_loaner CO-01772
  - default: crm.assign_loaner CO-01774
  - default: crm.assign_loaner CO-01780
  - default: crm.assign_loaner CO-01781
  - default: crm.assign_loaner CO-01783
  - default: crm.assign_loaner CO-01785
  - default: crm.assign_loaner CO-01786
  - default: crm.assign_loaner CO-01798
  - default: crm.assign_loaner CO-01799
  - default: crm.assign_loaner CO-01802
  - default: crm.assign_loaner CO-01808
  - default: crm.assign_loaner CO-01810
  - default: crm.assign_loaner CO-01812
  - default: crm.assign_loaner CO-01814
  - default: crm.assign_loaner CO-01827
  - default: crm.assign_loaner CO-01830
  - default: crm.assign_loaner CO-01833
  - default: crm.assign_loaner CO-01851
  - default: crm.assign_loaner CO-01853
  - default: dealer.notify D01 (1 orders)
  - default: dealer.notify D02 (7 orders)
  - default: dealer.notify D04 (3 orders)
  - default: dealer.notify D06 (6 orders)
  - default: dealer.notify D07 (2 orders)
  - default: dealer.notify D08 (9 orders)
  - default: dealer.notify D09 (1 orders)
  - default: dealer.notify D11 (1 orders)
  - default: dealer.notify D13 (1 orders)
  - default: dealer.notify D14 (1 orders)
  - default: dealer.notify D15 (2 orders)
  - default: dealer.notify D16 (1 orders)
  - default: dealer.notify D17 (1 orders)
  - default: dealer.notify D18 (1 orders)
  - default: dealer.notify D19 (1 orders)
  - default: dealer.notify D20 (4 orders)
  - default: dealer.notify D21 (2 orders)
  - default: dealer.notify D22 (2 orders)
  - default: dealer.notify D23 (4 orders)
  - default: dealer.notify D24 (2 orders)
  - default: dealer.notify D25 (6 orders)
  - default: dealer.notify D26 (8 orders)
  - default: dealer.notify D27 (5 orders)
  - default: dealer.notify D29 (1 orders)
  - default: dealer.notify D30 (1 orders)
  - default: dealer.notify D31 (9 orders)
  - default: dealer.notify D32 (1 orders)
  - default: dealer.notify D33 (2 orders)
  - default: dealer.notify D34 (4 orders)
  - default: dealer.notify D35 (2 orders)
  - default: dealer.notify D36 (1 orders)
  - default: dealer.notify D38 (3 orders)
  - default: dealer.notify D39 (1 orders)
  - default: dealer.notify D41 (2 orders)
  - default: dealer.notify D42 (3 orders)
  - default: dealer.notify D43 (1 orders)
  - default: dealer.notify D44 (4 orders)
  - default: dealer.notify D45 (9 orders)
  - default: dealer.notify D46 (5 orders)
  - default: dealer.notify D47 (1 orders)
  - default: dealer.notify D50 (1 orders)
  - default: mes.reschedule PO-0058 -> same plant 2027-03-23
  - default: mes.reschedule PO-0059 -> same plant 2027-03-23
  - default: mes.reschedule PO-0060 -> same plant 2027-03-24
  - default: mes.reschedule PO-0061 -> same plant 2027-03-24
  - default: mes.reschedule PO-0062 -> same plant 2027-03-25
  - default: mes.reschedule PO-0063 -> same plant 2027-03-25
  - default: mes.reschedule PO-0316 -> same plant 2027-03-19
  - default: mes.reschedule PO-0318 -> same plant 2027-03-19
  - default: mes.reschedule PO-0319 -> same plant 2027-03-22
  - default: mes.reschedule PO-0321 -> same plant 2027-03-22
  - default: mes.reschedule PO-0322 -> same plant 2027-03-23
  - default: mes.reschedule PO-0324 -> same plant 2027-03-23
  - default: mes.reschedule PO-0325 -> same plant 2027-03-24
  - default: mes.reschedule PO-0327 -> same plant 2027-03-24
- **E-04**: 59 decision(s) replaced by 63, 0 notification text(s) changed
  - default: crm.assign_loaner CO-00725
  - default: crm.assign_loaner CO-00727
  - default: crm.assign_loaner CO-00729
  - default: crm.assign_loaner CO-00736
  - default: crm.assign_loaner CO-00737
  - default: crm.assign_loaner CO-00738
  - default: crm.assign_loaner CO-00747
  - default: crm.assign_loaner CO-00750
  - default: crm.assign_loaner CO-00757
  - default: crm.assign_loaner CO-00758
  - default: crm.assign_loaner CO-00765
  - default: crm.assign_loaner CO-00770
  - default: crm.assign_loaner CO-00771
  - default: crm.assign_loaner CO-00772
  - default: crm.assign_loaner CO-00784
  - default: crm.assign_loaner CO-00787
  - default: crm.assign_loaner CO-00789
  - default: crm.assign_loaner CO-00793
  - default: dealer.notify D02 (4 orders)
  - default: dealer.notify D03 (7 orders)
  - default: dealer.notify D04 (1 orders)
  - default: dealer.notify D05 (1 orders)
  - default: dealer.notify D06 (1 orders)
  - default: dealer.notify D07 (2 orders)
  - default: dealer.notify D08 (4 orders)
  - default: dealer.notify D10 (1 orders)
  - default: dealer.notify D15 (1 orders)
  - default: dealer.notify D16 (1 orders)
  - default: dealer.notify D17 (1 orders)
  - default: dealer.notify D20 (5 orders)
  - default: dealer.notify D21 (1 orders)
  - default: dealer.notify D22 (1 orders)
  - default: dealer.notify D23 (6 orders)
  - default: dealer.notify D25 (7 orders)
  - default: dealer.notify D26 (3 orders)
  - default: dealer.notify D27 (2 orders)
  - default: dealer.notify D30 (1 orders)
  - default: dealer.notify D31 (2 orders)
  - default: dealer.notify D32 (1 orders)
  - default: dealer.notify D34 (2 orders)
  - default: dealer.notify D35 (2 orders)
  - default: dealer.notify D36 (1 orders)
  - default: dealer.notify D38 (4 orders)
  - default: dealer.notify D39 (1 orders)
  - default: dealer.notify D40 (1 orders)
  - default: dealer.notify D42 (1 orders)
  - default: dealer.notify D44 (6 orders)
  - default: dealer.notify D45 (4 orders)
  - default: dealer.notify D46 (2 orders)
  - default: dealer.notify D49 (2 orders)
  - default: mes.reschedule PO-0139 -> same plant 2027-03-19
  - default: mes.reschedule PO-0140 -> same plant 2027-03-19
  - default: mes.reschedule PO-0141 -> same plant 2027-03-22
  - default: mes.reschedule PO-0142 -> same plant 2027-03-22
  - default: mes.reschedule PO-0143 -> same plant 2027-03-23
  - default: mes.reschedule PO-0144 -> same plant 2027-03-23
  - default: mes.reschedule PO-0145 -> same plant 2027-03-24
  - default: mes.reschedule PO-0146 -> same plant 2027-03-24
  - default: mes.reschedule PO-0147 -> same plant 2027-03-25
  - alternative: crm.assign_loaner CO-00578
  - alternative: crm.assign_loaner CO-00584
  - alternative: crm.assign_loaner CO-00588
  - alternative: crm.assign_loaner CO-00590
  - alternative: crm.assign_loaner CO-00596
  - alternative: crm.assign_loaner CO-00597
  - alternative: crm.assign_loaner CO-00604
  - alternative: crm.assign_loaner CO-00606
  - alternative: crm.assign_loaner CO-00608
  - alternative: crm.assign_loaner CO-00614
  - alternative: crm.assign_loaner CO-00619
  - alternative: crm.assign_loaner CO-00627
  - alternative: crm.assign_loaner CO-00637
  - alternative: crm.assign_loaner CO-00641
  - alternative: crm.assign_loaner CO-00643
  - alternative: crm.assign_loaner CO-00652
  - alternative: crm.assign_loaner CO-00653
  - alternative: crm.assign_loaner CO-00656
  - alternative: dealer.notify D01 (1 orders)
  - alternative: dealer.notify D02 (4 orders)
  - alternative: dealer.notify D03 (2 orders)
  - alternative: dealer.notify D06 (2 orders)
  - alternative: dealer.notify D07 (3 orders)
  - alternative: dealer.notify D08 (5 orders)
  - alternative: dealer.notify D10 (2 orders)
  - alternative: dealer.notify D11 (1 orders)
  - alternative: dealer.notify D12 (2 orders)
  - alternative: dealer.notify D13 (1 orders)
  - alternative: dealer.notify D14 (3 orders)
  - alternative: dealer.notify D15 (1 orders)
  - alternative: dealer.notify D16 (2 orders)
  - alternative: dealer.notify D19 (1 orders)
  - alternative: dealer.notify D20 (3 orders)
  - alternative: dealer.notify D21 (1 orders)
  - alternative: dealer.notify D22 (1 orders)
  - alternative: dealer.notify D23 (3 orders)
  - alternative: dealer.notify D24 (1 orders)
  - alternative: dealer.notify D25 (7 orders)
  - alternative: dealer.notify D26 (5 orders)
  - alternative: dealer.notify D27 (3 orders)
  - alternative: dealer.notify D29 (3 orders)
  - alternative: dealer.notify D30 (1 orders)
  - alternative: dealer.notify D31 (2 orders)
  - alternative: dealer.notify D32 (1 orders)
  - alternative: dealer.notify D33 (1 orders)
  - alternative: dealer.notify D35 (2 orders)
  - alternative: dealer.notify D38 (3 orders)
  - alternative: dealer.notify D39 (1 orders)
  - alternative: dealer.notify D40 (1 orders)
  - alternative: dealer.notify D43 (3 orders)
  - alternative: dealer.notify D44 (6 orders)
  - alternative: dealer.notify D45 (4 orders)
  - alternative: dealer.notify D46 (1 orders)
  - alternative: dealer.notify D49 (2 orders)
  - alternative: mes.reschedule PO-0124 -> same plant 2027-03-12
  - alternative: mes.reschedule PO-0125 -> same plant 2027-03-12
  - alternative: mes.reschedule PO-0126 -> same plant 2027-03-15
  - alternative: mes.reschedule PO-0127 -> same plant 2027-03-15
  - alternative: mes.reschedule PO-0128 -> same plant 2027-03-16
  - alternative: mes.reschedule PO-0129 -> same plant 2027-03-16
  - alternative: mes.reschedule PO-0130 -> same plant 2027-03-17
  - alternative: mes.reschedule PO-0131 -> same plant 2027-03-17
  - alternative: mes.reschedule PO-0132 -> same plant 2027-03-18
