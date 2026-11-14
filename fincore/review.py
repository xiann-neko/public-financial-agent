"""Weekly review and the short summary shown when a session starts."""
from datetime import date, datetime, timedelta

from fincore import goals as G
from fincore import guard
from fincore.budget import expense_events, period_status, warnings
from fincore.money import format_amount
from fincore.periods import period_for
from fincore.store import Store
from fincore.waitlist import due_items, saved_by_waiting


def _impulse_names(store: Store) -> set[str]:
    return {c.name for c in store.categories() if c.impulse}


def weekly_review(store: Store, today: date) -> dict:
    start = today - timedelta(days=6)
    prev_start, prev_end = start - timedelta(days=7), start - timedelta(days=1)
    week = [t for t in store.transactions() if start <= t.date <= today]
    impulse = _impulse_names(store)
    events = expense_events(store, start, today)
    by_cat: dict[str, int] = {}
    for _, category, amount in events:
        by_cat[category] = by_cat.get(category, 0) + amount
    p = period_for(today)
    return {
        "week_start": start.isoformat(), "week_end": today.isoformat(),
        "spend_by_category": [{"category": c, "amount": a}
                              for c, a in sorted(by_cat.items(), key=lambda kv: -kv[1])],
        "total_spent": sum(by_cat.values()),
        "total_income": sum(t.amount for t in week if t.type == "income"),
        "impulse_this_week": sum(a for _, c, a in events if c in impulse),
        "impulse_last_week": sum(a for _, c, a in expense_events(store, prev_start, prev_end) if c in impulse),
        "period_label": p.label,
        "warnings": [w.__dict__ for w in warnings(period_status(store, p))],
        "goals": [{"name": g.name, "progress": G.progress(store, g), "target": G.target(store, g, today)}
                  for g in sorted(store.goals(), key=lambda g: g.priority)],
        "saved_by_waiting": saved_by_waiting(store),
        **_debt_week(store, today, events),
    }


def _debt_week(store: Store, today: date, events) -> dict:
    from fincore.debts import INTEREST_CATEGORY, debt_summary
    now, before = debt_summary(store, today), debt_summary(store, today - timedelta(days=7))
    return {"debt_total": now["total_owed"], "debt_change_week": now["total_owed"] - before["total_owed"],
            "interest_this_week": sum(a for _, c, a in events if c == INTEREST_CATEGORY),
            "owed_to_you": now["owed_to_you"], "has_debts": bool(now["debts"])}


def format_review(r: dict) -> str:
    lines = [f"Week {r['week_start']} → {r['week_end']}: spent {format_amount(r['total_spent'])}, "
             f"income {format_amount(r['total_income'])}"]
    for row in r["spend_by_category"]:
        lines.append(f"  {row['category']}: {format_amount(row['amount'])}")
    lines.append(f"Impulse: {format_amount(r['impulse_this_week'])} this week vs "
                 f"{format_amount(r['impulse_last_week'])} the week before")
    for w in r["warnings"]:
        lines.append(f"Pay period {r['period_label']}: {w['category']} is {w['level']} its limit")
    for g in r["goals"]:
        tgt = f" of {format_amount(g['target'])}" if g["target"] else ""
        lines.append(f"{g['name']}: {format_amount(g['progress'])}{tgt}")
    lines.append(f"Saved by waiting (total): {format_amount(r['saved_by_waiting'])}")
    if r.get("has_debts"):
        ch = r["debt_change_week"]
        trend = "no change" if ch == 0 else (f"down {format_amount(-ch)}" if ch < 0 else f"up {format_amount(ch)}")
        lines.append(f"Debt: {format_amount(r['debt_total'])} ({trend} this week); "
                     f"interest & fees this week {format_amount(r['interest_this_week'])}")
    if r.get("owed_to_you"):
        lines.append(f"Owed to you: {format_amount(r['owed_to_you'])}")
    return "\n".join(lines)


def startup_summary(store: Store, now: datetime) -> list[str]:
    lines = []
    warn = guard.visibility_warning(store.dir)
    if warn:
        lines.append(warn)
    for w in due_items(store, now):
        lines.append(f"Cooling-off done: {w.item} ({format_amount(w.price)}, {w.id}) — buy or drop?")
    p = period_for(now.date())
    for w in warnings(period_status(store, p)):
        lines.append(f"{w.category} is {w.level} its limit for {p.label}")
    lines += debt_reminders(store, now.date())
    last = store.meta().get("last_review")
    if not last or (now.date() - date.fromisoformat(last)).days >= 7:
        lines.append("Weekly review due — say \"weekly review\".")
    return lines


DUE_SOON_DAYS = 5
OVERDUE_DAYS = 10  # flag a missed due date for this long; older ones predate tracking or are stale


def _paid_between(store: Store, name: str, after: date, upto: date) -> bool:
    return any(t.type == "transfer" and t.to_account == name and after < t.date <= upto
               for t in store.transactions())


def debt_reminders(store: Store, today: date) -> list[str]:
    from fincore.debts import next_due, owed, previous_due
    out = []
    for a in store.accounts():
        if a.is_debt and a.due_day and owed(store, a, today) > 0:
            nd, pd = next_due(a, today), previous_due(a, today)
            days = (nd - today).days
            if days <= DUE_SOON_DAYS and not _paid_between(store, a.name, pd, today):
                if days == 0:
                    out.append(f"{a.name} due today ({nd:%b} {nd.day})")
                else:
                    out.append(f"{a.name} due {nd:%b} {nd.day} (in {days} day{'s' if days != 1 else ''})")
            elif (pd and (today - pd).days <= OVERDUE_DAYS
                  and not (a.tracked_since and pd < date.fromisoformat(a.tracked_since))
                  and not _paid_between(store, a.name, previous_due(a, pd), today)):
                out.append(f"{a.name} is overdue (was due {pd:%b} {pd.day}) — no payment logged")
        elif a.kind == "receivable" and a.due_date:
            due = date.fromisoformat(a.due_date)
            left = owed(store, a, today)
            if due < today and left > 0:
                out.append(f"{a.name.removeprefix('Owed by ')} owes you {format_amount(left)} "
                           f"(was due {due:%b} {due.day})")
    return out
