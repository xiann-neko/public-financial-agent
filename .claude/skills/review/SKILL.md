---
name: review
description: Weekly money review — where the money went, impulse spending vs last week, budgets near or over, savings progress, saved by waiting. Use when the owner asks for a review or summary, or when the session-start summary says one is due.
---

# Weekly review

1. `./fin review` (this also records that the review happened).
2. Summarise in 3–5 lines, most important first:
   - total spent this week and the biggest category,
   - impulse spending this week vs the week before (call out improvement),
   - any category near or over its limit this pay period,
   - emergency fund progress (`./fin goal list` for pace / pay periods to go),
   - saved by waiting so far,
   - debt total and its change this week, any interest or fees, and money owed
     to them (`./fin debt plan` if they ask how long until debt-free).
3. Offer one concrete suggestion at most, based on the numbers.
4. `./fin save -m "weekly review"`.

## Monthly tracker page
When the owner asks for the tracker, a monthly summary or charts:
`./fin report --month YYYY-MM --html <scratchpad>/tracker-YYYY-MM.html`, then send the file
(it holds personal data, so never commit it or publish it). The "Debt payment goal" is each
card's `--payment`: when a new statement arrives, set it to the statement amount with
`./fin debt set "CARD" --kind card --payment AMOUNT` and save.
