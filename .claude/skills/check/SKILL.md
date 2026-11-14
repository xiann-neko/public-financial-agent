---
name: check
description: Before-you-buy check and the cooling-off list. Use when the owner says they're thinking of buying something, asks "should I buy…", or when cooling-off items are due.
---

# Before you buy

1. Get the price and the category (ask if unclear; wants are **Impulse / wants**),
   and how they'd pay: which account or card, and whether on installment.
2. `./fin check AMOUNT "CATEGORY" [--account "CARD"] [--months N]`. With a card it
   also shows what they still owe on it and the limit used; with `--months` the
   budget line uses the monthly share.
3. Relay it in two or three lines: what's left in that category until the next
   payday, what it does to the emergency fund ("pushes it back about N days"),
   and a straight take. Essentials: fine, just log it when bought.
4. Non-essentials: offer the cooling-off list —
   `./fin wait add "ITEM" AMOUNT "CATEGORY"` (48 hours by default, `--hours` to
   change). Save.

# Cooling-off items that are due

The session-start summary lists them (or run `./fin wait due`). For each, ask:
still want it?
- **Bought it:** `./fin wait buy ID --account ACCOUNT` (logs the expense).
- **Dropped it:** `./fin wait drop ID` — tell them the running "saved by
  waiting" total; it's worth celebrating.
Then save.

Never pressure; the point is a pause, not a ban.

## "How much can I spend on …?"
Run `./fin safe --except "CATEGORY"` (add `--until YYYY-MM-DD` when the owner plans to a later
payday, e.g. pay already received early). Give the safe amount and the main things held back.
When the owner earmarks money ("keep 10k for the trip"), record it with `./fin setaside add NAME AMOUNT`
and drop or lower it once that money is spent.
