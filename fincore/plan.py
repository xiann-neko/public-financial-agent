"""Pay-period plan: does the expected pay cover bills, installments, budgets and savings?"""
import json
from datetime import date, timedelta

from fincore.debts import installment_shares
from fincore.money import format_amount
from fincore.periods import Period, period_for
from fincore.store import Store, _atomic_write

FILE = "plan.json"


def expected_pay(store: Store) -> dict:
    path = store.dir / FILE
    return json.loads(path.read_text(encoding="utf-8")).get("pay", {}) if path.exists() else {}


def save_expected_pay(store: Store, pay: dict) -> None:
    _atomic_write(store.dir / FILE, json.dumps({"pay": pay}, indent=2) + "\n")


def payday_key(p: Period) -> str:
    return "15" if p.start.day == 15 else "30"


def _bill_due_in(c, p: Period) -> list[date]:
    from fincore.report import _bill_dates  # avoid an import cycle
    out, d = [], p.start.replace(day=1)
    while d <= p.end:
        nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        out += [x for x in _bill_dates(c, d, nxt - timedelta(days=1)) if p.start <= x <= p.end]
        d = nxt
    return out


def period_plan(store: Store, p: Period) -> dict:
    pay = expected_pay(store).get(payday_key(p))
    cats = [c for c in store.categories() if c.kind == "expense"]
    bills, offset = [], []
    for c in cats:
        if c.bill_day and c.bill_via == "owed":  # no cash: taken off someone's debt
            amount = c.bill_amount if c.bill_amount is not None else c.limit
            offset += [{"name": c.name, "due": d.isoformat(), "amount": amount or 0} for d in _bill_due_in(c, p)]
        elif c.bill_day:
            amount = c.bill_amount if c.bill_amount is not None else c.limit
            for d in _bill_due_in(c, p):
                bills.append({"name": c.name, "due": d.isoformat(), "amount": amount or 0})
    installments = []
    for i in store.installments():
        for d, principal, interest in installment_shares(i):
            if p.start <= d <= p.end:
                installments.append({"name": i.item, "card": i.card, "category": i.category,
                                     "due": d.isoformat(), "amount": principal + interest})
    budgets = [{"name": c.name, "amount": c.limit} for c in cats if c.limit and not c.bill_day]
    savings = [{"name": g.name, "amount": g.planned_per_period}
               for g in sorted(store.goals(), key=lambda g: g.priority) if g.planned_per_period]
    out = sum(x["amount"] for x in bills + installments + budgets + savings)
    return {"period": p.label, "start": p.start.isoformat(), "end": p.end.isoformat(), "pay": pay,
            "bills": bills, "installments": installments, "budgets": budgets, "savings": savings,
            "not_cash": offset, "total_out": out, "left": None if pay is None else pay - out}


def plans(store: Store, today: date, count: int = 2) -> list[dict]:
    out, p = [], period_for(today)
    if p.end <= today:  # the current period ends today: plan from the next payday
        p = period_for(p.end + timedelta(days=1))
    for _ in range(count):
        out.append(period_plan(store, p))
        p = period_for(p.end + timedelta(days=1))
    return out


def format_plan(r: dict) -> str:
    lines = [f"Pay period {r['period']}: expected pay "
             + (format_amount(r["pay"]) if r["pay"] is not None else "not set (./fin payday set 15|30 AMOUNT)")]
    for title, key in (("Bills due", "bills"), ("Card installments billed", "installments"),
                       ("Day-to-day budgets", "budgets"), ("Savings", "savings")):
        rows = r[key]
        if rows:
            lines.append(f"- {title}: {format_amount(sum(x['amount'] for x in rows))}")
            for x in rows:
                extra = f" ({x['due']})" if "due" in x else ""
                lines.append(f"    {x['name']}{extra}: {format_amount(x['amount'])}")
    for x in r["not_cash"]:
        lines.append(f"  (not counted: {x['name']} {format_amount(x['amount'])} on {x['due']} is taken off money owed to you)")
    lines.append(f"Total going out: {format_amount(r['total_out'])}")
    if r["left"] is None:
        lines.append("Left over: unknown until the expected pay is set")
    elif r["left"] >= 0:
        lines.append(f"Left over: {format_amount(r['left'])}")
    else:
        lines.append(f"Short by: {format_amount(-r['left'])}")
    return "\n".join(lines)
