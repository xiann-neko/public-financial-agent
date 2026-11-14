#!/usr/bin/env python3
"""Copy the agent's code (never data/) into a checkout of the public sharing repo.

Usage: python3 scripts/publish.py DEST [--allow TERM ...]
It only copies files; review, commit and push in DEST yourself.
Before copying, it checks the files for names, payees, notes and amounts from
your real data/ and refuses if any appear (--allow TERM for a false positive).
"""
import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


class PublishError(Exception):
    pass


PRIVATE_PREFIXES = ("data/", "docs/superpowers/")  # ledger; design docs name the owner and repo


def _is_private(path: str) -> bool:
    return path == "data" or path.startswith(PRIVATE_PREFIXES)


# ---- leak guard: nothing from the real ledger may appear in published files ----
TEXT_KEYS = {"name", "card", "item", "payee", "note", "account", "to_account", "goal", "label", "title",
             "category", "counterparty"}
AMOUNT_HINTS = ("amount", "balance", "limit", "payment", "price", "total", "monthly", "opening", "planned",
                "target")
# Words that are fine anywhere: default categories, bookkeeping vocabulary, everyday words.
COMMON = set("""
groceries dining food delivery transport bills utilities rent housing health family support padala
shopping planned impulse wants entertainment subscriptions other salary side income interest fees
emergency fund savings saving cash bank card credit loan loans payment payments transfer opening manual
lunch dinner breakfast snack snacks coffee load owed lent repaid forgiven paid bill monthly month
spending spent gift gifts trip example phone before tracking balance conversion store merchant
internet water electricity payroll care
january february march april may june july august september october november december
""".split())
_WORD = re.compile(r"[A-Za-z][A-Za-z']+")


def _values(obj, key=None):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _values(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _values(v, key)
    else:
        yield key, obj


def _records(folder: Path):
    """(key, value) pairs from every JSON/CSV file in a data folder."""
    for f in sorted(folder.glob("*.json")):
        try:
            yield from _values(json.loads(f.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError):
            continue
    for f in sorted(folder.glob("*.csv")):
        try:
            with open(f, encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    yield from ((k, v) for k, v in row.items() if k)
        except (OSError, csv.Error):
            continue


def _is_amount_key(key) -> bool:
    return isinstance(key, str) and any(h in key for h in AMOUNT_HINTS)


def personal_terms(data_dir: Path, example_dir: Path) -> set[str]:
    """Names, payees, notes and distinctive amounts from the real ledger that aren't in the examples."""
    example_words = set()
    for _, v in _records(Path(example_dir)) if Path(example_dir).exists() else []:
        if isinstance(v, str):
            example_words.add(v.lower())
            example_words.update(w.lower() for w in _WORD.findall(v))
    terms = set()
    for key, v in _records(Path(data_dir)):
        if key in TEXT_KEYS and isinstance(v, str) and v.strip():
            phrase = v.strip()
            words = [w.lower() for w in _WORD.findall(phrase)]
            everyday = words and all(w in COMMON or w in example_words for w in words)
            long_enough = len(phrase) >= 4 or (len(phrase) == 3 and phrase.isupper())
            if long_enough and phrase.lower() not in example_words and phrase.lower() not in COMMON and not everyday:
                terms.add(phrase)
            for w in _WORD.findall(phrase):
                lw = w.lower()
                if (len(w) >= 4 or (len(w) == 3 and w.isupper())) and lw not in COMMON and lw not in example_words:
                    terms.add(w)
        elif _is_amount_key(key):
            try:
                cents = int(v)
            except (TypeError, ValueError):
                continue
            if cents >= 100000 and cents % 10000:  # skip small amounts and whole ₱100s (too common to flag)
                pesos = cents / 100
                terms.update({str(cents), f"{pesos:,.2f}", f"{pesos:.2f}"})
    return {t for t in terms if t.lower() not in COMMON}


def _pattern(term: str) -> re.Pattern:
    if term[0].isdigit():
        return re.compile(r"(?<![\d.,])" + re.escape(term) + r"(?![\d])")
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.IGNORECASE)


def find_leaks(src: Path, files: list[str], terms: set[str]) -> list[str]:
    pats = [(t, _pattern(t)) for t in sorted(terms, key=len, reverse=True)]
    leaks = []
    for rel in files:
        try:
            text = (src / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binary files
        for n, line in enumerate(text.splitlines(), 1):
            for t, p in pats:
                if p.search(line):
                    leaks.append(f"{rel}:{n} → {t}")
                    break
    return leaks


def publish(src: Path, dest: Path, allow: set[str] | None = None) -> list[str]:
    src, dest = Path(src), Path(dest)
    real = [p for p in (dest / "data").rglob("*") if p.is_file() and p.name != ".gitkeep"] \
        if (dest / "data").exists() else []
    if real:
        raise PublishError(f"{dest}/data contains real files ({real[0].name}…) — refusing to publish there")
    tracked = subprocess.run(["git", "-C", str(src), "ls-files", "-z"], capture_output=True, text=True,
                             check=True).stdout.split("\0")
    files = [rel for rel in filter(None, tracked) if not _is_private(rel)]
    if (src / "data").is_dir():
        allowed = {a.lower() for a in (allow or set())}
        allowed |= {w.lower() for a in (allow or set()) for w in _WORD.findall(a)}  # allowing "Hobby fund" allows "Hobby"
        terms = {t for t in personal_terms(src / "data", src / "data.example") if t.lower() not in allowed}
        leaks = find_leaks(src, files, terms)
        if leaks:
            raise PublishError("Personal data from data/ found in files to publish — nothing was copied:\n  "
                               + "\n  ".join(leaks)
                               + "\nRemove it, or pass --allow TERM if it's a false positive.")
    copied = []
    for rel in files:
        if _is_private(rel):
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, target)
        copied.append(rel)
    if any(_is_private(c) for c in copied):  # belt and braces
        raise PublishError("internal error: a data/ file was about to be published")
    return copied


def main(argv: list[str]) -> int:
    allow, rest = set(), []
    it = iter(argv)
    for a in it:
        if a == "--allow":
            allow.add(next(it, ""))
        else:
            rest.append(a)
    if len(rest) != 1:
        print(__doc__)
        return 1
    try:
        copied = publish(Path(__file__).resolve().parent.parent, Path(rest[0]), allow)
    except PublishError as e:
        print(e, file=sys.stderr)
        return 2
    print(f"Copied {len(copied)} files to {rest[0]} (data/ excluded, no personal data found). "
          "Review, then commit and push there.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
