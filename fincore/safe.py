"""Set-asides (money earmarked inside spending accounts) and safe-to-spend until the next payday."""
import json
from datetime import date, timedelta
from typing import Optional

from fincore.budget import period_status
from fincore.debts import balance
from fincore.money import format_amount
from fincore.periods import period_for
from fincore.store import Store, _atomic_write

FILE = "setasides.json"


def set_asides(store: Store) -> list[dict]:
    path = store.dir / FILE
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["set_asides"]


def save_set_asides(store: Store, items: list[dict]) -> None:
    _atomic_write(store.dir / FILE, json.dumps({"set_asides": items}, indent=2, ensure_ascii=False) + "\n")


def next_payday(today: date) -> date:
    return period_for(today).end + timedelta(days=1)


def safe_to_spend(store: Store, today: date, until: Optional[date] = None,
                  except_category: Optional[str] = None) -> dict:
    from fincore.report import to_pay  # avoid an import cycle
    until = until or next_payday(today)
    accounts = [a for a in store.accounts() if a.kind == "cash" and a.role == "spending"]
    money = [{"name": a.name, "amount": balance(store, a, today)} for a in accounts]
    asides = [{"name": s["name"], "amount": s["amount"]} for s in set_asides(store)]

    bills, d = [], date(today.year, today.month, 1)
    while d < until:  # every month the window touches
        nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        for b in to_pay(store, d, nxt - timedelta(days=1), today):
            due = date.fromisoformat(b["due"])
            if today <= due < until and b["status"] != "paid" and b["expected"] and b["kind"] != "owed":
                bills.append({"name": b["name"], "due": b["due"], "amount": max(b["expected"] - b["paid"], 0)})
        d = nxt

    bill_cats = {c.name for c in store.categories() if c.bill_day}
    skip = (except_category or "").lower()
    budgets, p = [], period_for(today)
    while p.start < until:
        for s in period_status(store, p):
            if s.limit is None or s.category in bill_cats or s.category.lower() == skip:
                continue
            left = max(s.remaining, 0)
            if left:
                budgets.append({"name": s.category, "period": p.label, "amount": left})
        p = period_for(p.end + timedelta(days=1))

    total = sum(m["amount"] for m in money)
    held = sum(x["amount"] for x in asides + bills + budgets)
    return {"until": until.isoformat(), "money": money, "money_total": total, "set_asides": asides,
            "bills": bills, "budgets": budgets, "safe": total - held, "except": except_category}


def format_safe(r: dict) -> str:
    until = date.fromisoformat(r["until"])
    lines = [f"Spending money today: {format_amount(r['money_total'])}"]
    for title, key in (("Set aside", "set_asides"), ("Bills due before payday", "bills"),
                       ("Day-to-day budgets until payday", "budgets")):
        rows = r[key]
        if rows:
            lines.append(f"- {title}: {format_amount(sum(x['amount'] for x in rows))}")
            for x in rows:
                extra = f" ({x['period']})" if "period" in x else (f" (due {x['due']})" if "due" in x else "")
                lines.append(f"    {x['name']}{extra}: {format_amount(x['amount'])}")
    label = f"Safe to spend until {until:%b} {until.day}"
    if r["except"]:
        label += f" on {r['except']}"
    if r["safe"] < 0:
        lines.append(f"{label}: nothing. Short by {format_amount(-r['safe'])}")
    else:
        lines.append(f"{label}: {format_amount(r['safe'])}")
    return "\n".join(lines)
