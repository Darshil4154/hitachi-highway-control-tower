# Questions to post on the Hitachi Discord channel (early, today)

Post these as one message. Whatever they answer, set the matching switch in control_tower/config.py.

1. "next <weekday>": events arrive Monday 2027-03-08. Does "next Friday" mean Fri 03-12 or Fri 03-19?
   (One message says the part "can't make it next Monday" and the carrier now says "next Friday", which suggests
   the following week.)  -> NEXT_WEEKDAY
2. Transfers: when no same-plant slot exists, must the transfer day also be on/after the end of the disruption,
   or is any day with a free slot from today allowed? Which plant wins a tie on the same day?
   -> TRANSFER_LOWER_BOUND, PLANT_TIEBREAK
3. Slot competition: when several affected orders compete for the same free slots, should they be placed in order
   of original build date, then production order id?
4. Compound event: should a dealer affected by both incidents get one dealer.notify for the event, or one per
   incident? Are loaners ranked across both incidents together?  -> NOTIFY_SCOPE
5. If an affected order has no free slot anywhere before 2027-04-02, should we leave it and escalate?
   -> NO_SLOT_ACTION
6. Quality hold: is dealer.stop_sale + crm.notify_customer enough, or should dealers also get dealer.notify?
   One notify_customer per owner, or per vehicle?  -> QUALITY_DEALER_NOTIFY
7. Is calling escalate on a noise event penalized?
8. For R9 (at least three kinds of action), do read tools or escalate count as a kind?
