"""./fin save — commit data/ and push it to main (pull-request fallback)."""
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from fincore import guard

_DENIED = re.compile(r"\b403\b|permission|denied|not allowed|protected branch", re.IGNORECASE)
_STALE = re.compile(r"non-fast-forward|fetch first|rejected", re.IGNORECASE)


@dataclass
class SaveResult:
    status: Literal["pushed", "nothing", "fallback"]
    detail: str


def save(repo: Path, message: str, run: Callable = subprocess.run,
         visibility: Callable[[], str] = guard.current_visibility) -> SaveResult:
    if visibility() == "public":
        raise guard.GuardError("This repo is public — refusing to push financial data. Make it private first.")

    def git(*args):
        return run(["git", "-C", str(repo), *args], capture_output=True, text=True)

    git("add", "--", "data/")
    if git("diff", "--cached", "--quiet", "--", "data/").returncode == 0:
        return SaveResult("nothing", "No data changes to save.")
    c = git("commit", "-q", "-m", f"data: {message}", "--", "data/")
    if c.returncode != 0:
        raise RuntimeError(f"git commit failed: {c.stderr.strip()}")
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def fallback(reason: str) -> SaveResult:
        p = git("push", "-q", "-u", "origin", "HEAD")
        if p.returncode != 0:
            raise RuntimeError(f"Saved locally but couldn't push anywhere: {p.stderr.strip()}")
        return SaveResult("fallback", f"{reason} Pushed to {branch}; open a pull request into main and merge it.")

    if git("fetch", "-q", "origin", "main").returncode != 0:
        return fallback("Couldn't reach main on GitHub (it may not exist yet).")
    d = git("diff", "--name-only", "origin/main...HEAD")
    if d.returncode != 0:
        return fallback("Couldn't compare this branch with main.")
    if any(not f.startswith("data/") for f in d.stdout.split()):
        return fallback("This branch also has code changes, so the ledger can't go straight to main.")

    for attempt in range(2):
        p = git("push", "-q", "origin", "HEAD:main")
        if p.returncode == 0:
            return SaveResult("pushed", "Saved to main.")
        if _DENIED.search(p.stderr) and not _STALE.search(p.stderr):
            return fallback("Pushing to main isn't allowed from this session.")
        if attempt == 0 and _STALE.search(p.stderr):
            git("fetch", "-q", "origin", "main")
            r = git("rebase", "-q", "origin/main")
            if r.returncode != 0:
                git("rebase", "--abort")
                return fallback("main changed in a conflicting way.")
            continue
        break
    return fallback(f"Push to main failed ({p.stderr.strip().splitlines()[-1] if p.stderr.strip() else 'unknown'}).")


def sync_from_main(repo: Path, run: Callable = subprocess.run) -> list[str]:
    """Session start: bring in the latest ledger from main; flag ledger entries stuck on other branches.
    Returns messages for the owner (empty = all good)."""
    def git(*args):
        return run(["git", "-C", str(repo), *args], capture_output=True, text=True)

    if git("fetch", "-q", "origin").returncode != 0 or git("rev-parse", "-q", "--verify",
                                                           "origin/main").returncode != 0:
        return ["⚠ Couldn't get main from GitHub — the ledger here may be out of date."]
    msgs = []
    if git("merge-base", "--is-ancestor", "HEAD", "origin/main").returncode == 0:
        git("merge", "-q", "--ff-only", "origin/main")
    elif git("merge-base", "--is-ancestor", "origin/main", "HEAD").returncode != 0:
        msgs.append("⚠ This session's branch has diverged from main — the latest ledger entries may be "
                    "missing. Merge main before logging.")
    for ref in git("branch", "-r", "--no-merged", "origin/main", "--format=%(refname:short)").stdout.split():
        if ref in ("origin/HEAD", "origin/main", "origin"):
            continue
        files = git("diff", "--name-only", f"origin/main...{ref}").stdout.split()
        if files and all(f.startswith("data/") for f in files):
            msgs.append(f"⚠ Ledger entries on {ref.removeprefix('origin/')} aren't on main yet — "
                        "merge that pull request.")
    return msgs
