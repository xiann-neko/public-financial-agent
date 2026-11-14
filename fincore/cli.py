"""Command-line interface. Every failure is a one-line message, never a traceback."""
import argparse
import contextlib
import io
import json
import sys
from datetime import date, datetime

from fincore import clock, guard
from fincore.model import Account, Category, Goal, Transaction
from fincore import goals as G
from fincore import review as R
from fincore import waitlist as W
from fincore.dedupe import find_duplicates
from fincore import importer as I
from fincore.budget import period_status, status_line, warnings
from fincore.money import format_amount, parse_amount
from fincore.periods import period_for
from fincore.store import NoDataError, Store, default_data_dir, init_data, next_txn_id


class UserError(Exception):
    pass


class Ctx:
    def __init__(self, args):
        self.args = args
        local = clock.now()
        self.today: date = date.fromisoformat(args.today) if args.today else local.date()
        self.now: datetime = (datetime.fromisoformat(args.now) if args.now
                              else datetime.combine(self.today, local.time()))
        self._store = None

    @property
    def store(self) -> Store:
        if self._store is None:
            self._store = Store.open()
        return self._store

    def writable(self) -> Store:
        s = self.store
        guard.ensure_writable(s.dir)
        return s


def _date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise UserError(f"Not a date: {s!r} (use YYYY-MM-DD)")


def _amount(s: str) -> int:
    try:
        return parse_amount(s)
    except ValueError as e:
        raise UserError(str(e))


def txn_line(t: Transaction) -> str:
    if t.type == "transfer":
        what = f"{t.account} → {t.to_account}" + (f" [{t.goal}]" if t.goal else "")
    else:
        what = f"{t.category} · {t.account}"
    sign = "+" if t.type == "income" else ("" if t.type == "transfer" else "-")
    payee = f" {t.payee}" if t.payee else ""
    return f"{t.id}  {t.date}  {sign}{format_amount(t.amount)}  {what}{payee}" + (f" ({t.note})" if t.note else "")


def txn_json(t: Transaction) -> dict:
    d = dict(t.__dict__)
    d["date"] = t.date.isoformat()
    d["created_at"] = t.created_at.isoformat() if t.created_at else ""
    return d


# ---- validation shared by add / add-batch / edit ------------------------
def validate_txn(store: Store, t: Transaction) -> None:
    accounts = [a.name for a in store.accounts()]
    if t.account not in accounts:
        raise UserError(f"Unknown account {t.account!r}. Accounts: {', '.join(accounts)}")
    if t.type == "transfer":
        if not t.to_account:
            raise UserError("A transfer needs --to ACCOUNT")
        if t.to_account not in accounts:
            raise UserError(f"Unknown account {t.to_account!r}. Accounts: {', '.join(accounts)}")
        t.category = ""
        if t.goal:
            sign = "-" if t.goal.startswith("-") else ""
            t.goal = sign + _goal(store, t.goal.lstrip("-")).name
        return
    kind = "income" if t.type == "income" else "expense"
    if t.goal:
        raise UserError("Only transfers can be tagged with a savings goal")
    valid = [c.name for c in store.categories() if c.kind == kind]
    if not t.category:
        raise UserError(f"An {t.type} needs --category. Options: {', '.join(valid)}")
    if t.category not in valid:
        raise UserError(f"Unknown {kind} category {t.category!r}. Options: {', '.join(valid)}")


# ---- commands -----------------------------------------------------------
def cmd_init(ctx: Ctx) -> int:
    d = default_data_dir()
    guard.ensure_writable(d)
    try:
        init_data(d)
    except FileExistsError as e:
        raise UserError(str(e))
    print(f"Created {d} with default categories. Next: set accounts, limits and goals.")
    return 0


def after_add_hook(ctx: Ctx, t: Transaction) -> None:
    """After an expense: show that category's standing this pay period."""
    if t.type != "expense":
        return
    p = period_for(t.date)
    for st in period_status(ctx.store, p):
        if st.category == t.category:
            print(f"{p.label}: {status_line(st)}")


def cmd_status(ctx: Ctx) -> int:
    d = _date(ctx.args.date) if ctx.args.date else ctx.today
    p = period_for(d)
    sts = period_status(ctx.store, p)
    if ctx.args.json:
        print(json.dumps({"period": {"start": p.start.isoformat(), "end": p.end.isoformat(), "label": p.label},
                          "categories": [st.__dict__ for st in sts]}, ensure_ascii=False, indent=1))
        return 0
    print(f"Pay period {p.label}")
    for st in sts:
        if st.spent or st.limit:
            print("  " + status_line(st))
    ws = warnings(sts)
    if ws:
        print("Heads-up: " + ", ".join(f"{w.category} ({w.level})" for w in ws))
    return 0


def cmd_add(ctx: Ctx) -> int:
    a = ctx.args
    s = ctx.writable()
    d = _date(a.date) if a.date else ctx.today
    t = Transaction(id="", date=d, type=a.type, amount=_amount(a.amount), category=a.category or "",
                    account=a.account or "", to_account=a.to or "", payee=a.payee or "", note=a.note or "",
                    goal=a.goal or "", source=a.source or "manual", created_at=ctx.now)
    validate_txn(s, t)
    check_duplicates(s, t, a.allow_duplicate)
    t.id = s.new_txn_id(d)
    s.save_transactions(s.transactions() + [t])
    print(f"Saved {txn_line(t)}")
    after_add_hook(ctx, t)
    return 0


class DuplicateError(UserError):
    code = 3


def check_duplicates(store: Store, t: Transaction, allow: bool, existing=None) -> None:
    if allow:
        return
    dups = find_duplicates(store.transactions() if existing is None else existing,
                           t.type, t.amount, t.date, t.payee)
    if dups:
        listing = "\n".join("  " + txn_line(d) for d in dups)
        raise DuplicateError(f"Possible duplicate of:\n{listing}\nIf it's really a separate "
                             "transaction, repeat with --allow-duplicate.")


def _find(store: Store, tid: str) -> Transaction:
    for t in store.transactions():
        if t.id == tid:
            return t
    raise UserError(f"No transaction with id {tid!r}")


def cmd_list(ctx: Ctx) -> int:
    a = ctx.args
    txns = ctx.store.transactions()
    if a.from_:
        txns = [t for t in txns if t.date >= _date(a.from_)]
    if a.to:
        txns = [t for t in txns if t.date <= _date(a.to)]
    if a.category:
        txns = [t for t in txns if t.category.lower() == a.category.lower()]
    if a.search:
        q = a.search.lower()
        txns = [t for t in txns if q in f"{t.payee} {t.note} {t.category}".lower()]
    txns.sort(key=lambda t: (t.date, t.id))
    if a.json:
        print(json.dumps([txn_json(t) for t in txns], ensure_ascii=False, indent=1))
    else:
        for t in txns:
            print(txn_line(t))
        if not txns:
            print("No matching transactions.")
    return 0


def cmd_edit(ctx: Ctx) -> int:
    a = ctx.args
    s = ctx.writable()
    txns = s.transactions()
    t = _find(s, a.id)
    if a.amount:
        t.amount = _amount(a.amount)
    if a.date:
        t.date = _date(a.date)
    for field in ("category", "payee", "note", "account", "goal"):
        v = getattr(a, field)
        if v is not None:
            setattr(t, field, v)
    if a.to is not None:
        t.to_account = a.to
    validate_txn(s, t)
    s.save_transactions([t if x.id == t.id else x for x in txns])
    print(f"Updated {txn_line(t)}")
    return 0


def cmd_delete(ctx: Ctx) -> int:
    s = ctx.writable()
    t = _find(s, ctx.args.id)
    s.save_transactions([x for x in s.transactions() if x.id != t.id])
    print(f"Deleted {txn_line(t)}")
    return 0


# ---- accounts / categories -------------------------------------------------
def _yes_no(v: str) -> bool:
    if v.lower() in ("yes", "y", "true"):
        return True
    if v.lower() in ("no", "n", "false"):
        return False
    raise UserError(f"Use yes or no, not {v!r}")


def _limit(v: str):
    return None if v.lower() == "none" else _amount(v)


def cmd_account(ctx: Ctx) -> int:
    a = ctx.args
    if a.acct_cmd == "list":
        from fincore.debts import balance
        for x in ctx.store.accounts():
            if x.kind == "cash":
                print(f"{x.name}: {format_amount(balance(ctx.store, x, ctx.today))}"
                      + ("" if x.role == "spending" else f" ({x.role})"))
            else:
                print(f"{x.name} (opening {format_amount(x.opening_balance)})")
        return 0
    s = ctx.writable()
    accts = s.accounts()
    existing = {x.name.lower(): x for x in accts}
    if a.acct_cmd == "add":
        if a.name.lower() in existing:
            raise UserError(f"Account {a.name!r} already exists")
        accts.append(Account(a.name, _amount(a.opening) if a.opening else 0))
    elif a.acct_cmd == "set":
        from fincore.debts import cash_flow
        from datetime import date as _d
        x = existing.get(a.name.lower())
        if x is None:
            raise UserError(f"No account {a.name!r}")
        if x.kind != "cash":
            raise UserError(f"{x.name} is a card, loan or person; use ./fin debt or ./fin owed for it")
        if a.role:
            if a.role not in ("spending", "savings", "hidden"):
                raise UserError("--role is spending, savings or hidden")
            x.role = a.role
        if a.balance is not None:
            today_balance = parse_balance(a.balance)
            x.opening_balance = today_balance - cash_flow(s, x.name, _d.min, ctx.today)
        s.save_accounts(accts)
        from fincore.debts import balance
        print(f"{x.name}: {format_amount(balance(s, x, ctx.today))} today"
              + ("" if x.role == "spending" else f" ({x.role})"))
        return 0
    else:
        x = existing.get(a.name.lower())
        if x is None:
            raise UserError(f"No account {a.name!r}")
        if any(x.name in (t.account, t.to_account) for t in s.transactions()):
            raise UserError(f"{x.name} has transactions, so it can't be removed")
        if any(i.card == x.name for i in s.installments()):
            raise UserError(f"{x.name} has installment plans, so it can't be removed")
        accts.remove(x)
    s.save_accounts(accts)
    print("Accounts: " + ", ".join(x.name for x in accts))
    return 0


def parse_balance(text: str) -> int:
    t = text.strip()
    if t in ("0", "0.00", "₱0"):
        return 0
    neg = t.startswith("-")
    v = _amount(t.lstrip("-"))
    return -v if neg else v


def cmd_category(ctx: Ctx) -> int:
    a = ctx.args
    if a.cat_cmd == "list":
        for c in ctx.store.categories():
            bits = [c.kind]
            if c.kind == "expense":
                bits.append("no limit" if c.limit is None else f"{format_amount(c.limit)}/pay period")
                bits += ["essential"] if c.essential else []
                bits += ["impulse"] if c.impulse else []
                if c.bill_day:
                    every = "" if c.bill_every == 1 else f" every {c.bill_every} months"
                    amt = f" ({format_amount(c.bill_amount)})" if c.bill_amount else ""
                    via = {"card": ", charged to a card", "owed": ", paid from money owed to you"}.get(c.bill_via, "")
                    bits.append(f"bill due day {c.bill_day}{every}{amt}{via}")
            print(f"{c.name}: {', '.join(bits)}")
        return 0
    s = ctx.writable()
    cats = s.categories()
    found = next((c for c in cats if c.name.lower() == a.name.lower()), None)
    if a.cat_cmd == "add":
        if found:
            raise UserError(f"Category {a.name!r} already exists")
        found = Category(a.name, "income" if a.income else "expense", None, False)
        cats.append(found)
    elif found is None:
        raise UserError(f"No category {a.name!r}. Options: {', '.join(c.name for c in cats)}")
    if a.limit is not None:
        found.limit = _limit(a.limit)
    if a.essential is not None:
        found.essential = _yes_no(a.essential)
    _set_bill(found, a)
    s.save_budget(cats)
    lim = "no limit" if found.limit is None else f"{format_amount(found.limit)}/pay period"
    print(f"{found.name}: {found.kind}, {lim}{', essential' if found.essential else ''}")
    return 0


def _set_bill(c: Category, a) -> None:
    if a.bill_day is not None:
        if a.bill_day.lower() == "none":
            c.bill_day, c.bill_every, c.bill_from, c.bill_amount, c.bill_via = None, 1, None, None, "direct"
            return
        try:
            day = int(a.bill_day)
        except ValueError:
            day = 0
        if not 1 <= day <= 31:
            raise UserError("--bill-day is a day of the month, 1-31 (or 'none')")
        c.bill_day = day
    if (a.every is not None or a.bill_from or a.bill_amount or a.via) and not c.bill_day:
        raise UserError("Set --bill-day first")
    if a.every is not None:
        if a.every < 1:
            raise UserError("--every is a number of months, 1 or more")
        c.bill_every = a.every
    if a.bill_from:
        c.bill_from = _date(a.bill_from).isoformat()
    if a.bill_amount:
        c.bill_amount = None if a.bill_amount.lower() == "none" else _amount(a.bill_amount)
    if a.via:
        if a.via not in ("direct", "card", "owed"):
            raise UserError("--via is direct, card (auto-charged to a card) or owed (taken off someone's debt)")
        c.bill_via = a.via
    if c.bill_every > 1 and not c.bill_from:
        raise UserError("A bill that isn't monthly needs --from YYYY-MM-DD (one of its due dates)")


# ---- goals --------------------------------------------------------------
def _goal(store: Store, name: str) -> Goal:
    goals = store.goals()
    for g in goals:
        if g.name.lower() == name.lower():
            return g
    raise UserError(f"Unknown goal {name!r}. Goals: {', '.join(g.name for g in goals)}")


def _goal_transfer(ctx: Ctx, goal_tag: str, amount: str, src: str, dst: str, d, source="manual") -> int:
    s = ctx.writable()
    t = Transaction(id="", date=_date(d) if d else ctx.today, type="transfer", amount=_amount(amount),
                    category="", account=src, to_account=dst, goal=goal_tag, source=source, created_at=ctx.now)
    validate_txn(s, t)
    t.id = s.new_txn_id(t.date)
    s.save_transactions(s.transactions() + [t])
    print(f"Saved {txn_line(t)}")
    g = _goal(s, goal_tag.lstrip("-"))
    print(f"{g.name}: {format_amount(G.progress(s, g))} saved")
    return 0


def goal_summary(store: Store, g: Goal, today) -> dict:
    prog, tgt, rate = G.progress(store, g), G.target(store, g, today), G.savings_rate(store, g, today)
    left = None if tgt is None else max(tgt - prog, 0)
    periods = None if left is None or rate <= 0 else -(-left // rate)
    return {"name": g.name, "priority": g.priority, "progress": prog, "target": tgt,
            "percent": None if not tgt else round(100 * prog / tgt, 1), "rate_per_period": rate,
            "periods_to_target": periods}


def cmd_goal(ctx: Ctx) -> int:
    a = ctx.args
    if a.goal_cmd == "list":
        s = ctx.store
        rows = [goal_summary(s, g, ctx.today) for g in sorted(s.goals(), key=lambda g: g.priority)]
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
            return 0
        for r in rows:
            tgt = "target not set yet (needs 2 pay periods of spending)" if r["target"] is None \
                else f"of {format_amount(r['target'])} ({r['percent']}%)"
            pace = "not growing at the current pace" if r["rate_per_period"] <= 0 \
                else f"{format_amount(r['rate_per_period'])}/pay period"
            eta = f", ~{r['periods_to_target']} pay periods to go" if r["periods_to_target"] else ""
            print(f"{r['name']}: {format_amount(r['progress'])} {tgt} · {pace}{eta}")
        return 0
    if a.goal_cmd in ("contribute", "withdraw"):
        g = _goal(ctx.store, a.name)
        tag = g.name if a.goal_cmd == "contribute" else "-" + g.name
        return _goal_transfer(ctx, tag, a.amount, a.from_, a.to, a.date)
    if a.goal_cmd == "opening":
        g = _goal(ctx.store, a.name)
        return _goal_transfer(ctx, g.name, a.amount, a.account, a.account, None, source="opening")
    s = ctx.writable()
    goals = s.goals()
    if a.goal_cmd == "add":
        if any(g.name.lower() == a.name.lower() for g in goals):
            raise UserError(f"Goal {a.name!r} already exists")
        g = Goal(a.name, None, a.priority or max([x.priority for x in goals], default=0) + 1, 0)
        goals.append(g)
    else:
        g = next(x for x in goals if x.name == _goal(s, a.name).name)
    if a.target:
        g.target = None if a.target == "auto" else _amount(a.target)
    if a.months:
        g.target_months = a.months
    if a.planned:
        g.planned_per_period = 0 if a.planned in ("0", "none") else _amount(a.planned)
    if a.priority:
        g.priority = a.priority
    s.save_goals(goals)
    r = goal_summary(s, g, ctx.today)
    print(f"Goal {g.name}: target {format_amount(r['target']) if r['target'] else 'auto'}, "
          f"planned {format_amount(g.planned_per_period)}/pay period, priority {g.priority}")
    return 0


# ---- before you buy / cooling-off ------------------------------------------
def cmd_check(ctx: Ctx) -> int:
    r = W.check_purchase(ctx.store, _amount(ctx.args.amount), ctx.args.category, ctx.today,
                         account=ctx.args.account, months=ctx.args.months)
    if ctx.args.json:
        print(json.dumps(r.__dict__, ensure_ascii=False, indent=1))
        return 0
    p = period_for(ctx.today)
    print(f"{format_amount(r.amount)} on {r.category} ({'essential' if r.essential else 'non-essential'})"
          + (f", on installment: {format_amount(r.monthly_share)} a month" if r.monthly_share else ""))
    if r.limit is None:
        print(f"  No limit set for {r.category}.")
    elif r.remaining_after >= 0:
        print(f"  Budget: {format_amount(r.remaining_before)} left until {p.end:%b %d}; "
              f"{format_amount(r.remaining_after)} after this.")
    else:
        print(f"  Budget: {format_amount(max(r.remaining_before, 0))} left until {p.end:%b %d}; "
              f"this puts {r.category} over by {format_amount(-r.remaining_after)}.")
    if r.goal and r.ef_rate_zero:
        print(f"  {r.goal}: at your current pace it isn't growing, so this money comes straight out of it.")
    elif r.goal:
        print(f"  {r.goal}: pushes it back about {r.ef_delay_days} days.")
    if r.card and r.card_owed_before > 0:
        lim = f" ({r.card_limit_pct_after}% of limit)" if r.card_limit_pct_after is not None else ""
        print(f"  You still owe {format_amount(r.card_owed_before)} on {r.card}; "
              f"this makes it {format_amount(r.card_owed_after)}{lim}.")
    elif r.card:
        lim = f" ({r.card_limit_pct_after}% of limit)" if r.card_limit_pct_after is not None else ""
        print(f"  {r.card} would then be at {format_amount(r.card_owed_after)}{lim}.")
    if r.suggest_wait:
        print("  Suggestion: put it on the cooling-off list (48 hours) and decide then.")
    return 0


def cmd_wait(ctx: Ctx) -> int:
    a = ctx.args
    if a.wait_cmd == "add":
        w = W.add_item(ctx.writable(), a.item, _amount(a.amount), a.category, ctx.now, a.hours)
        print(f"{w.id}: {w.item} {format_amount(w.price)} — decide after {w.due_at:%a %b %d %H:%M}")
        return 0
    if a.wait_cmd in ("list", "due"):
        s = ctx.store
        items = W.due_items(s, ctx.now) if a.wait_cmd == "due" else W.pending(s)
        for w in items:
            print(f"{w.id}: {w.item} {format_amount(w.price)} ({w.category}) — due {w.due_at:%a %b %d %H:%M}")
        if not items:
            print("Nothing due." if a.wait_cmd == "due" else "Cooling-off list is empty.")
        if a.wait_cmd == "list":
            print(f"Saved by waiting so far: {format_amount(W.saved_by_waiting(s))}")
        return 0
    s = ctx.writable()
    w = W.resolve(s, a.id, "bought" if a.wait_cmd == "buy" else "dropped", ctx.now, getattr(a, "account", None))
    if w.outcome == "bought":
        t = next(t for t in s.transactions() if t.id == w.txn_id)
        print(f"Bought: saved {txn_line(t)}")
        after_add_hook(ctx, t)
    else:
        print(f"Dropped {w.item}. Saved by waiting: {format_amount(W.saved_by_waiting(s))}")
    return 0


# ---- import ---------------------------------------------------------------
def cmd_import(ctx: Ctx) -> int:
    a = ctx.args
    from pathlib import Path
    folder = Path(a.importers) if a.importers else I.IMPORTERS_DIR
    mapping_file = folder / f"{a.source}.json"
    if not mapping_file.exists():
        known = sorted(p.stem for p in folder.glob("*.json"))
        raise UserError(f"No importer called {a.source!r}. Known: {', '.join(known) or 'none yet'}")
    rows = I.propose(ctx.store, I.parse_statement(Path(a.file), json.loads(mapping_file.read_text()), a.source))
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    for r in rows:
        sign = "+" if r["type"] == "income" else "-"
        dup = f"  ⚠ possible duplicate of {', '.join(r['duplicates'])}" if r["duplicates"] else ""
        print(f"{r['n']:>3}. {r['date']} {sign}{format_amount(r['amount'])} {r['payee']}{dup}")
    return 0


def cmd_add_batch(ctx: Ctx) -> int:
    s = ctx.writable()
    try:
        rows = json.loads(open(ctx.args.file, encoding="utf-8").read())
    except (OSError, json.JSONDecodeError) as e:
        raise UserError(f"Can't read {ctx.args.file}: {e}")
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise UserError("The batch file must be a JSON list of transaction objects")
    existing = s.transactions()
    accepted: list[Transaction] = []
    for i, r in enumerate(rows, 1):
        try:
            raw = r["amount"]
            if isinstance(raw, bool) or not isinstance(raw, (int, str)):
                raise UserError(f"amount must be centavos (integer) or a peso string, not {raw!r}")
            amount = raw if isinstance(raw, int) else _amount(raw)
            if not isinstance(r["date"], str):
                raise UserError(f"date must be a YYYY-MM-DD string, not {r['date']!r}")
            t = Transaction(id="", date=_date(r["date"]), type=r["type"], amount=amount,
                            category=r.get("category", ""), account=r.get("account", ""),
                            to_account=r.get("to_account", ""), payee=r.get("payee", ""), note=r.get("note", ""),
                            goal=r.get("goal", ""), source=r.get("source", "import"), created_at=ctx.now)
            if t.type not in ("income", "expense", "transfer") or t.amount <= 0:
                raise UserError("type must be income/expense/transfer and amount positive")
            validate_txn(s, t)
            check_duplicates(s, t, bool(r.get("allow_duplicate")), existing + accepted)
        except DuplicateError as e:
            raise DuplicateError(f"row {i}: {e}")
        except (UserError, ValueError, KeyError, TypeError, AttributeError) as e:
            raise UserError(f"row {i}: {e}")
        accepted.append(t)
    all_txns = s.transactions()
    for t in accepted:
        t.id = next_txn_id(all_txns, t.date)
        all_txns.append(t)
    s.save_transactions(all_txns)
    print(f"Saved {len(accepted)} transactions.")
    for t in accepted:
        print("  " + txn_line(t))
    return 0


# ---- save -----------------------------------------------------------------
def cmd_save(ctx: Ctx) -> int:
    from fincore.gitsync import save
    from fincore.store import REPO_ROOT
    try:
        r = save(REPO_ROOT, ctx.args.message)
    except RuntimeError as e:
        raise UserError(str(e))
    print(r.detail)
    return 0


# ---- review / startup -----------------------------------------------------
def cmd_review(ctx: Ctx) -> int:
    s = ctx.writable()
    r = R.weekly_review(s, ctx.today)
    print(json.dumps(r, ensure_ascii=False, indent=1) if ctx.args.json else R.format_review(r))
    meta = s.meta()
    meta["last_review"] = ctx.today.isoformat()
    s.save_meta(meta)
    return 0


def cmd_report(ctx: Ctx) -> int:
    from fincore.report import month_report
    from fincore.report_html import render
    a = ctx.args
    if a.month:
        try:
            year, month = (int(x) for x in a.month.split("-"))
            date(year, month, 1)
        except ValueError:
            raise UserError(f"Not a month: {a.month!r} (use YYYY-MM)")
    else:
        year, month = ctx.today.year, ctx.today.month
    r = month_report(ctx.store, year, month, ctx.today)
    if a.html:
        with open(a.html, "w", encoding="utf-8") as f:
            f.write(render(r))
        print(f"Tracker page for {r['month']} written to {a.html}")
        return 0
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    s = r["summary"]
    print(r["month"])
    for label, key in (("Total income", "income"), ("Total expenses", "expenses"), ("Income - expenses", "net"),
                       ("Savings goal", "savings_goal"), ("Actual savings", "savings_actual"),
                       ("Debt payment goal", "debt_goal"), ("Actual debt paid", "debt_paid")):
        print(f"  {label}: {format_amount(s[key])}")
    print(f"  Money left this month: {format_amount(r['money_left'])}")
    if r["balances"]:
        print("Balances today:")
        for b in r["balances"]:
            print(f"  {b['name']}: {format_amount(b['balance'])}" + (" (savings, not counted)" if b["role"] == "savings" else ""))
    if r["to_pay"]:
        print("To pay:")
        for x in r["to_pay"]:
            amt = format_amount(x["expected"]) if x["expected"] is not None else "amount not set"
            print(f"  {x['due']}  {x['name']}: {amt} · {x['status']}")
    if r["savings_moves"]:
        print("Savings to move:")
        for x in r["savings_moves"]:
            if x["planned"]:
                print(f"  {x['goal']} ({x['period']}): {format_amount(x['moved'])} of "
                      f"{format_amount(x['planned'])} · {x['status']}")
            else:
                print(f"  {x['goal']}: no amount per pay period set")
    return 0


def cmd_setaside(ctx: Ctx) -> int:
    from fincore import safe as SF
    a = ctx.args
    if a.sa_cmd == "list":
        items = SF.set_asides(ctx.store)
        for x in items:
            print(f"{x['name']}: {format_amount(x['amount'])}" + (f" ({x['note']})" if x.get("note") else ""))
        print(f"Total set aside: {format_amount(sum(x['amount'] for x in items))}" if items else "Nothing set aside.")
        return 0
    s = ctx.writable()
    items = SF.set_asides(s)
    found = next((x for x in items if x["name"].lower() == a.name.lower()), None)
    if a.sa_cmd == "add":
        if found:
            raise UserError(f"{found['name']!r} is already set aside; use ./fin setaside set to change it")
        items.append({"name": a.name, "amount": _amount(a.amount), "note": a.note or "",
                      "added": ctx.today.isoformat()})
    elif found is None:
        raise UserError(f"Nothing set aside as {a.name!r}. Set-asides: {', '.join(x['name'] for x in items) or 'none'}")
    elif a.sa_cmd == "set":
        found["amount"] = _amount(a.amount)
    else:
        items.remove(found)
    SF.save_set_asides(s, items)
    print(f"Total set aside: {format_amount(sum(x['amount'] for x in items))}"
          + (f" ({', '.join(x['name'] for x in items)})" if items else ""))
    return 0


def cmd_safe(ctx: Ctx) -> int:
    from fincore import safe as SF
    a = ctx.args
    if a.except_ and not any(c.name.lower() == a.except_.lower() for c in ctx.store.categories()):
        raise UserError(f"No category {a.except_!r}")
    r = SF.safe_to_spend(ctx.store, ctx.today, _date(a.until) if a.until else None, a.except_)
    print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else SF.format_safe(r))
    return 0


def cmd_payday(ctx: Ctx) -> int:
    from fincore import plan as PL
    a = ctx.args
    if a.pd_cmd == "list":
        pay = PL.expected_pay(ctx.store)
        for k in ("15", "30"):
            print(f"{k}th: {format_amount(pay[k]) if k in pay else 'not set'}")
        return 0
    if a.day not in ("15", "30"):
        raise UserError("Payday is 15 or 30")
    s = ctx.writable()
    pay = PL.expected_pay(s)
    pay[a.day] = _amount(a.amount)
    PL.save_expected_pay(s, pay)
    print(f"Expected pay on the {a.day}th: {format_amount(pay[a.day])}")
    return 0


def cmd_plan(ctx: Ctx) -> int:
    from fincore import plan as PL
    a = ctx.args
    if a.periods < 1:
        raise UserError("--periods must be 1 or more")
    rs = PL.plans(ctx.store, _date(a.date) if a.date else ctx.today, a.periods)
    print(json.dumps(rs, ensure_ascii=False, indent=1) if a.json else "\n\n".join(PL.format_plan(r) for r in rs))
    return 0


def cmd_startup(ctx: Ctx) -> int:
    """Never fails: a broken hook must not block a session."""
    if ctx.args.sync:
        from fincore.gitsync import sync_from_main
        from fincore.store import REPO_ROOT
        try:
            for m in sync_from_main(REPO_ROOT):
                print(m)
        except Exception as e:  # noqa: BLE001
            print(f"⚠ Couldn't sync with main ({e}).")
    try:
        lines = R.startup_summary(ctx.store, ctx.now)
    except NoDataError:
        warn = guard.visibility_warning(default_data_dir())
        print((warn + "\n" if warn else "") + 'No data yet — say "set me up" to start.')
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"fin startup: couldn't build the summary ({e})")
        return 0
    print("\n".join(lines) if lines else "All good.")
    return 0


# ---- parser -------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="./fin", description="Personal finance ledger (₱, pay-period budgets).")
    p.add_argument("--today", help=argparse.SUPPRESS)
    p.add_argument("--now", help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="command", metavar="command")

    sub.add_parser("init", help="create data/ from defaults").set_defaults(func=cmd_init)

    a = sub.add_parser("add", help="record income, expense or transfer")
    a.add_argument("type", choices=["expense", "income", "transfer"])
    a.add_argument("amount")
    for f in ("category", "account", "to", "payee", "note", "goal", "date", "source"):
        a.add_argument(f"--{f}")
    a.add_argument("--allow-duplicate", action="store_true")
    a.set_defaults(func=cmd_add)

    l = sub.add_parser("list", help="list/search transactions")
    l.add_argument("--from", dest="from_")
    l.add_argument("--to")
    l.add_argument("--category")
    l.add_argument("--search")
    l.add_argument("--json", action="store_true")
    l.set_defaults(func=cmd_list)

    e = sub.add_parser("edit", help="correct a transaction")
    e.add_argument("id")
    for f in ("amount", "category", "date", "payee", "note", "account", "goal", "to"):
        e.add_argument(f"--{f}")
    e.set_defaults(func=cmd_edit)

    d = sub.add_parser("delete", help="delete a transaction")
    d.add_argument("id")
    d.set_defaults(func=cmd_delete)

    st = sub.add_parser("status", help="budget usage this pay period")
    st.add_argument("--date")
    st.add_argument("--json", action="store_true")
    st.set_defaults(func=cmd_status)

    ac = sub.add_parser("account", help="list/add/set/remove accounts")
    acs = ac.add_subparsers(dest="acct_cmd", required=True)
    acs.add_parser("list")
    x = acs.add_parser("add")
    x.add_argument("name")
    x.add_argument("--opening", help="opening balance")
    x = acs.add_parser("set", help="set today's balance or the account's role")
    x.add_argument("name")
    x.add_argument("--balance", help="what's in the account today")
    x.add_argument("--role", help="spending (default), savings, or hidden")
    x = acs.add_parser("remove")
    x.add_argument("name")
    ac.set_defaults(func=cmd_account)

    ca = sub.add_parser("category", help="list/add/set categories and limits")
    cas = ca.add_subparsers(dest="cat_cmd", required=True)
    cas.add_parser("list")
    for name in ("set", "add"):
        x = cas.add_parser(name)
        x.add_argument("name")
        x.add_argument("--limit", help="per pay period, or 'none'")
        x.add_argument("--essential", help="yes/no")
        x.add_argument("--bill-day", help="fixed bill: day of the month it's due (or 'none')")
        x.add_argument("--every", type=int, help="months between bills (default 1)")
        x.add_argument("--from", dest="bill_from", help="one due date YYYY-MM-DD (needed when --every > 1)")
        x.add_argument("--bill-amount", help="expected bill (default: the limit), or 'none'")
        x.add_argument("--via", help="direct (default), card (auto-charged to a card) or owed (taken off someone's debt)")
        if name == "add":
            x.add_argument("--income", action="store_true")
    ca.set_defaults(func=cmd_category)

    g = sub.add_parser("goal", help="savings goals")
    gs = g.add_subparsers(dest="goal_cmd", required=True)
    gl = gs.add_parser("list")
    gl.add_argument("--json", action="store_true")
    for name in ("set", "add"):
        x = gs.add_parser(name)
        x.add_argument("name")
        x.add_argument("--target", help="amount or 'auto'")
        x.add_argument("--months", type=int)
        x.add_argument("--planned", help="planned savings per pay period")
        x.add_argument("--priority", type=int)
    for name in ("contribute", "withdraw"):
        x = gs.add_parser(name)
        x.add_argument("name")
        x.add_argument("amount")
        x.add_argument("--from", dest="from_", required=True)
        x.add_argument("--to", required=True)
        x.add_argument("--date")
    x = gs.add_parser("opening", help="money already saved before using fin")
    x.add_argument("name")
    x.add_argument("amount")
    x.add_argument("--account", required=True)
    g.set_defaults(func=cmd_goal)

    c = sub.add_parser("check", help="before-you-buy check")
    c.add_argument("amount")
    c.add_argument("category")
    c.add_argument("--account", help="how you'd pay (shows card debt)")
    c.add_argument("--months", type=int, help="installment months")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_check)

    w = sub.add_parser("wait", help="cooling-off list")
    ws = w.add_subparsers(dest="wait_cmd", required=True)
    x = ws.add_parser("add")
    x.add_argument("item")
    x.add_argument("amount")
    x.add_argument("category")
    x.add_argument("--hours", type=int, default=W.DEFAULT_HOURS)
    ws.add_parser("list")
    ws.add_parser("due")
    x = ws.add_parser("buy")
    x.add_argument("id")
    x.add_argument("--account")
    x = ws.add_parser("drop")
    x.add_argument("id")
    w.set_defaults(func=cmd_wait)

    r = sub.add_parser("review", help="weekly review")
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_review)
    sa = sub.add_parser("setaside", help="earmark money in your spending accounts")
    sas = sa.add_subparsers(dest="sa_cmd", required=True)
    sas.add_parser("list")
    x = sas.add_parser("add")
    x.add_argument("name")
    x.add_argument("amount")
    x.add_argument("--note")
    x = sas.add_parser("set")
    x.add_argument("name")
    x.add_argument("amount")
    x = sas.add_parser("drop")
    x.add_argument("name")
    sa.set_defaults(func=cmd_setaside)
    pd = sub.add_parser("payday", help="expected take-home pay per payday")
    pds = pd.add_subparsers(dest="pd_cmd", required=True)
    pds.add_parser("list")
    x = pds.add_parser("set")
    x.add_argument("day", help="15 or 30")
    x.add_argument("amount")
    pd.set_defaults(func=cmd_payday)
    pl = sub.add_parser("plan", help="pay-period plan: expected pay vs bills, installments, budgets, savings")
    pl.add_argument("--date", help="plan from the pay period after this date (default: today)")
    pl.add_argument("--periods", type=int, default=2)
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_plan)
    sf = sub.add_parser("safe", help="how much is safe to spend until payday")
    sf.add_argument("--until", help="YYYY-MM-DD, the payday to plan to (default: the next one)")
    sf.add_argument("--except", dest="except_", help="category you're asking about (its budget isn't held back)")
    sf.add_argument("--json", action="store_true")
    sf.set_defaults(func=cmd_safe)
    rp = sub.add_parser("report", help="monthly tracker (summary, charts page)")
    rp.add_argument("--month", help="YYYY-MM (default: this month)")
    rp.add_argument("--json", action="store_true")
    rp.add_argument("--html", help="write the tracker page to this file")
    rp.set_defaults(func=cmd_report)
    su = sub.add_parser("startup", help="session-start summary")
    su.add_argument("--sync", action="store_true", help="first bring in the latest ledger from main")
    su.set_defaults(func=cmd_startup)

    im = sub.add_parser("import", help="read a bank/e-wallet CSV (no writes)")
    ims = im.add_subparsers(dest="import_cmd", required=True)
    x = ims.add_parser("parse")
    x.add_argument("file")
    x.add_argument("--source", required=True, help="importer name in importers/")
    x.add_argument("--importers", help=argparse.SUPPRESS)
    x.add_argument("--json", action="store_true")
    im.set_defaults(func=cmd_import)
    ab = sub.add_parser("add-batch", help="save confirmed rows from a JSON file, all or nothing")
    ab.add_argument("file")
    ab.set_defaults(func=cmd_add_batch)

    sv = sub.add_parser("save", help="commit data/ and push it to main")
    sv.add_argument("-m", "--message", required=True)
    sv.set_defaults(func=cmd_save)

    for register in EXTRA_COMMANDS:
        register(sub)
    return p


EXTRA_COMMANDS: list = []


def main(argv=None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return 1 if e.code else 0
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(Ctx(args))
    except NoDataError as e:
        print(str(e), file=sys.stderr)
        return 1
    except guard.GuardError as e:
        print(str(e), file=sys.stderr)
        return 2
    except (UserError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return getattr(e, "code", 1)
    except OSError as e:
        print(f"Can't access {getattr(e, 'filename', '') or 'a file'}: {e.strerror or e}", file=sys.stderr)
        return 1


def run(argv) -> tuple[int, str, str]:
    """Test helper: run the CLI capturing stdout/stderr."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


from fincore import cli_debt  # noqa: E402,F401  (registers debt commands)
