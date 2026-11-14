"""Regression tests for findings from the final branch review."""
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from fincore import clock
from fincore.cli import run
from fincore.gitsync import save, sync_from_main
from fincore.importer import parse_statement
from fincore.store import Store
from tests.helpers import TempData, store
from tests.test_gitsync import configure, git

PRIVATE = lambda: "private"  # noqa: E731


class SaveFailsClosedTest(unittest.TestCase):
    """Critical 1: no origin/main must never mean 'push the whole branch to main'."""

    def test_no_main_on_remote_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            origin = root / "o.git"
            git(root, "init", "-q", "--bare", "-b", "main", str(origin))
            work = root / "w"
            git(root, "clone", "-q", str(origin), str(work))
            configure(work)
            git(work, "checkout", "-q", "-b", "claude/x")
            (work / "code.py").write_text("x\n")
            (work / "data").mkdir()
            (work / "data" / "transactions.csv").write_text("id\n")
            git(work, "add", ".")
            git(work, "commit", "-qm", "code")
            (work / "data" / "transactions.csv").write_text("id\n1\n")
            r = save(work, "x", visibility=PRIVATE)
            self.assertEqual(r.status, "fallback")
            heads = subprocess.run(["git", "ls-remote", "--heads", str(origin)], capture_output=True,
                                   text=True).stdout
            self.assertNotIn("refs/heads/main", heads)


class SyncFromMainTest(unittest.TestCase):
    """Important 7: session start brings in the latest ledger and flags unmerged data branches."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = Path(self.tmp.name)
        self.origin = root / "o.git"
        git(root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        seed = root / "seed"
        git(root, "clone", "-q", str(self.origin), str(seed))
        configure(seed)
        git(seed, "checkout", "-q", "-b", "main")
        (seed / "data").mkdir()
        (seed / "data" / "transactions.csv").write_text("id\n")
        git(seed, "add", ".")
        git(seed, "commit", "-qm", "seed")
        git(seed, "push", "-q", "origin", "main")
        self.work = root / "w"
        git(root, "clone", "-q", "-b", "main", str(self.origin), str(self.work))
        configure(self.work)
        git(self.work, "checkout", "-q", "-b", "claude/session")
        # newer ledger entry lands on main after this session's branch was cut
        (seed / "data" / "transactions.csv").write_text("id\nnew\n")
        git(seed, "commit", "-qam", "data: new")
        git(seed, "push", "-q", "origin", "main")
        self.seed = seed

    def tearDown(self):
        self.tmp.cleanup()

    def test_fast_forwards_to_main(self):
        msgs = sync_from_main(self.work)
        self.assertEqual((self.work / "data" / "transactions.csv").read_text(), "id\nnew\n")
        self.assertEqual(msgs, [])

    def test_warns_about_unmerged_data_branch(self):
        git(self.seed, "checkout", "-q", "-b", "claude/old-session")
        (self.seed / "data" / "transactions.csv").write_text("id\nnew\nfallback\n")
        git(self.seed, "commit", "-qam", "data: fallback")
        git(self.seed, "push", "-q", "origin", "claude/old-session")
        msgs = sync_from_main(self.work)
        self.assertTrue(any("claude/old-session" in m for m in msgs), msgs)

    def test_no_remote_main_is_a_warning_not_a_crash(self):
        with tempfile.TemporaryDirectory() as d:
            git(Path(d), "init", "-q")
            msgs = sync_from_main(Path(d))
        self.assertTrue(msgs)


class ClockTest(unittest.TestCase):
    """Important 2: 'today' is Philippine time, not the container's UTC."""

    def test_early_morning_on_payday_is_payday(self):
        with mock.patch("fincore.clock._utcnow", return_value=datetime(2026, 11, 14, 23, 30, tzinfo=timezone.utc)):
            self.assertEqual(clock.now(), datetime(2026, 11, 15, 7, 30))
            self.assertEqual(clock.today().isoformat(), "2026-11-15")

    def test_cli_uses_ph_time(self):
        with TempData(), mock.patch("fincore.clock._utcnow",
                                    return_value=datetime(2026, 11, 14, 23, 30, tzinfo=timezone.utc)):
            run(["add", "expense", "100", "--category", "Groceries", "--account", "Cash"])
            self.assertEqual(store().transactions()[0].date.isoformat(), "2026-11-15")


class CliRobustnessTest(unittest.TestCase):
    def setUp(self):
        self.ctx = TempData()
        self.dir = self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_goal_tag_is_canonicalised(self):  # Important 3
        run(["add", "transfer", "500", "--account", "Cash", "--to", "Savings", "--goal", "emergency fund"])
        run(["add", "transfer", "100", "--account", "Savings", "--to", "Cash", "--goal=-EMERGENCY FUND"])
        goals = [t.goal for t in store().transactions()]
        self.assertEqual(goals, ["Emergency fund", "-Emergency fund"])
        self.assertEqual(json.loads(run(["goal", "list", "--json"])[1])[0]["progress"], 40000)

    def test_duplicate_ids_are_repaired_not_overwritten(self):  # Important 4
        run(["--today", "2026-11-14", "add", "expense", "100", "--category", "Groceries", "--account", "Cash"])
        p = self.dir / "transactions.csv"
        lines = p.read_text().splitlines()
        lines.append(lines[1].replace(",10000,", ",20000,").replace("Groceries", "Transport"))
        p.write_text("\n".join(lines) + "\n")
        ids = [t.id for t in Store.open(self.dir).transactions()]
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(run(["edit", "20261114-001", "--amount", "999"])[0], 0)
        amounts = sorted(t.amount for t in store().transactions())
        self.assertEqual(amounts, [20000, 99900])

    def test_missing_import_file_is_a_message(self):  # Important 6
        code, _, err = run(["import", "parse", str(self.dir / "nope.csv"), "--source", "generic-example"])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)

    def batch(self, obj):
        f = self.dir / "b.json"
        f.write_text(json.dumps(obj))
        return run(["add-batch", str(f)])

    def test_add_batch_bad_shapes(self):  # Important 6
        self.assertEqual(self.batch({"date": "2026-11-14"})[0], 1)
        self.assertEqual(self.batch(["x"])[0], 1)
        row = {"date": 20261114, "type": "expense", "amount": 100, "category": "Groceries", "account": "Cash"}
        self.assertEqual(self.batch([row])[0], 1)

    def test_add_batch_rejects_bool_amount(self):  # Minor 1 regraded
        row = {"date": "2026-11-14", "type": "expense", "amount": True, "category": "Groceries", "account": "Cash"}
        self.assertEqual(self.batch([row])[0], 1)
        self.assertEqual(store().transactions(), [])


class ImportZeroTest(unittest.TestCase):
    def test_zero_debit_uses_credit(self):  # Important 5
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "s.csv"
            f.write_text("Date,Description,Debit,Credit\n11/14/2026,Fee,0.00,\n11/15/2026,Pay,0.00,500.00\n")
            rows = parse_statement(f, {"date_column": "Date", "date_format": "%m/%d/%Y", "payee_column": "Description",
                                       "debit_column": "Debit", "credit_column": "Credit", "account": "Cash"},
                                   source="x")
        self.assertEqual([(r["type"], r["amount"]) for r in rows], [("income", 50000)])


class PublishPrivacyTest(unittest.TestCase):
    def test_design_docs_not_published(self):  # Minor 9 regraded
        import importlib.util
        root = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location("publish", root / "scripts" / "publish.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertTrue(m._is_private("docs/superpowers/specs/x.md"))


if __name__ == "__main__":
    unittest.main()
