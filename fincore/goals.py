"""Savings goals: progress, savings rate, emergency-fund target, purchase delay."""
import math
from datetime import date
from typing import Optional

from fincore.budget import expense_events
from fincore.model import Goal, Transaction
from fincore.periods import Period, days_per_period, period_for, previous
from fincore.store import Store

RATE_WINDOW = 6  # pay periods (~3 months)


def _signed(t: Transaction, goal: Goal) -> int:
    if t.type != "transfer":
        return 0
    if t.goal == goal.name:
        return t.amount
    if t.goal == "-" + goal.name:
        return -t.amount
    return 0


def progress(store: Store, goal: Goal) -> int:
    return sum(_signed(t, goal) for t in store.transactions())


def completed_periods(today: date, n: int) -> list[Period]:
    """The n pay periods before today's, newest first."""
    out, p = [], period_for(today)
    for _ in range(n):
        p = previous(p)
        out.append(p)
    return out


def savings_rate(store: Store, goal: Goal, today: date) -> int:
    """Centavos saved per pay period: planned until 6 periods of real history, then the 6-period average."""
    window = completed_periods(today, RATE_WINDOW)
    txns = [t for t in store.transactions() if _signed(t, goal) and t.source != "opening"]
    first_contribution = min((t.date for t in txns if _signed(t, goal) > 0), default=None)
    if first_contribution is None or first_contribution > window[-1].end:
        return goal.planned_per_period
    net = sum(_signed(t, goal) for t in txns if window[-1].start <= t.date <= window[0].end)
    return net // RATE_WINDOW


def essential_monthly(store: Store, today: date) -> Optional[int]:
    """Average monthly essential spending over up to 6 completed periods; None until 2 periods have data."""
    essentials = {c.name for c in store.categories() if c.kind == "expense" and c.essential}
    window = completed_periods(today, RATE_WINDOW)
    start, end = window[-1].start, window[0].end
    events = expense_events(store, start, end)
    dates = [t.date for t in store.transactions() if start <= t.date <= end] + [d for d, _, _ in events]
    with_data = [p for p in window if any(p.contains(d) for d in dates)]
    if len(with_data) < 2:
        return None
    span = [p for p in window if p.start >= with_data[-1].start]
    total = sum(a for _, c, a in events if c in essentials)
    return total * 2 // len(span)


def is_emergency_fund(store: Store, goal: Goal) -> bool:
    return goal.priority == min(g.priority for g in store.goals())


def target(store: Store, goal: Goal, today: date) -> Optional[int]:
    if goal.target is not None:
        return goal.target
    if not is_emergency_fund(store, goal):
        return None
    monthly = essential_monthly(store, today)
    return None if monthly is None else monthly * goal.target_months


def delay_days(amount: int, rate: int) -> Optional[int]:
    if rate <= 0:
        return None
    return math.ceil(amount * days_per_period / rate)
