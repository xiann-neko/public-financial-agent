# Financial agent

A personal budget tracker you run by talking to Claude. Tell Claude what you
spent ("₱350 Grab food lunch", e.g.) or send a screenshot, and it records the
transaction properly, warns you as categories approach their limits, checks
purchases before you buy, keeps a cooling-off list for impulse buys, and tracks
savings goals, starting with an emergency fund. It also tracks credit cards,
card installments and loans (balances, due-date reminders, a payoff plan) and
money other people owe you.

- Currency: Philippine peso (₱). Budgets run per pay period (paydays on the 15th
  and 30th).
- Plain Python 3.11+, standard library only. Nothing to install.
- All math is done by the `./fin` tool, not by Claude, so totals are exact.
- Your data lives in `data/` as plain CSV/JSON files, with git history.

## Set it up

1. Copy this repo into a new **private** repo of your own: use GitHub's
   "Use this template" button if it's shown, or create an empty private repo
   and push these files to it. Don't fork it, because a fork of a public repo
   can't be made private. The tool refuses to save financial data while the
   repo is public.
2. Open a Claude Code session on your copy (on the web or in the Claude app on
   your phone) and say **"set me up"**. Claude runs `./fin init` and walks you
   through accounts, limits per pay period, and your emergency fund.
3. From then on, just talk: "spent 1,299 on Shopee", "thinking of buying
   headphones for 2,500", "weekly review", or upload a statement CSV.

Each change is saved with `./fin save`, which commits `data/` and pushes it to
`main`, so the next session sees it. If a session can't push to `main`, it
pushes a branch instead and asks you to merge a pull request.

## Try it without your own data

```sh
FIN_DATA_DIR=data.example ./fin status
FIN_DATA_DIR=data.example ./fin check 2500 "Impulse / wants"
```

(Writes to `data.example/` aren't guarded. Don't commit them.)

## Tests

```sh
python3 -m unittest discover -s tests
```

## Layout

- `fin`: command wrapper. `fincore/`: the code.
- `CLAUDE.md`, `.claude/skills/`: how Claude uses the tool.
- `importers/`: CSV column mappings for bank and e-wallet statements.
- `scripts/publish.py`: copies the code, without `data/`, into a public repo
  for sharing.
