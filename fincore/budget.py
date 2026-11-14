"""Budget status for one pay period."""
from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional

from fincore.money import format_amount
from fincore.periods import Period
from fincore.store import Store

NEAR_RATIO = 0.8


@dataclass
class CategoryStatus:
    category: str
    limit: Optional[int]
    spent: int
    remaining: Optional[int]
    ratio: Optional[float]
    level: Literal["ok", "near", "over", "no-limit"]


def _level(spent: int, limit: Optional[int]) -> str:
    if limit is None:
        return "no-limit"
    if spent > limit:
        return "over"
    if spent >= limit * NEAR_RATIO:
        return "near"
    return "ok"


def expense_events(store: Store, start: date, end: date) -> list[tuple[date, str, int]]:
    """Everything that counts as spending between start and end (inclusive):
    expense transactions plus card-installment shares billed in that range."""
    from fincore.debts import INTEREST_CATEGORY, installment_shares
    out = [(t.date, t.category, t.amount) for t in store.transactions()
           if t.type == "expense" and start <= t.date <= end]
    for i in store.installments():
        for d, principal, interest in installment_shares(i):
            if start <= d <= end:
                out.append((d, i.category, principal))
                if interest:
                    out.append((d, INTEREST_CATEGORY, interest))
    return sorted(out)


def period_status(store: Store, period: Period) -> list[CategoryStatus]:
    spent: dict[str, int] = {}
    for _, category, amount in expense_events(store, period.start, period.end):
        spent[category] = spent.get(category, 0) + amount
    out = []
    for c in store.categories():
        if c.kind != "expense":
            continue
        s = spent.get(c.name, 0)
        out.append(CategoryStatus(
            category=c.name, limit=c.limit, spent=s,
            remaining=None if c.limit is None else c.limit - s,
            ratio=None if not c.limit else s / c.limit,
            level=_level(s, c.limit)))
    return out


def warnings(statuses: list[CategoryStatus]) -> list[CategoryStatus]:
    return [s for s in statuses if s.level in ("near", "over")]


def status_line(s: CategoryStatus) -> str:
    if s.limit is None:
        return f"{s.category}: {format_amount(s.spent)} spent (no limit)"
    left = (f"{format_amount(s.remaining)} left" if s.remaining >= 0
            else f"over by {format_amount(-s.remaining)}")
    flag = {"near": "  ⚠ near limit", "over": "  ⛔ over limit"}.get(s.level, "")
    return f"{s.category}: {format_amount(s.spent)} / {format_amount(s.limit)} ({left}){flag}"
