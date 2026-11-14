import json
import unittest

from fincore.budget import period_status
from fincore.periods import period_for
from fincore.cli import run
from tests.helpers import TempData, store
from datetime import date


def ok(*args, today="2026-11-20"):
    code, out, err = run(["--today", today, *args])
    assert code == 0, err
    return out


def owed_list():
    return {r["name"]: r for r in json.loads(ok("owed", "list", "--json"))}


class OwedCliTest(unittest.TestCase):
    def setUp(self):
        self.ctx = TempData()
        self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_lend_repay(self):
        ok("owed", "lend", "Juan", "500", "--from", "Cash", "--due", "2026-12-01")
        a = next(a for a in store().accounts() if a.name == "Owed by Juan")
        self.assertEqual((a.kind, a.due_date), ("receivable", "2026-12-01"))
        ok("owed", "lend", "juan", "300", "--from", "GCash")  # same person, any capitalisation
        ok("owed", "repay", "Juan", "200", "--to", "Cash")
        self.assertEqual(owed_list()["Juan"]["owed"], 60000)
        self.assertEqual(owed_list()["Juan"]["due_date"], "2026-12-01")
        self.assertTrue(all(s.spent == 0 for s in period_status(store(), period_for(date(2026, 11, 20)))))

    def test_repay_more_than_owed_rejected(self):
        ok("owed", "lend", "Juan", "500", "--from", "Cash")
        self.assertEqual(run(["owed", "repay", "Juan", "600", "--to", "Cash"])[0], 1)
        self.assertEqual(run(["owed", "repay", "Maria", "1", "--to", "Cash"])[0], 1)

    def test_forgive_becomes_expense(self):
        ok("owed", "lend", "Juan", "500", "--from", "Cash")
        ok("owed", "forgive", "Juan", "--category", "Family support (padala)")
        self.assertEqual(owed_list()["Juan"]["owed"], 0)
        st = next(s for s in period_status(store(), period_for(date(2026, 11, 20)))
                  if s.category == "Family support (padala)")
        self.assertEqual(st.spent, 50000)

    def test_forgive_partial_default_other(self):
        ok("owed", "lend", "Juan", "500", "--from", "Cash")
        ok("owed", "forgive", "Juan", "100")
        self.assertEqual(owed_list()["Juan"]["owed"], 40000)
        self.assertEqual(store().transactions()[-1].category, "Other")

    def test_list_text_and_settled_hidden(self):
        ok("owed", "lend", "Juan", "500", "--from", "Cash")
        ok("owed", "lend", "Ana", "100", "--from", "Cash")
        ok("owed", "repay", "Ana", "100", "--to", "Cash")
        out = ok("owed", "list")
        self.assertIn("Juan", out)
        self.assertNotIn("Ana", out)
        self.assertIn("₱500.00", out)


if __name__ == "__main__":
    unittest.main()
