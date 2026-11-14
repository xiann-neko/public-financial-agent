"""Shared test helpers: temp data dirs, no network guard."""
import os
import tempfile
from pathlib import Path

from fincore.store import Store, init_data


class TempData:
    """Context manager: an initialised data dir with FIN_DATA_DIR set."""

    def __init__(self, init: bool = True):
        self.init = init

    def __enter__(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "data"
        if self.init:
            init_data(self.path, examples=False)
        else:
            self.path.mkdir()
        self._old = {k: os.environ.get(k) for k in ("FIN_DATA_DIR", "FIN_SKIP_GUARD")}
        os.environ["FIN_DATA_DIR"] = str(self.path)
        os.environ["FIN_SKIP_GUARD"] = "1"
        return self.path

    def __exit__(self, *exc):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()


def store() -> Store:
    return Store.open()
