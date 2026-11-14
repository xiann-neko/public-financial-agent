"""Mapping-driven import of bank / e-wallet CSV statements. Parsing only — never writes."""
import csv
import io
from datetime import datetime
from pathlib import Path

from fincore.dedupe import find_duplicates
from fincore.money import parse_amount
from fincore.store import REPO_ROOT, Store

IMPORTERS_DIR = REPO_ROOT / "importers"


def _money(raw: str, line: int) -> int:
    try:
        return parse_amount(raw.strip().lstrip("-").replace("(", "").replace(")", ""))
    except ValueError:
        raise ValueError(f"line {line}: can't read amount {raw!r}")


def _nonzero(raw: str) -> str:
    """Banks often write 0.00 for 'nothing'; treat it like an empty cell."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    return raw if digits.strip("0") else ""


def parse_statement(path: Path, mapping: dict, source: str) -> list[dict]:
    text = Path(path).read_text(encoding=mapping.get("encoding", "utf-8-sig"))
    skip = int(mapping.get("skip_rows", 0))
    lines = text.splitlines(keepends=True)
    reader = csv.DictReader(io.StringIO("".join(lines[skip:])))
    rows = []
    for r in reader:
        line = reader.line_num + skip
        if not any((v or "").strip() for v in r.values()):
            continue
        raw_date = (r.get(mapping["date_column"]) or "").strip()
        try:
            d = datetime.strptime(raw_date, mapping["date_format"]).date()
        except ValueError:
            raise ValueError(f"line {line}: can't read date {raw_date!r} (expected {mapping['date_format']})")
        if "amount_column" in mapping:
            raw = _nonzero((r.get(mapping["amount_column"]) or "").strip())
            if not raw:
                continue
            negative = raw.startswith("-") or raw.startswith("(")
            is_expense = negative if mapping.get("expense_is_negative", True) else not negative
            amount = _money(raw, line)
            kind = "expense" if is_expense else "income"
        else:
            debit = _nonzero((r.get(mapping["debit_column"]) or "").strip())
            credit = _nonzero((r.get(mapping["credit_column"]) or "").strip())
            if debit:
                kind, amount = "expense", _money(debit, line)
            elif credit:
                kind, amount = "income", _money(credit, line)
            else:
                continue
        note_col = mapping.get("note_column")
        rows.append({"date": d.isoformat(), "type": kind, "amount": amount,
                     "payee": (r.get(mapping["payee_column"]) or "").strip(),
                     "note": (r.get(note_col) or "").strip() if note_col else "",
                     "account": mapping["account"], "source": f"import:{source}"})
    return rows


def propose(store: Store, rows: list[dict]) -> list[dict]:
    existing = store.transactions()
    out = []
    for n, r in enumerate(rows, 1):
        d = datetime.strptime(r["date"], "%Y-%m-%d").date()
        dups = find_duplicates(existing, r["type"], r["amount"], d, r["payee"])
        out.append(dict(r, n=n, duplicates=[t.id for t in dups]))
    return out
