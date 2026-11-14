import json
import os
import unittest
from datetime import date, datetime

from fincore.cli import run
from fincore.review import startup_summary, weekly_review
from tests.helpers import TempData, store

IMP = "Impulse / wants"


def ok(*args, today="2026-11-20"):
    code, out, err = run(["--today", today, "--now", today + "T09:00:00", *args])
    assert code == 0, err
    return out


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.ctx = TempData()
        self.ctx.__enter__()
        ok("add", "expense", "800", "--category", IMP, "--account", "Cash", "--date", "2026-11-18")
        ok("add", "expense", "1200", "--category", IMP, "--account", "Cash", "--date", "2026-11-12")
        ok("add", "expense", "500", "--category", "Groceries", "--account", "Cash", "--date", "2026-11-14")
        ok("add", "income", "15000", "--category", "Salary", "--account", "GCash", "--date", "2026-11-15")
        ok("add", "transfer", "2000", "--account", "GCash", "--to", "Savings", "--date", "2026-11-16")

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_weekly_numbers(self):
        r = weekly_review(store(), date(2026, 11, 20))
        self.assertEqual((r["week_start"], r["week_end"]), ("2026-11-14", "2026-11-20"))
        self.assertEqual(r["impulse_this_week"], 80000)
        self.assertEqual(r["impulse_last_week"], 120000)
        self.assertEqual(r["total_spent"], 130000)
        self.assertEqual(r["total_income"], 1500000)
        self.assertEqual(r["spend_by_category"][0], {"category": IMP, "amount": 80000})
        self.assertEqual(r["period_label"], "Nov 15–29")

    def test_review_command_records_last_review(self):
        out = ok("review")
        self.assertIn("₱800.00", out)
        self.assertEqual(store().meta()["last_review"], "2026-11-20")

    def test_startup_mentions_due_item_and_review(self):
        ok("wait", "add", "Sneakers", "4000", IMP, today="2026-11-17")
        lines = startup_summary(store(), datetime(2026, 11, 20, 9))
        text = "\n".join(lines)
        self.assertIn("Sneakers", text)
        self.assertIn("Weekly review", text)
        ok("review", today="2026-11-12")
        self.assertIn("Weekly review", "\n".join(startup_summary(store(), datetime(2026, 11, 20, 9))))
        ok("review", today="2026-11-15")
        self.assertNotIn("Weekly review", "\n".join(startup_summary(store(), datetime(2026, 11, 20, 9))))



class StartupQuietTest(unittest.TestCase):
    def test_all_good(self):
        with TempData():
            ok("review")
            self.assertEqual(ok("startup").strip().splitlines(), ["All good."])


class StartupNoDataTest(unittest.TestCase):
    def test_no_data_still_warns_when_public(self):
        from unittest import mock
        with TempData(init=False):
            with mock.patch("fincore.guard.visibility_warning", return_value="⛔ This repo is PUBLIC"):
                code, out, _ = run(["startup"])
        self.assertEqual(code, 0)
        self.assertIn("PUBLIC", out)
        self.assertIn("set me up", out)

    def test_no_data_is_not_an_error(self):
        with TempData(init=False):
            code, out, err = run(["startup"])
        self.assertEqual(code, 0)
        self.assertIn("set me up", out)


if __name__ == "__main__":
    unittest.main()
