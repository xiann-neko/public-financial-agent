"""Debts (credit cards, loans), card installments, and money owed to the owner."""
import calendar
from datetime import date

from typing import Optional

from fincore.model import Account, Category, Installment
from fincore.store import Store

INTEREST_CATEGORY = "Interest & fees"


def add_months(d: date, k: int, day: int) -> date:
    y, m = divmod(d.month - 1 + k, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def has_interest(i: Installment) -> bool:
    """True when the plan charges interest; rounding up to whole centavos isn't interest."""
    return i.monthly > -(-i.total // i.months)


def installment_shares(i: Installment) -> list[tuple[date, int, int]]:
    """(billing date, principal part, interest part) for each monthly share."""
    day = i.billing_day or i.first_billing.day
    dates = [i.first_billing] + [add_months(i.first_billing, k, day) for k in range(1, i.months)]
    if not has_interest(i):
        base = i.total // i.months
        principals = [base] * (i.months - 1) + [i.total - base * (i.months - 1)]
        return [(d, p, 0) for d, p in zip(dates, principals)]
    total_interest = i.monthly * i.months - i.total
    each = total_interest // i.months
    interests = [total_interest - each * (i.months - 1)] + [each] * (i.months - 1)
    return [(d, i.monthly - x, x) for d, x in zip(dates, interests)]


def installment_remaining(items: list[Installment], card: str, on: date) -> int:
    """Principal of shares not yet billed on `on` (still owed, but on its own schedule)."""
    return sum(p for i in items if i.card == card for d, p, _ in installment_shares(i) if d > on)


def owed(store: Store, acct: Account, on: date) -> int:
    """Balance owed on a card/loan (for cards: excluding unbilled installment shares),
    or owed to the owner on a receivable, as of `on`."""
    total = acct.opening_balance
    for t in store.transactions():
        if t.date > on:
            continue
        if t.type == "transfer":
            if t.to_account == acct.name:
                total += t.amount if acct.kind == "receivable" else -t.amount
            if t.account == acct.name:
                total += -t.amount if acct.kind == "receivable" else t.amount
        elif t.type == "expense" and t.account == acct.name:
            total += -t.amount if acct.kind == "receivable" else t.amount
        elif t.type == "income" and t.account == acct.name:
            total += t.amount if acct.kind == "receivable" else -t.amount
    if acct.kind == "credit_card":
        # Billed installment shares (with any interest) join the statement balance;
        # unbilled ones are reported separately by installment_remaining.
        total += sum(p + x for i in store.installments() if i.card == acct.name
                     for d, p, x in installment_shares(i) if d <= on)
    return total


def cash_flow(store: Store, name: str, start: date, end: date) -> int:
    """Net money into a cash account between start and end (inclusive)."""
    total = 0
    for t in store.transactions():
        if not start <= t.date <= end:
            continue
        if t.type == "income" and t.account == name:
            total += t.amount
        elif t.type == "expense" and t.account == name:
            total -= t.amount
        elif t.type == "transfer":
            if t.to_account == name:
                total += t.amount
            if t.account == name:
                total -= t.amount
    return total


def balance(store: Store, acct: Account, on: date) -> int:
    """Money in a cash account as of `on`: its opening balance plus everything logged since."""
    return acct.opening_balance + cash_flow(store, acct.name, date.min, on)


def ensure_interest_category(store: Store) -> None:
    cats = store.categories()
    if not any(c.name == INTEREST_CATEGORY for c in cats):
        store.save_budget(cats + [Category(INTEREST_CATEGORY, "expense", None, False)])


def next_due(acct: Account, today: date) -> Optional[date]:
    """The next due date on or after today (day clamped to the month's length)."""
    if not acct.due_day:
        return None
    this = add_months(today.replace(day=1), 0, acct.due_day)
    return this if this >= today else add_months(today.replace(day=1), 1, acct.due_day)


def previous_due(acct: Account, today: date) -> Optional[date]:
    """The latest due date strictly before today."""
    if not acct.due_day:
        return None
    this = add_months(today.replace(day=1), 0, acct.due_day)
    return this if this < today else add_months(today.replace(day=1), -1, acct.due_day)


def debt_summary(store: Store, today: date) -> dict:
    items = store.installments()
    rows = []
    for a in store.accounts():
        if not a.is_debt:
            continue
        o = owed(store, a, today)
        nd = next_due(a, today)
        rows.append({
            "name": a.name, "kind": a.kind, "owed": o,
            "installments_left": installment_remaining(items, a.name, today) if a.kind == "credit_card" else 0,
            "next_due": nd.isoformat() if nd else None,
            "days_to_due": (nd - today).days if nd else None,
            "limit_used_pct": round(100 * o / a.credit_limit, 1) if a.credit_limit else None,
            "rate_monthly": a.rate_monthly, "payment": a.payment, "end": a.end})
    to_you = sum(owed(store, a, today) for a in store.accounts() if a.kind == "receivable")
    return {"debts": rows, "total_owed": sum(r["owed"] + r["installments_left"] for r in rows),
            "owed_to_you": to_you}
