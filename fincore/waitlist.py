"""Before-you-buy check and the cooling-off list."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, Optional

from fincore import goals as G
from fincore.budget import period_status
from fincore.model import Transaction, WaitItem
from fincore.periods import period_for
from fincore.store import Store

DEFAULT_HOURS = 48


@dataclass
class CheckResult:
    amount: int
    category: str
    essential: bool
    limit: Optional[int]
    remaining_before: Optional[int]
    remaining_after: Optional[int]
    goal: Optional[str]
    ef_delay_days: Optional[int]
    ef_rate_zero: bool
    suggest_wait: bool
    monthly_share: Optional[int] = None  # installment: what the budget sees each month
    card: Optional[str] = None
    card_owed_before: Optional[int] = None
    card_owed_after: Optional[int] = None
    card_limit_pct_after: Optional[float] = None


def _category(store: Store, name: str):
    for c in store.categories():
        if c.kind == "expense" and c.name.lower() == name.lower():
            return c
    names = ", ".join(c.name for c in store.categories() if c.kind == "expense")
    raise ValueError(f"Unknown expense category {name!r}. Options: {names}")


def priority_goal(store: Store, today: date):
    for g in sorted(store.goals(), key=lambda g: g.priority):
        tgt = G.target(store, g, today)
        if tgt is None or G.progress(store, g) < tgt:
            return g
    return None


def check_purchase(store: Store, amount: int, category: str, today: date,
                   account: Optional[str] = None, months: Optional[int] = None) -> CheckResult:
    from fincore.debts import owed
    if months is not None and months < 1:
        raise ValueError("--months must be at least 1")
    cat = _category(store, category)
    share = -(-amount // months) if months else None
    budget_amount = share or amount
    st = next(s for s in period_status(store, period_for(today)) if s.category == cat.name)
    goal = priority_goal(store, today)
    delay, rate_zero = None, False
    if goal is not None:
        rate = G.savings_rate(store, goal, today)
        delay = G.delay_days(amount, rate)
        rate_zero = rate <= 0
    r = CheckResult(
        amount=amount, category=cat.name, essential=cat.essential, limit=cat.limit,
        remaining_before=st.remaining,
        remaining_after=None if st.remaining is None else st.remaining - budget_amount,
        goal=goal.name if goal else None, ef_delay_days=delay, ef_rate_zero=rate_zero,
        suggest_wait=not cat.essential, monthly_share=share)
    if account:
        acct = next((a for a in store.accounts() if a.name.lower() == account.lower()), None)
        if acct is None:
            raise ValueError(f"Unknown account {account!r}. Accounts: {', '.join(a.name for a in store.accounts())}")
        if acct.kind == "credit_card":
            before = owed(store, acct, today)
            r.card, r.card_owed_before, r.card_owed_after = acct.name, before, before + amount
            if acct.credit_limit:
                r.card_limit_pct_after = round(100 * r.card_owed_after / acct.credit_limit, 1)
    return r


def add_item(store: Store, item: str, price: int, category: str, now: datetime,
             hours: int = DEFAULT_HOURS) -> WaitItem:
    cat = _category(store, category)
    w = WaitItem(id=store.new_wait_id(), item=item, price=price, category=cat.name, added_at=now,
                 due_at=now + timedelta(hours=hours))
    store.save_waitlist(store.waitlist() + [w])
    return w


def pending(store: Store) -> list[WaitItem]:
    return [w for w in store.waitlist() if w.outcome == "pending"]


def due_items(store: Store, now: datetime) -> list[WaitItem]:
    return [w for w in pending(store) if w.due_at <= now]


def resolve(store: Store, wait_id: str, outcome: Literal["bought", "dropped"], now: datetime,
            account: Optional[str] = None) -> WaitItem:
    items = store.waitlist()
    w = next((x for x in items if x.id == wait_id), None)
    if w is None:
        raise ValueError(f"No cooling-off item with id {wait_id!r}")
    if w.outcome != "pending":
        raise ValueError(f"{w.item} was already marked {w.outcome}")
    if outcome == "bought":
        accounts = [a.name for a in store.accounts()]
        if account not in accounts:
            raise ValueError(f"Say which account paid (--account). Accounts: {', '.join(accounts)}")
        t = Transaction(id=store.new_txn_id(now.date()), date=now.date(), type="expense", amount=w.price,
                        category=w.category, account=account, payee=w.item, source="waitlist", created_at=now)
        store.save_transactions(store.transactions() + [t])
        w.txn_id = t.id
    w.outcome, w.resolved_at = outcome, now
    store.save_waitlist(items)
    return w


def saved_by_waiting(store: Store) -> int:
    return sum(w.price for w in store.waitlist() if w.outcome == "dropped")
