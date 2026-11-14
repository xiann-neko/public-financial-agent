---
name: debt
description: Credit cards, card installments, loans, and money other people owe the owner (utang). Use when the owner mentions a card bill, card balance, installment, loan, amortization, paying a debt, interest or fees, a payoff plan, lending money, or someone paying them back.
---

# Debts and money owed to you

All amounts and dates come from `./fin`. Never work them out yourself. Save
after every change: `./fin save -m "…"`.

## Setting up a card or loan
Ask what's owed today, the due day, and, for cards, the limit and the interest
rate per month (Philippine cards usually charge 2–3% a month; the statement
shows it). Also ask what they plan to pay each month.
- Card: `./fin debt set "NAME" --kind card --owed AMOUNT --due-day N --limit AMOUNT --rate PCT --payment AMOUNT`
- Loan: `./fin debt set "NAME" --kind loan --owed AMOUNT --due-day N --payment AMOUNT [--end YYYY-MM] [--rate PCT]`
  (`--end` is the last amortization month. Ask for it; it gives an exact payoff date.)
`--owed` is the balance *today*. Purchases logged afterwards add to it.

## Everyday
- **Bought something with a card:** a normal expense with `--account "CARD"`. It
  counts in the budget now and adds to what's owed.
- **Card installment** (e.g. a phone on 12 months): don't log it as an expense. Use
  `./fin debt installment "CARD" "ITEM" TOTAL --months N --category "…" [--monthly AMOUNT]`.
  Pass `--monthly` when the plan has interest (the monthly amount × months is more
  than the price); the difference is tracked as interest. The budget counts one
  share in each pay period it's billed.
- **Paid a card bill or loan amortization:** `./fin debt pay "NAME" AMOUNT --from ACCOUNT`.
  For loans, if the receipt splits interest, add `--interest AMOUNT` so interest
  is tracked separately.
- **Finance charge, late fee or annual fee on the statement:** `./fin debt charge "NAME" AMOUNT --note "late fee"`.
- **Balances and due dates:** `./fin debt list`.

## Payoff plan
`./fin debt plan`. If they can put extra money toward debt, use
`./fin debt plan --extra AMOUNT`: it puts the extra on the highest-interest debt
first and shows the new debt-free month and the interest saved. If a debt says
"never paid off at this payment", say so plainly. The payment doesn't cover the
interest.

## Money other people owe you (utang)
Lending isn't spending.
- Lent: `./fin owed lend "NAME" AMOUNT --from ACCOUNT [--due YYYY-MM-DD]`
- Paid back: `./fin owed repay "NAME" AMOUNT --to ACCOUNT`
- Letting it go: `./fin owed forgive "NAME" [AMOUNT] [--category "…"]`. This
  becomes spending (default category Other; e.g. Family support for relatives).
- Who owes what: `./fin owed list`.

## Reminders
The session-start summary lists cards and loans due within 5 days, missed due
dates with no payment logged, and people past the date they promised. Raise
them first, briefly.
