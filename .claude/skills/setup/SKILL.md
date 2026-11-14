---
name: setup
description: First-time setup of the finance ledger — accounts, income per payday, category limits per pay period, emergency fund and existing savings. Use when the owner says "set me up", or when ./fin reports there is no data yet.
---

# Setup

1. Run `./fin init`. If data already exists, stop and ask whether they want to
   change settings instead.
2. Ask, one topic at a time, keeping it conversational:
   - **Accounts** they pay from or save in (e.g. Cash, GCash, a bank):
     `./fin account add NAME`, and `./fin account remove NAME` for defaults they
     don't use.
   - **Income per payday** (15th and 30th), for context only.
   - **Fixed bills** (rent, Meralco, water, internet, load, padala). For each bill paid directly
     (not auto-charged to a card), record its due day so the tracker can list it:
     `./fin category set NAME --bill-day N` (quarterly: `--every 3 --from YYYY-MM-DD`;
     `--bill-amount X` when the bill differs from the limit).
   - **Limits per pay period** for each category and which are essential:
     `./fin category list`, then `./fin category set NAME --limit AMOUNT --essential yes|no`
     (`--limit none` for no limit; `./fin category add NAME` for new ones). Keep
     "Impulse / wants" — it is how impulse spending stays visible.
   - **Emergency fund**: how many months of essentials (3–6) and how much they
     plan to save each pay period: `./fin goal set "Emergency fund" --months N --planned AMOUNT`.
     The target is worked out from their spending after two pay periods; they
     can set one now with `--target AMOUNT`.
   - **Savings they already have**: `./fin goal opening "Emergency fund" AMOUNT --account ACCOUNT`.
   - **Credit cards and loans**: for each, use `./fin debt set …` with what's owed
     today, due day, limit, rate and planned payment (see the `debt` skill).
     Existing installments go in with `./fin debt installment …`.
   - **Money people owe them**: `./fin owed lend "NAME" AMOUNT --from ACCOUNT --due …`
     for each (use the account the money originally came from, or Cash).
3. Show `./fin status` and `./fin goal list` so they can check it.
4. `./fin save -m "setup"`.

Later changes use the same `account` / `category` / `goal` commands, then save.
