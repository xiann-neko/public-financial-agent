"""Load and save everything under the data directory (atomic writes)."""
import csv
import dataclasses
import io
import json
import os
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fincore.model import Account, Category, Goal, Installment, Transaction, WaitItem

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_DIR = REPO_ROOT / "data.example"
CONFIG_FILES = ("budget.json", "accounts.json", "goals.json")
REQUIRED_FILES = CONFIG_FILES + ("transactions.csv", "waitlist.csv", "meta.json")

TXN_FIELDS = [f.name for f in dataclasses.fields(Transaction)]
WAIT_FIELDS = [f.name for f in dataclasses.fields(WaitItem)]


class NoDataError(Exception):
    pass


def default_data_dir() -> Path:
    env = os.environ.get("FIN_DATA_DIR")
    return Path(env) if env else REPO_ROOT / "data"


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _csv_text(fields: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def _iso(v) -> str:
    return v.isoformat() if isinstance(v, (date, datetime)) else ("" if v is None else str(v))


def _dt(s: str) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


class Store:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)

    @classmethod
    def open(cls, data_dir: Optional[Path] = None) -> "Store":
        d = Path(data_dir) if data_dir else default_data_dir()
        if not d.is_dir() or not all((d / f).exists() for f in REQUIRED_FILES):
            raise NoDataError("No data yet — run ./fin init")
        return cls(d)

    # ---- reading -------------------------------------------------------
    def _rows(self, name: str) -> list[dict]:
        with open(self.dir / name, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def _json(self, name: str):
        return json.loads((self.dir / name).read_text(encoding="utf-8-sig"))

    def transactions(self) -> list[Transaction]:
        out = []
        for r in self._rows("transactions.csv"):
            out.append(Transaction(
                id=r["id"], date=date.fromisoformat(r["date"]), type=r["type"], amount=int(r["amount"]),
                category=r["category"], account=r["account"], to_account=r.get("to_account", ""),
                payee=r.get("payee", ""), note=r.get("note", ""), goal=r.get("goal", ""),
                source=r.get("source", "") or "manual", created_at=_dt(r.get("created_at", ""))))
        return _unique_ids(out)

    def waitlist(self) -> list[WaitItem]:
        return [WaitItem(id=r["id"], item=r["item"], price=int(r["price"]), category=r["category"],
                         added_at=_dt(r["added_at"]), due_at=_dt(r["due_at"]), outcome=r["outcome"],
                         resolved_at=_dt(r.get("resolved_at", "")), txn_id=r.get("txn_id", ""))
                for r in self._rows("waitlist.csv")]

    def categories(self) -> list[Category]:
        known = {f.name for f in dataclasses.fields(Category)}
        return [Category(**{k: v for k, v in c.items() if k in known}) for c in self._json("budget.json")["categories"]]

    def accounts(self) -> list[Account]:
        known = {f.name for f in dataclasses.fields(Account)}
        return [Account(**{k: v for k, v in a.items() if k in known}) for a in self._json("accounts.json")["accounts"]]

    def goals(self) -> list[Goal]:
        return [Goal(**g) for g in self._json("goals.json")["goals"]]

    def meta(self) -> dict:
        return self._json("meta.json")

    def installments(self) -> list[Installment]:
        if not (self.dir / "installments.json").exists():
            return []
        known = {f.name for f in dataclasses.fields(Installment)}
        return [Installment(**{k: v for k, v in dict(i, first_billing=date.fromisoformat(i["first_billing"])).items()
                               if k in known})
                for i in self._json("installments.json")["installments"]]

    def save_installments(self, items: list[Installment]) -> None:
        rows = [dict(dataclasses.asdict(i), first_billing=i.first_billing.isoformat()) for i in items]
        self._save_json("installments.json", {"installments": rows})

    def new_installment_id(self) -> str:
        used = [int(i.id[1:]) for i in self.installments() if i.id[1:].isdigit()]
        return f"i{max(used, default=0) + 1:03d}"

    # ---- writing -------------------------------------------------------
    def save_transactions(self, txns: list[Transaction]) -> None:
        rows = [{k: _iso(v) for k, v in dataclasses.asdict(t).items()} for t in txns]
        _atomic_write(self.dir / "transactions.csv", _csv_text(TXN_FIELDS, rows))

    def save_waitlist(self, items: list[WaitItem]) -> None:
        rows = [{k: _iso(v) for k, v in dataclasses.asdict(w).items()} for w in items]
        _atomic_write(self.dir / "waitlist.csv", _csv_text(WAIT_FIELDS, rows))

    def _save_json(self, name: str, obj) -> None:
        _atomic_write(self.dir / name, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")

    def save_budget(self, cats: list[Category]) -> None:
        self._save_json("budget.json", {"categories": [dataclasses.asdict(c) for c in cats]})

    def save_accounts(self, accts: list[Account]) -> None:
        self._save_json("accounts.json", {"accounts": [dataclasses.asdict(a) for a in accts]})

    def save_goals(self, goals: list[Goal]) -> None:
        self._save_json("goals.json", {"goals": [dataclasses.asdict(g) for g in goals]})

    def save_meta(self, meta: dict) -> None:
        self._save_json("meta.json", meta)

    # ---- ids -----------------------------------------------------------
    def new_txn_id(self, d: date) -> str:
        return next_txn_id(self.transactions(), d)

    def new_wait_id(self) -> str:
        used = [int(w.id[1:]) for w in self.waitlist() if w.id[1:].isdigit()]
        return f"w{max(used, default=0) + 1:03d}"


def _unique_ids(txns: list[Transaction]) -> list[Transaction]:
    """Two sessions merged via pull requests can both create e.g. 20261114-001.
    Later rows with a repeated id get the next free id, so edit/delete hit one row only."""
    seen: set[str] = set()
    for t in txns:
        if t.id in seen:
            t.id = next_txn_id(txns, t.date)
        seen.add(t.id)
    return txns


def next_txn_id(txns: list[Transaction], d: date) -> str:
    prefix = d.strftime("%Y%m%d") + "-"
    used = [int(t.id[len(prefix):]) for t in txns if t.id.startswith(prefix) and t.id[len(prefix):].isdigit()]
    return f"{prefix}{max(used, default=0) + 1:03d}"


def init_data(data_dir: Path, examples: bool = False) -> None:
    """Create a data dir from data.example/. Example transactions only if examples=True."""
    d = Path(data_dir)
    if d.exists() and any(p for p in d.iterdir() if p.name != ".gitkeep"):
        raise FileExistsError(f"{d} already has data — not overwriting it")
    d.mkdir(parents=True, exist_ok=True)
    for name in CONFIG_FILES:
        shutil.copy(EXAMPLE_DIR / name, d / name)
    if examples:
        for name in ("transactions.csv", "waitlist.csv", "installments.json"):
            shutil.copy(EXAMPLE_DIR / name, d / name)
    else:
        _atomic_write(d / "transactions.csv", _csv_text(TXN_FIELDS, []))
        _atomic_write(d / "waitlist.csv", _csv_text(WAIT_FIELDS, []))
        _atomic_write(d / "installments.json", json.dumps({"installments": []}, indent=2) + "\n")
        # A real ledger starts with plain accounts only; example cards/loans are for demos.
        accts = json.loads((d / "accounts.json").read_text(encoding="utf-8"))
        accts["accounts"] = [a for a in accts["accounts"] if a.get("kind", "cash") == "cash"]
        _atomic_write(d / "accounts.json", json.dumps(accts, indent=2, ensure_ascii=False) + "\n")
    _atomic_write(d / "meta.json", json.dumps({"last_review": None}, indent=2) + "\n")
