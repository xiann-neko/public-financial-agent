"""CLI commands for debts (cards, loans, installments) and money owed to the owner."""
import json
import re

from fincore import cli as C
from fincore import debts as D
from fincore.model import Account, Installment, Transaction
from fincore.money import format_amount

KIND = {"card": "credit_card", "loan": "loan"}


def _debt(store, name: str) -> Account:
    for a in store.accounts():
        if a.name.lower() == name.lower():
            if not a.is_debt:
                raise C.UserError(f"{a.name} isn't set up as a card or loan — use ./fin debt set first")
            return a
    raise C.UserError(f"No account {name!r}")


def _save_txns(ctx, s, txns: list[Transaction]) -> None:
    all_txns = s.transactions()
    for t in txns:
        C.validate_txn(s, t)
        t.id = C.next_txn_id(all_txns, t.date)
        all_txns.append(t)
        print(f"Saved {C.txn_line(t)}")
    s.save_transactions(all_txns)


def cmd_debt_set(ctx) -> int:
    a = ctx.args
    s = ctx.writable()
    accts = s.accounts()
    acct = next((x for x in accts if x.name.lower() == a.name.lower()), None)
    converting = acct is None or not acct.is_debt
    if acct is None:
        acct = Account(a.name)
        accts.append(acct)
    elif acct.kind == "receivable":
        raise C.UserError(f"{acct.name} tracks money owed to you; it can't become a debt")
    if converting and a.owed is None:
        raise C.UserError(f"Say how much is owed on {acct.name} today: --owed AMOUNT (0 if nothing)")
    acct.kind = KIND[a.kind]
    if a.owed is not None:
        today_balance = 0 if a.owed.strip().lstrip("₱").strip() in ("0", "0.00") else C._amount(a.owed)
        # --owed is today's balance: transactions already logged on this account are part of it
        acct.opening_balance = 0
        acct.opening_balance = today_balance - D.owed(s, acct, ctx.today)
        acct.tracked_since = ctx.today.isoformat()
    if a.due_day is not None:
        if not 1 <= a.due_day <= 31:
            raise C.UserError("--due-day must be 1–31")
        acct.due_day = a.due_day
    if a.limit is not None:
        acct.credit_limit = C._amount(a.limit)
    if a.rate is not None:
        try:
            acct.rate_monthly = float(a.rate.rstrip("%"))
        except ValueError:
            raise C.UserError(f"--rate is % per month, e.g. 3 or 2.5, not {a.rate!r}")
        if not 0 <= acct.rate_monthly < 100:
            raise C.UserError("--rate must be between 0 and 100 (% per month)")
    if a.payment is not None:
        acct.payment = C._amount(a.payment)
    if a.end is not None:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", a.end):
            raise C.UserError("--end is the last payment month, YYYY-MM")
        acct.end = a.end
    s.save_accounts(accts)
    print(f"{acct.name}: {acct.kind.replace('_', ' ')}, owes {format_amount(D.owed(s, acct, ctx.today))}"
          + (f", due every {acct.due_day}" if acct.due_day else ""))
    return 0


def cmd_debt_list(ctx) -> int:
    r = D.debt_summary(ctx.store, ctx.today)
    if ctx.args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    if not r["debts"]:
        print("No cards or loans set up. Use ./fin debt set NAME --kind card|loan.")
    for d in r["debts"]:
        bits = [f"{d['name']}: {format_amount(d['owed'])} owed"]
        if d["installments_left"]:
            bits.append(f"+ {format_amount(d['installments_left'])} in installments not yet billed")
        if d["next_due"]:
            due = C.date.fromisoformat(d["next_due"])
            bits.append(f"due {due:%b} {due.day} (in {d['days_to_due']} days)")
        if d["limit_used_pct"] is not None:
            bits.append(f"{d['limit_used_pct']}% of limit")
        print(" · ".join(bits))
    print(f"Total owed: {format_amount(r['total_owed'])}")
    if r["owed_to_you"]:
        print(f"Owed to you: {format_amount(r['owed_to_you'])}")
    return 0


def cmd_debt_pay(ctx) -> int:
    a = ctx.args
    s = ctx.writable()
    acct = _debt(s, a.name)
    amount = C._amount(a.amount)
    interest = C._amount(a.interest) if a.interest else 0
    if interest >= amount:
        raise C.UserError("The interest part must be less than the payment")
    d = C._date(a.date) if a.date else ctx.today
    txns = [Transaction(id="", date=d, type="transfer", amount=amount - interest, category="", account=a.from_,
                        to_account=acct.name, note="payment", created_at=ctx.now)]
    if interest:
        D.ensure_interest_category(s)
        txns.append(Transaction(id="", date=d, type="expense", amount=interest, category=D.INTEREST_CATEGORY,
                                account=a.from_, payee=acct.name, note="interest", created_at=ctx.now))
    _save_txns(ctx, s, txns)
    print(f"{acct.name}: {format_amount(D.owed(s, acct, d))} still owed")
    return 0


def cmd_debt_charge(ctx) -> int:
    a = ctx.args
    s = ctx.writable()
    acct = _debt(s, a.name)
    D.ensure_interest_category(s)
    d = C._date(a.date) if a.date else ctx.today
    _save_txns(ctx, s, [Transaction(id="", date=d, type="expense", amount=C._amount(a.amount),
                                    category=D.INTEREST_CATEGORY, account=acct.name, payee=acct.name,
                                    note=a.note or "finance charge", created_at=ctx.now)])
    print(f"{acct.name}: {format_amount(D.owed(s, acct, d))} owed")
    return 0


def cmd_debt_installment(ctx) -> int:
    a = ctx.args
    s = ctx.writable()
    acct = _debt(s, a.card)
    if acct.kind != "credit_card":
        raise C.UserError("Installments go on a credit card")
    if a.months < 1:
        raise C.UserError("--months must be at least 1")
    total = C._amount(a.total)
    monthly = C._amount(a.monthly) if a.monthly else -(-total // a.months)
    if monthly * a.months < total:
        raise C.UserError("--monthly × --months is less than the total")
    cats = [c.name for c in s.categories() if c.kind == "expense"]
    cat = next((c for c in cats if c.lower() == a.category.lower()), None)
    if cat is None:
        raise C.UserError(f"Unknown expense category {a.category!r}. Options: {', '.join(cats)}")
    first = C._date(a.first) if a.first else (D.next_due(acct, ctx.today) or ctx.today)
    items = s.installments()
    same = [i for i in items if i.card == acct.name and i.total == total and i.item.lower() == a.item.lower()]
    if same and not a.allow_duplicate:
        raise C.DuplicateError(f"There's already an installment for {a.item} ({format_amount(total)}) on "
                               f"{acct.name} ({same[0].id}). If it's a second one, repeat with --allow-duplicate.")
    inst = Installment(s.new_installment_id(), acct.name, a.item, cat, total, a.months, monthly, first,
                       billing_day=acct.due_day or first.day)
    if D.has_interest(inst):
        D.ensure_interest_category(s)
    s.save_installments(items + [inst])
    extra = monthly * a.months - total if D.has_interest(inst) else 0
    print(f"{inst.id}: {a.item} {format_amount(total)} on {acct.name} — {a.months} × {format_amount(monthly)} "
          f"from {first:%b} {first.day}" + (f" (interest {format_amount(extra)} in total)" if extra else ""))
    print(f"Your budget counts {format_amount(monthly)} in each pay period a share is billed.")
    return 0


def cmd_debt_installments(ctx) -> int:
    items = ctx.store.installments()
    for i in items:
        left = D.installment_remaining([i], i.card, ctx.today)
        print(f"{i.id}: {i.item} on {i.card} — {i.months} × {format_amount(i.monthly)} from "
              f"{i.first_billing:%b %d %Y} ({i.category}); {format_amount(left)} not yet billed")
    if not items:
        print("No installments.")
    return 0


def cmd_debt_installment_delete(ctx) -> int:
    s = ctx.writable()
    items = s.installments()
    i = next((x for x in items if x.id == ctx.args.id), None)
    if i is None:
        raise C.UserError(f"No installment {ctx.args.id!r}. Run ./fin debt installments to see them.")
    s.save_installments([x for x in items if x.id != i.id])
    print(f"Deleted {i.id}: {i.item} on {i.card}")
    return 0


# ---- payoff plan ------------------------------------------------------------
def _month_label(today, months: int) -> str:
    d = D.add_months(today.replace(day=1), months, 1)
    return f"{d:%b %Y}"


def plan_inputs(store, today) -> list:
    from fincore.payoff import SimDebt
    out = []
    items = store.installments()
    for a in store.accounts():
        if not a.is_debt:
            continue
        rate = (a.rate_monthly or 0) / 100
        end = None
        if a.kind == "loan" and a.end:
            y, m = map(int, a.end.split("-"))
            end = (y - today.year) * 12 + (m - today.month)
            if end < 0:
                end = None  # past its end date but still owed: simulate with the payment instead
        out.append(SimDebt(a.name, D.owed(store, a, today), rate, a.payment, end))
        for i in items:
            if i.card != a.name:
                continue
            left = [d for d, _, _ in D.installment_shares(i) if d > today]
            if left:
                last = left[-1]
                out.append(SimDebt(f"{a.name} · {i.item} (installment)", D.installment_remaining([i], a.name, today),
                                   0.0, None, (last.year - today.year) * 12 + (last.month - today.month)))
    return out


def _result_json(r, today) -> dict:
    return {"debts": {n: {"status": x.status, "months": x.months, "interest": x.interest,
                          "payoff": _month_label(today, x.months) if x.months is not None else None}
                      for n, x in r.debts.items()},
            "total_interest": r.total_interest, "debt_free_months": r.debt_free_months,
            "debt_free": _month_label(today, r.debt_free_months) if r.debt_free_months is not None else None,
            "first_target": r.first_target}


def cmd_debt_plan(ctx) -> int:
    from fincore.payoff import simulate
    s = ctx.store
    debts = plan_inputs(s, ctx.today)
    extra = C._amount(ctx.args.extra) if ctx.args.extra else 0
    base = simulate(plan_inputs(s, ctx.today), 0)
    fast = simulate(plan_inputs(s, ctx.today), extra) if extra else None
    if ctx.args.json:
        out = {"current": _result_json(base, ctx.today)}
        if fast:
            out["with_extra"] = _result_json(fast, ctx.today)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    if not debts:
        print("No cards or loans set up.")
        return 0
    for d in debts:
        x = base.debts[d.name]
        if d.balance <= 0:
            continue
        if x.status == "no-payment":
            what = "set a monthly payment to see a payoff date (./fin debt set … --payment)"
        elif x.status == "never":
            what = "never paid off at this payment — it doesn't cover the interest"
        else:
            what = f"paid off {_month_label(ctx.today, x.months)}"
            if x.interest:
                what += f", about {format_amount(x.interest)} interest"
        print(f"{d.name} ({format_amount(d.balance)}): {what}")
    if base.debt_free_months is not None:
        print(f"Debt-free: {_month_label(ctx.today, base.debt_free_months)} at your current payments.")
    else:
        print("Debt-free date unknown until every debt has a payment that beats its interest.")
    if fast:
        print(f"With {format_amount(extra)} extra a month, put it on {fast.first_target} first "
              "(highest interest), then roll each paid-off payment into the next.")
        never = [n for n, x in base.debts.items() if x.status == "never"]
        if fast.debt_free_months is not None:
            line = f"  Debt-free: {_month_label(ctx.today, fast.debt_free_months)}"
            if never:
                line += f" — without the extra, {', '.join(never)} would never be paid off."
            else:
                line += (f"; saves about {format_amount(max(base.total_interest - fast.total_interest, 0))}"
                         " in interest.")
            print(line)
    return 0


# ---- money owed to the owner ------------------------------------------------
PREFIX = "Owed by "


def _person_account(store, name: str):
    target = (PREFIX + name).lower()
    return next((a for a in store.accounts() if a.kind == "receivable" and a.name.lower() == target), None)


def _require_person(store, name: str) -> Account:
    acct = _person_account(store, name)
    if acct is None:
        people = [a.name[len(PREFIX):] for a in store.accounts() if a.kind == "receivable"]
        raise C.UserError(f"Nobody called {name!r} owes you. People: {', '.join(people) or 'none yet'}")
    return acct


def cmd_owed(ctx) -> int:
    a = ctx.args
    if a.owed_cmd == "list":
        s = ctx.store
        rows = [{"name": x.name[len(PREFIX):], "owed": D.owed(s, x, ctx.today), "due_date": x.due_date}
                for x in s.accounts() if x.kind == "receivable"]
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
            return 0
        rows = [r for r in rows if r["owed"] > 0]  # settled people stay in JSON, hidden in text
        for r in rows:
            print(f"{r['name']}: {format_amount(r['owed'])}" + (f" (due {r['due_date']})" if r["due_date"] else ""))
        print(f"Total owed to you: {format_amount(sum(r['owed'] for r in rows))}" if rows else "Nobody owes you money.")
        return 0
    s = ctx.writable()
    d = C._date(a.date) if getattr(a, "date", None) else ctx.today
    if a.owed_cmd == "lend":
        names = [x.name for x in s.accounts()]
        if a.from_ not in names:
            raise C.UserError(f"Unknown account {a.from_!r}. Accounts: {', '.join(names)}")
        amount = C._amount(a.amount)
        acct = _person_account(s, a.name)
        if acct is None:
            acct = Account(PREFIX + a.name.strip(), kind="receivable")
            s.save_accounts(s.accounts() + [acct])
        if a.due:
            accts = s.accounts()
            next(x for x in accts if x.name == acct.name).due_date = C._date(a.due).isoformat()
            s.save_accounts(accts)
        _save_txns(ctx, s, [Transaction(id="", date=d, type="transfer", amount=amount, category="",
                                        account=a.from_, to_account=acct.name, note="lent", created_at=ctx.now)])
    else:
        acct = _require_person(s, a.name)
        balance = D.owed(s, acct, ctx.today)
        amount = C._amount(a.amount) if getattr(a, "amount", None) else balance
        if amount > balance or amount <= 0:
            raise C.UserError(f"{acct.name[len(PREFIX):]} owes you {format_amount(balance)}")
        if a.owed_cmd == "repay":
            t = Transaction(id="", date=d, type="transfer", amount=amount, category="", account=acct.name,
                            to_account=a.to, note="repaid", created_at=ctx.now)
        else:
            t = Transaction(id="", date=d, type="expense", amount=amount, category=a.category or "Other",
                            account=acct.name, payee=acct.name[len(PREFIX):], note="forgiven", created_at=ctx.now)
        _save_txns(ctx, s, [t])
    print(f"{acct.name[len(PREFIX):]} owes you {format_amount(D.owed(s, acct, ctx.today))}")
    return 0


def register(sub) -> None:
    o = sub.add_parser("owed", help="money other people owe you")
    os_ = o.add_subparsers(dest="owed_cmd", required=True)
    x = os_.add_parser("list")
    x.add_argument("--json", action="store_true")
    x = os_.add_parser("lend")
    x.add_argument("name")
    x.add_argument("amount")
    x.add_argument("--from", dest="from_", required=True)
    x.add_argument("--due", help="when they said they'd pay back, YYYY-MM-DD")
    x.add_argument("--date")
    x = os_.add_parser("repay")
    x.add_argument("name")
    x.add_argument("amount")
    x.add_argument("--to", required=True)
    x.add_argument("--date")
    x = os_.add_parser("forgive")
    x.add_argument("name")
    x.add_argument("amount", nargs="?")
    x.add_argument("--category", help="expense category (default Other)")
    x.add_argument("--date")
    o.set_defaults(func=cmd_owed)

    d = sub.add_parser("debt", help="credit cards, loans, installments")
    ds = d.add_subparsers(dest="debt_cmd", required=True)
    x = ds.add_parser("set", help="make an account a card or loan, or change its details")
    x.add_argument("name")
    x.add_argument("--kind", choices=list(KIND), required=True)
    x.add_argument("--owed", help="amount owed today (required when an account first becomes a debt)")
    x.add_argument("--due-day", type=int)
    x.add_argument("--limit")
    x.add_argument("--rate", help="interest, %% per month")
    x.add_argument("--payment", help="planned monthly payment")
    x.add_argument("--end", help="loans: last payment month YYYY-MM")
    x.set_defaults(func=cmd_debt_set)
    x = ds.add_parser("list")
    x.add_argument("--json", action="store_true")
    x.set_defaults(func=cmd_debt_list)
    x = ds.add_parser("pay")
    x.add_argument("name")
    x.add_argument("amount")
    x.add_argument("--from", dest="from_", required=True)
    x.add_argument("--interest")
    x.add_argument("--date")
    x.set_defaults(func=cmd_debt_pay)
    x = ds.add_parser("charge", help="finance charge / fee on a card or loan")
    x.add_argument("name")
    x.add_argument("amount")
    x.add_argument("--note")
    x.add_argument("--date")
    x.set_defaults(func=cmd_debt_charge)
    x = ds.add_parser("plan", help="payoff dates; --extra shows the avalanche plan")
    x.add_argument("--extra", help="extra money per month toward debt")
    x.add_argument("--json", action="store_true")
    x.set_defaults(func=cmd_debt_plan)
    x = ds.add_parser("installments", help="list installment plans")
    x.set_defaults(func=cmd_debt_installments)
    x = ds.add_parser("installment-delete", help="remove a wrongly entered installment")
    x.add_argument("id")
    x.set_defaults(func=cmd_debt_installment_delete)
    x = ds.add_parser("installment", help="installment purchase on a card")
    x.add_argument("card")
    x.add_argument("item")
    x.add_argument("total")
    x.add_argument("--months", type=int, required=True)
    x.add_argument("--category", required=True)
    x.add_argument("--monthly")
    x.add_argument("--first", help="first billing date YYYY-MM-DD (default: card's next due date)")
    x.add_argument("--allow-duplicate", action="store_true")
    x.set_defaults(func=cmd_debt_installment)


C.EXTRA_COMMANDS.append(register)
