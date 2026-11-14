"""Monthly tracker: income, spending, savings and debt for one calendar month,
plus a snapshot of debts, money owed to you and goals. All values are centavos."""
import calendar
from datetime import date, timedelta

from fincore import goals as G
from fincore.budget import expense_events, period_status
from fincore.debts import add_months, balance, cash_flow, debt_summary, installment_shares, owed
from fincore.periods import Period, period_for
from fincore.store import Store

RECEIVABLE_PREFIX = "Owed by "
TREND_MONTHS = 6


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _income(store: Store, start: date, end: date) -> int:
    return sum(t.amount for t in store.transactions() if t.type == "income" and start <= t.date <= end)


def _spent(store: Store, start: date, end: date) -> int:
    return sum(a for _, _, a in expense_events(store, start, end))


def periods_in_month(start: date, end: date) -> list[Period]:
    """Pay periods that start inside the month (the 15th and the 30th / last of Feb)."""
    out, p = [], period_for(start)
    if p.start < start:
        p = period_for(p.end + timedelta(days=1))
    while p.start <= end:
        out.append(p)
        p = period_for(p.end + timedelta(days=1))
    return out


def periods_shown(start: date, end: date, today: date) -> list[Period]:
    """Pay periods that overlap the month and have already started (the current one included)."""
    out, p = [], period_for(start)
    while p.start <= end and p.start <= today:
        out.append(p)
        p = period_for(p.end + timedelta(days=1))
    return out


def _saved(store: Store, start: date, end: date) -> int:
    """Net goal contributions in the range, not counting money saved before tracking."""
    goals = store.goals()
    return sum(G._signed(t, g) for t in store.transactions()
               if start <= t.date <= end and t.source != "opening" for g in goals)


def _due_in_month(day: int, start: date) -> date:
    return add_months(start, 0, day)


EARLY_DAYS = 5  # savings moved this many days before a payday count toward that pay period


def _status(expected, paid: int, due: date, today: date) -> str:
    if paid and (expected is None or paid >= expected):
        return "paid"
    if paid:
        return "partly paid"
    return "overdue" if due < today else "due"


def _bill_dates(c, start: date, end: date) -> list[date]:
    d = add_months(start, 0, c.bill_day)
    if c.bill_every > 1 and c.bill_from:
        anchor = date.fromisoformat(c.bill_from)
        if ((d.year - anchor.year) * 12 + d.month - anchor.month) % c.bill_every or d < anchor:
            return []
    return [d] if start <= d <= end else []


def to_pay(store: Store, start: date, end: date, today: date) -> list[dict]:
    out = []
    for c in store.categories():
        if c.kind != "expense" or not c.bill_day or c.bill_via == "card":
            continue  # card-charged bills are paid through the card statement
        for due in _bill_dates(c, start, end):
            lo, hi = due - timedelta(days=15), due + timedelta(days=14)
            paid = sum(a for _, cat, a in expense_events(store, lo, hi) if cat == c.name)
            expected = c.bill_amount if c.bill_amount is not None else c.limit
            out.append({"name": c.name, "kind": "owed" if c.bill_via == "owed" else "bill",
                        "due": due.isoformat(), "expected": expected,
                        "paid": paid, "status": _status(expected, paid, due, today)})
    for a in store.accounts():
        if not (a.is_debt and a.due_day and a.payment):
            continue
        due = add_months(start, 0, a.due_day)
        if a.tracked_since and due.isoformat() < a.tracked_since:
            continue  # due before tracking began: paid outside fin
        prev = add_months(due, -1, a.due_day)
        paid = sum(t.amount for t in store.transactions() if t.type == "transfer" and t.to_account == a.name
                   and prev < t.date <= due + timedelta(days=10))
        out.append({"name": a.name, "kind": "card" if a.kind == "credit_card" else "loan", "due": due.isoformat(),
                    "expected": a.payment, "paid": paid, "status": _status(a.payment, paid, due, today)})
    return sorted(out, key=lambda x: (x["due"], x["name"]))


def _savings_period(d: date) -> Period:
    p = period_for(d)
    nxt = p.end + timedelta(days=1)
    return period_for(nxt) if (nxt - d).days <= EARLY_DAYS else p


def savings_moves(store: Store, start: date, end: date, today: date) -> list[dict]:
    goals = sorted(store.goals(), key=lambda g: g.priority)
    txns = [t for t in store.transactions() if t.type == "transfer" and t.goal and t.source != "opening"]
    out = []
    for g in goals:
        if not g.planned_per_period:
            out.append({"goal": g.name, "period": None, "planned": 0, "moved": 0, "status": "no amount set"})
            continue
        for p in periods_in_month(start, end):
            moved = sum(G._signed(t, g) for t in txns if _savings_period(t.date) == p)
            if moved >= g.planned_per_period:
                st = "moved"
            elif moved > 0:
                st = "partly moved"
            elif p.start - timedelta(days=EARLY_DAYS) > today:
                st = "upcoming"
            else:
                st = "not yet moved"
            out.append({"goal": g.name, "period": p.label, "planned": g.planned_per_period, "moved": moved,
                        "status": st})
    return out


def money_in(store: Store, start: date, end: date) -> list[dict]:
    receivables = {a.name for a in store.accounts() if a.kind == "receivable"}
    out = []
    for t in store.transactions():
        if not start <= t.date <= end:
            continue
        if t.type == "income":
            out.append({"date": t.date.isoformat(), "what": t.payee or t.category, "category": t.category,
                        "account": t.account, "amount": t.amount, "note": t.note})
        elif t.type == "transfer" and t.account in receivables:
            out.append({"date": t.date.isoformat(), "what": t.account[len(RECEIVABLE_PREFIX):],
                        "category": "repayment", "account": t.to_account, "amount": t.amount, "note": t.note})
    return sorted(out, key=lambda x: x["date"], reverse=True)


def money_out(store: Store, start: date, end: date) -> list[dict]:
    out = [{"date": t.date.isoformat(), "what": t.payee or t.category, "category": t.category,
            "account": t.account, "amount": t.amount, "note": t.note}
           for t in store.transactions() if t.type == "expense" and start <= t.date <= end]
    for i in store.installments():
        for d, principal, interest in installment_shares(i):
            if start <= d <= end:
                out.append({"date": d.isoformat(), "what": i.item, "category": i.category, "account": i.card,
                            "amount": principal + interest, "note": "installment"})
    return sorted(out, key=lambda x: x["date"], reverse=True)


def _set_asides(store: Store) -> list[dict]:
    from fincore.safe import set_asides
    return [{"name": x["name"], "amount": x["amount"]} for x in set_asides(store)]


def month_report(store: Store, year: int, month: int, today: date) -> dict:
    start, end = month_bounds(year, month)
    accounts = store.accounts()
    debts = [a for a in accounts if a.is_debt]
    debt_names = {a.name for a in debts}

    events = expense_events(store, start, end)
    by_cat: dict[str, int] = {}
    for _, category, amount in events:
        by_cat[category] = by_cat.get(category, 0) + amount
    income = _income(store, start, end)
    spent = sum(by_cat.values())

    periods = periods_in_month(start, end)
    goals = sorted(store.goals(), key=lambda g: g.priority)
    savings_goal = sum(g.planned_per_period for g in goals) * len(periods)

    # A due date from before the card was tracked belongs to a bill paid outside fin.
    bills = [{"name": a.name, "due": _due_in_month(a.due_day, start).isoformat(), "amount": a.payment}
             for a in debts if a.due_day and a.payment
             and not (a.tracked_since and _due_in_month(a.due_day, start).isoformat() < a.tracked_since)]
    paid = [t for t in store.transactions()
            if t.type == "transfer" and t.to_account in debt_names and start <= t.date <= end]

    trend = []
    for k in range(TREND_MONTHS - 1, -1, -1):
        s = add_months(start, -k, 1)
        s_start, s_end = month_bounds(s.year, s.month)
        trend.append({"month": s_start.strftime("%b %Y"), "income": _income(store, s_start, s_end),
                      "expenses": _spent(store, s_start, s_end)})

    snap = debt_summary(store, today)
    installments = []
    for i in store.installments():
        shares = installment_shares(i)
        left = [d for d, _, _ in shares if d > today]
        if left:
            installments.append({"card": i.card, "item": i.item, "monthly": shares[-1][1] + shares[-1][2],
                                 "left": len(left), "last": left[-1].isoformat()})
    people = [{"name": a.name[len(RECEIVABLE_PREFIX):], "owed": owed(store, a, today)}
              for a in accounts if a.kind == "receivable"]

    return {
        "month": start.strftime("%B %Y"), "start": start.isoformat(), "end": end.isoformat(),
        "today": today.isoformat(),
        "summary": {
            "income": income, "expenses": spent, "net": income - spent,
            "savings_goal": savings_goal, "savings_actual": _saved(store, start, end),
            "debt_goal": sum(b["amount"] for b in bills if start.isoformat() <= b["due"] <= end.isoformat()),
            "debt_paid": sum(t.amount for t in paid),
        },
        "debt_bills": [b for b in bills if start.isoformat() <= b["due"] <= end.isoformat()],
        "spend_by_category": [{"category": c, "amount": a}
                              for c, a in sorted(by_cat.items(), key=lambda kv: -kv[1])],
        "periods": [{"label": p.label, "start": p.start.isoformat(), "end": p.end.isoformat(),
                     "categories": [s.__dict__ for s in period_status(store, p) if s.spent or s.limit]}
                    for p in periods_shown(start, end, today)],
        "trend": trend,
        "debts": snap["debts"], "debt_total": snap["total_owed"],
        "installments": sorted(installments, key=lambda x: x["last"]),
        "owed_to_you": sorted([p for p in people if p["owed"] > 0], key=lambda p: -p["owed"]),
        "owed_to_you_total": snap["owed_to_you"],
        "to_pay": to_pay(store, start, end, today),
        "savings_moves": savings_moves(store, start, end, today),
        "inflows": money_in(store, start, end),
        "outflows": money_out(store, start, end),
        "money_left": sum(cash_flow(store, a.name, start, end) for a in accounts
                          if a.kind == "cash" and a.role == "spending"),
        "balances": [{"name": a.name, "role": a.role, "balance": balance(store, a, today)}
                     for a in accounts if a.kind == "cash" and a.role in ("spending", "savings")],
        "set_asides": _set_asides(store),
        "goals": [{"name": g.name, "saved": G.progress(store, g), "target": G.target(store, g, today),
                   "planned": g.planned_per_period} for g in goals],
    }
