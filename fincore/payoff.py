"""Debt payoff simulation (monthly), with avalanche extra payments."""
from dataclasses import dataclass, field
from typing import Optional

MAX_MONTHS = 600


@dataclass
class SimDebt:
    name: str
    balance: int  # centavos owed now
    rate: float  # interest per month as a fraction (0.03 = 3%)
    payment: Optional[int]  # planned monthly payment; None = not set
    end_months: Optional[int]  # scheduled payoff (loans with an end month, installments)


@dataclass
class DebtResult:
    status: str  # "ok" | "never" | "no-payment"
    months: Optional[int] = None
    interest: Optional[int] = 0  # None when never paid off (it would grow without bound)


@dataclass
class SimResult:
    debts: dict = field(default_factory=dict)
    total_interest: int = 0
    debt_free_months: Optional[int] = None
    first_target: Optional[str] = None


def simulate(debts: list[SimDebt], extra: int) -> SimResult:
    res = SimResult()
    sim, scheduled = [], []
    for d in debts:
        if d.balance <= 0:
            res.debts[d.name] = DebtResult("ok", 0)
        elif d.end_months is not None:
            scheduled.append(d)
            res.debts[d.name] = DebtResult("ok", max(d.end_months, 0))
        elif not d.payment:
            res.debts[d.name] = DebtResult("no-payment")
        else:
            sim.append(d)
    bal = {d.name: d.balance for d in sim}
    interest = {d.name: 0 for d in sim}
    done: dict[str, int] = {}
    freed = 0
    if extra > 0 and sim:
        res.first_target = sorted(sim, key=lambda d: (-d.rate, d.balance))[0].name
    for m in range(1, MAX_MONTHS + 1):
        alive = [d for d in sim if d.name not in done]
        if not alive:
            break
        for d in alive:
            i = round(bal[d.name] * d.rate)
            bal[d.name] += i
            interest[d.name] += i
        pool = extra + (freed if extra > 0 else 0)  # rollover is part of the extra-payment plan only
        for d in alive:
            pay = min(d.payment, bal[d.name])
            bal[d.name] -= pay
            pool += d.payment - pay
        for d in sorted(alive, key=lambda d: (-d.rate, bal[d.name])):
            x = min(pool, bal[d.name])
            bal[d.name] -= x
            pool -= x
        for d in alive:
            if bal[d.name] <= 0:
                done[d.name] = m
                freed += d.payment
        freed += sum(d.payment or 0 for d in scheduled if d.end_months == m)
    for d in sim:
        res.debts[d.name] = (DebtResult("ok", done[d.name], interest[d.name]) if d.name in done
                             else DebtResult("never", None, None))
    res.total_interest = sum(r.interest or 0 for r in res.debts.values())
    if all(r.status == "ok" for r in res.debts.values()):
        res.debt_free_months = max((r.months for r in res.debts.values()), default=0)
    return res
