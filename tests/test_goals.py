import json
import unittest
from datetime import date

from fincore.budget import period_status
from fincore.cli import run
from fincore.goals import delay_days, essential_monthly, progress, savings_rate, target
from fincore.periods import period_for
from tests.helpers import TempData, store

TODAY = date(2026, 11, 20)
EF = "Emergency fund"


def ok(*args, today="2026-11-20"):
    code, out, err = run(["--today", today, *args])
    assert code == 0, err
    return out


def goal():
    return next(g for g in store().goals() if g.name == EF)


class GoalsTest(unittest.TestCase):
    def setUp(self):
        self.ctx = TempData()
        self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def contribute(self, amount, day):
        ok("goal", "contribute", EF, amount, "--from", "GCash", "--to", "Savings", "--date", day)

    def test_progress_contributions_minus_withdrawals(self):
        self.contribute("1000", "2026-11-01")
        self.contribute("500", "2026-11-02")
        ok("goal", "withdraw", EF, "300", "--from", "Savings", "--to", "GCash", "--date", "2026-11-03")
        self.assertEqual(progress(store(), goal()), 120000)
        wid = next(t.id for t in store().transactions() if t.goal == "-" + EF)
        ok("delete", wid)
        self.assertEqual(progress(store(), goal()), 150000)
        cid = next(t.id for t in store().transactions() if t.goal == EF)
        ok("edit", cid, "--amount", "2000")
        self.assertEqual(progress(store(), goal()), 250000)

    def test_opening_counts_in_progress_not_rate(self):
        ok("goal", "opening", EF, "5000", "--account", "Savings")
        self.assertEqual(progress(store(), goal()), 500000)
        self.assertEqual(savings_rate(store(), goal(), TODAY), goal().planned_per_period)

    def test_unknown_goal_rejected(self):
        code, _, err = run(["goal", "contribute", "Car", "100", "--from", "GCash", "--to", "Savings"])
        self.assertEqual(code, 1)
        self.assertIn(EF, err)

    def test_delay_days(self):
        self.assertEqual(delay_days(250000, 100000), 39)
        self.assertIsNone(delay_days(250000, 0))
        self.assertIsNone(delay_days(250000, -5))

    def test_savings_rate_uses_planned_until_six_periods(self):
        # 5 completed periods of history (Aug 30 .. Nov 14)
        for d in ["2026-08-31", "2026-09-16", "2026-10-01", "2026-10-16", "2026-11-01"]:
            self.contribute("2000", d)
        self.assertEqual(savings_rate(store(), goal(), TODAY), 100000)

    def test_savings_rate_averages_last_six_periods(self):
        for d in ["2026-08-16", "2026-08-31", "2026-09-16", "2026-10-01", "2026-10-16", "2026-11-01"]:
            self.contribute("2000", d)
        ok("goal", "withdraw", EF, "600", "--from", "Savings", "--to", "GCash", "--date", "2026-11-02")
        self.contribute("9999", "2026-11-16")  # current period: ignored
        self.assertEqual(savings_rate(store(), goal(), TODAY), (1200000 - 60000) // 6)

    def test_essential_monthly_and_auto_target(self):
        self.assertIsNone(essential_monthly(store(), TODAY))
        ok("add", "expense", "3000", "--category", "Groceries", "--account", "Cash", "--date", "2026-10-20")
        self.assertIsNone(essential_monthly(store(), TODAY))
        ok("add", "expense", "3000", "--category", "Groceries", "--account", "Cash", "--date", "2026-11-01")
        ok("add", "expense", "9999", "--category", "Impulse / wants", "--account", "Cash", "--date", "2026-11-01")
        self.assertEqual(essential_monthly(store(), TODAY), 600000)
        self.assertEqual(target(store(), goal(), TODAY), 1800000)
        ok("goal", "set", EF, "--target", "50000")
        self.assertEqual(target(store(), goal(), TODAY), 5000000)
        ok("goal", "set", EF, "--target", "auto", "--months", "6")
        self.assertEqual(target(store(), goal(), TODAY), 3600000)

    def test_goal_transfers_do_not_touch_budget(self):
        self.contribute("1000", "2026-11-20")
        self.assertTrue(all(s.spent == 0 for s in period_status(store(), period_for(TODAY))))

    def test_add_and_list(self):
        ok("goal", "add", "Laptop", "--target", "40000", "--planned", "2000", "--priority", "2")
        self.contribute("1000", "2026-11-16")
        data = json.loads(ok("goal", "list", "--json"))
        self.assertEqual([g["name"] for g in data], [EF, "Laptop"])
        self.assertEqual(data[0]["progress"], 100000)
        self.assertEqual(data[1]["target"], 4000000)
        self.assertIn("Laptop", ok("goal", "list"))


if __name__ == "__main__":
    unittest.main()
