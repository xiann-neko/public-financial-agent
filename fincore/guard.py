"""Refuse to write real financial data into a public GitHub repo."""
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Callable, Literal, Optional
from urllib.error import HTTPError

from fincore.store import REPO_ROOT

Visibility = Literal["public", "private", "unknown"]
_GH = re.compile(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")


class GuardError(Exception):
    pass


def parse_github_repo(remote_url: str) -> Optional[str]:
    m = _GH.search(remote_url.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def _http_get_json(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "fin-cli"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


def repo_visibility(remote_url: str, fetch: Callable = _http_get_json) -> Visibility:
    repo = parse_github_repo(remote_url)
    if not repo:
        return "unknown"
    try:
        data = fetch(f"https://api.github.com/repos/{repo}")
    except HTTPError as e:
        return "private" if e.code == 404 else "unknown"
    except Exception:
        return "unknown"
    if isinstance(data, dict) and isinstance(data.get("private"), bool):
        return "private" if data["private"] else "public"
    return "unknown"


def origin_url(repo: Path = REPO_ROOT) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def is_protected(data_dir: Path) -> bool:
    """Only the repo's own data/ dir is guarded (not temp or example dirs)."""
    return Path(data_dir).resolve() == (REPO_ROOT / "data").resolve()


def current_visibility() -> Visibility:
    return repo_visibility(origin_url())


def ensure_writable(data_dir: Path) -> None:
    if os.environ.get("FIN_SKIP_GUARD") == "1" or not is_protected(data_dir):
        return
    vis = repo_visibility(origin_url())
    if vis == "public":
        raise GuardError("This repo is public — refusing to save financial data. Make it private first.")
    if vis == "unknown":
        print("warning: couldn't confirm the repo is private; saving anyway.", file=sys.stderr)


def visibility_warning(data_dir: Path) -> Optional[str]:
    if os.environ.get("FIN_SKIP_GUARD") == "1" or not is_protected(data_dir):
        return None
    vis = repo_visibility(origin_url())
    if vis == "public":
        return "⛔ This repo is PUBLIC — nothing will be saved until it is private."
    if vis == "unknown":
        return "⚠ Couldn't confirm the repo is private."
    return None
