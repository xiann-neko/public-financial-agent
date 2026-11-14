---
name: log
description: Record a purchase, income or transfer from a plain-language message, a screenshot or a receipt photo. Use whenever the owner mentions money they spent, received or moved.
---

# Logging

## From text
1. Pull out amount, what it was (payee), account and date (default today).
2. Pick the category. Unplanned "wants" go to **Impulse / wants**; planned
   purchases to **Shopping (planned)**. If it could be either, ask one short
   question (e.g. "Was the Shopee order planned or an impulse buy?").
3. If the account isn't clear and they have several, ask.
4. `./fin add expense AMOUNT --category "…" --account "…" --payee "…" [--date …]`
   (`income` with an income category; `transfer … --to ACCOUNT` for moving
   money between accounts — transfers are never spending).
5. Relay `./fin`'s confirmation and the category line it prints. If it says
   near or over, mention it in one line.
6. `./fin save -m "<short description>"`.

## Cards, installments, loans, lending
- Paid by credit card: the usual `./fin add expense …` with `--account "CARD"`.
- Bought on installment, paid a card bill or loan, or lent money / got paid back:
  use the `debt` skill (`./fin debt …` / `./fin owed …`). Don't log those as
  plain expenses.

## From a screenshot or receipt
1. Read every transaction in the image: date, amount, merchant, account (GCash,
   e-wallet or bank receipts usually say which).
2. Show a compact list and ask for a yes or corrections before saving.
3. Add each with `--source screenshot`, then save once.

## Exit code 3 (possible duplicate)
Show the existing entry `./fin` printed and ask. Re-run with
`--allow-duplicate` only if they confirm it's a separate purchase.

## Corrections
`./fin list --search …` to find it, then `./fin edit ID …` or `./fin delete ID`,
then save.
