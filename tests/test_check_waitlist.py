import json
import unittest
from datetime import datetime

from fincore.budget import period_status
from fincore.cli import run
from fincore.periods import period_for
from fincore.waitlist import check_purchase, due_items, saved_by_waiting
from tests.helpers import TempData, store

IMP = "Impulse / wants"
T = datetime(2026, 11, 20, 10, 0)


def ok(*args, now="2026-11-20T10:00:00"):
    code, out, err = run(["--today", now[:10], "--now", now, *args])
    assert code == 0, err
    return out


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.ctx = TempData()
        self.ctx.__enter__()
        s = store()
        cats = s.categories()
        for c in cats:
            if c.name == IMP:
                c.limit = 300000
        s.save_budget(cats)
        ok("add", "expense", "1000", "--category", IMP, "--account", "Cash")

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def set_planned(self, amount):
        ok("goal", "set", "Emergency fund", "--planned", amount)

    def test_non_essential_purchase(self):
        r = check_purchase(store(), 250000, IMP, T.date())
        self.assertEqual((r.essential, r.suggest_wait, r.ef_delay_days, r.ef_rate_zero),
                         (False, True, 39, False))
        self.assertEqual((r.remaining_before, r.remaining_after, r.goal), (200000, -50000, "Emergency fund"))

    def test_essential_purchase_no_wait(self):
        self.assertFalse(check_purchase(store(), 250000, "Groceries", T.date()).suggest_wait)

    def test_zero_savings_rate(self):
        self.set_planned("0")
        r = check_purchase(store(), 250000, IMP, T.date())
        self.assertTrue(r.ef_rate_zero)
        self.assertIsNone(r.ef_delay_days)
        out = ok("check", "2500", IMP)
        self.assertIn("isn't growing", out)
        self.assertNotIn("None", out)
        self.assertNotIn("inf", out)

    def test_cli_text(self):
        out = ok("check", "2500", IMP)
        self.assertIn("over by ₱500.00", out)
        self.assertIn("39 days", out)
        self.assertIn("cooling-off", out)
        self.assertEqual(json.loads(ok("check", "2500", IMP, "--json"))["ef_delay_days"], 39)

    def test_unknown_category(self):
        self.assertEqual(run(["check", "100", "Toys"])[0], 1)


class WaitlistTest(unittest.TestCase):
    def setUp(self):
        self.ctx = TempData()
        self.ctx.__enter__()
        ok("wait", "add", "Headphones", "2500", IMP, now="2026-11-14T10:00:00")
        self.wid = store().waitlist()[0].id

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_due_after_48_hours(self):
        self.assertEqual(store().waitlist()[0].due_at, datetime(2026, 11, 16, 10, 0))
        self.assertEqual(due_items(store(), datetime(2026, 11, 16, 9, 59)), [])
        self.assertEqual(len(due_items(store(), datetime(2026, 11, 16, 10, 0))), 1)
        self.assertIn("Headphones", ok("wait", "due", now="2026-11-16T10:00:00"))

    def test_drop_counts_as_saved(self):
        ok("wait", "drop", self.wid)
        self.assertEqual(saved_by_waiting(store()), 250000)
        self.assertIn("₱2,500.00", ok("wait", "list"))

    def test_buy_requires_account_and_logs_expense(self):
        self.assertEqual(run(["wait", "buy", self.wid])[0], 1)
        ok("wait", "buy", self.wid, "--account", "GCash")
        t = store().transactions()[0]
        self.assertEqual((t.amount, t.category, t.source, t.payee), (250000, IMP, "waitlist", "Headphones"))
        self.assertEqual(store().waitlist()[0].txn_id, t.id)
        st = next(s for s in period_status(store(), period_for(t.date)) if s.category == IMP)
        self.assertEqual(st.spent, 250000)
        self.assertEqual(saved_by_waiting(store()), 0)

    def test_cannot_resolve_twice(self):
        ok("wait", "drop", self.wid)
        self.assertEqual(run(["wait", "drop", self.wid])[0], 1)
        self.assertEqual(run(["wait", "buy", self.wid, "--account", "Cash"])[0], 1)

    def test_custom_hours(self):
        ok("wait", "add", "Shoes", "3000", IMP, "--hours", "24", now="2026-11-14T10:00:00")
        self.assertEqual(store().waitlist()[1].due_at, datetime(2026, 11, 15, 10, 0))


if __name__ == "__main__":
    unittest.main()
