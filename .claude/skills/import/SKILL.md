---
name: import
description: Import a bank or e-wallet statement (CSV export) or a statement screenshot/PDF, with duplicate checks. Use when the owner uploads or mentions a statement or transaction history export.
---

# Statement import

1. Which source is it? Importers live in `importers/NAME.json`.
   - **Known:** go on.
   - **New CSV format:** look at the header row and write `importers/NAME.json`
     (keys: `date_column`, `date_format`, `payee_column`, optional `note_column`,
     either `amount_column` + `expense_is_negative` or `debit_column` +
     `credit_column`, `account`, `skip_rows`). No personal data in the mapping.
     This is a code change: commit it on a branch and open a pull request, not
     with `./fin save`.
   - **PDF or screenshot only:** read it like a screenshot (see the `log` skill).
2. `./fin import parse FILE --source NAME --json`. Nothing is written yet.
3. Show the rows compactly. Rows with `duplicates` are probably already logged —
   say so and skip them unless the owner says otherwise.
4. Assign a category to each remaining row (ask about anything ambiguous).
   **Credit card statements** need care, because some lines are already tracked
   by the `debt` skill:
   - Installment lines ("Installment 3/12 …") are already counted by
     `./fin debt installment`. Skip them. If an installment isn't tracked yet, set
     it up with `./fin debt installment` instead of importing the line.
   - Payment lines ("Payment – thank you") aren't spending. Record them with
     `./fin debt pay CARD AMOUNT --from ACCOUNT` unless already logged.
   - Finance charges, interest, late fees and annual fees: use
     `./fin debt charge CARD AMOUNT --note "…"`, not plain expenses.
   - Ordinary purchases are imported as expenses with the card as the account.
5. Write the confirmed rows to `data/.staging/import.json` as a JSON list. Keep
   each row's fields from step 2; add `category`. `amount` stays as the integer
   centavos the parser produced (a string like "1,299.50" is read as pesos).
   Add `"allow_duplicate": true` only for rows the owner confirmed are separate.
6. `./fin add-batch data/.staging/import.json` — all rows are saved or none.
   Exit 3 means a duplicate slipped through: show it and ask.
7. `./fin save -m "import NAME statement"`, then summarise what was added.
