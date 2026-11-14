"""Pay periods: paydays on the 15th and 30th (last day of February)."""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta

days_per_period: float = 365.25 / 24


def _paydays(year: int, month: int) -> list[date]:
    last = calendar.monthrange(year, month)[1]
    return [date(year, month, 15), date(year, month, min(30, last))]


def _prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _start_on_or_before(d: date) -> date:
    candidates = [p for p in _paydays(d.year, d.month) if p <= d]
    if candidates:
        return candidates[-1]
    return _paydays(*_prev_month(d.year, d.month))[1]


def _next_payday_after(d: date) -> date:
    for p in _paydays(d.year, d.month):
        if p > d:
            return p
    return _paydays(*_next_month(d.year, d.month))[0]


@dataclass(frozen=True)
class Period:
    start: date
    end: date  # inclusive

    @property
    def label(self) -> str:
        s, e = self.start, self.end
        if s.month == e.month:
            return f"{s:%b} {s.day}–{e.day}"
        return f"{s:%b} {s.day}–{e:%b} {e.day}"

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end


def period_for(d: date) -> Period:
    start = _start_on_or_before(d)
    return Period(start, _next_payday_after(start) - timedelta(days=1))


def previous(p: Period) -> Period:
    return period_for(p.start - timedelta(days=1))


def next_period(p: Period) -> Period:
    return period_for(p.end + timedelta(days=1))
