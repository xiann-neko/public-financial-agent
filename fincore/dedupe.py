"""Spot the same purchase recorded twice (e.g. screenshot, then statement import)."""
import re
from datetime import date
from difflib import SequenceMatcher

from fincore.model import Transaction

MAX_DAYS_APART = 2
MIN_SIMILARITY = 0.6


def normalize_payee(s: str) -> str:
    tokens = re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split()
    return " ".join(tok for tok in tokens if not tok.isdigit())


def _similar(a: str, b: str) -> bool:
    a, b = normalize_payee(a), normalize_payee(b)
    if not a or not b:
        return True
    if a.split()[0] in b or b.split()[0] in a:
        return True
    return SequenceMatcher(None, a, b).ratio() >= MIN_SIMILARITY


def find_duplicates(existing: list[Transaction], type: str, amount: int, d: date, payee: str) -> list[Transaction]:
    return [t for t in existing
            if t.type == type and t.amount == amount and abs((t.date - d).days) <= MAX_DAYS_APART
            and _similar(t.payee, payee)]
