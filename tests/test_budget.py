import json
import unittest
from datetime import date

from fincore.budget import period_status, warnings
from fincore.cli import run
from fincore.model import Category
from fincore.periods import period_for
from tests.helpers import TempData, store

NOV15 = period_for(date(2026, 11, 20))


class BudgetTest(unittest.TestCase):
    def setUp(self):
        self.ctx = TempData()
        self.ctx.__enter__()
        s = store()
        cats = [c for c in s.categories()]
        for c in cats:
            if c.name == "Groceries":
                c.limit = 100000
            if c.name == "Other":
                c.limit = None
        s.save_budget(cats)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def spend(self, amount, day="2026-11-20", category="Groceries"):
        code, out, err = run(["--today", day, "add", "expense", amount, "--category", category, "--account", "Cash",
                              "--allow-duplicate"])
        self.assertEqual(code, 0, err)
        return out

    def groceries(self):
        return next(c for c in period_status(store(), NOV15) if c.category == "Groceries")

    def test_levels(self):
        self.spend("799")
        self.assertEqual(self.groceries().level, "ok")
        self.spend("1")
        self.assertEqual(self.groceries().level, "near")
        self.spend("200")
        g = self.groceries()
        self.assertEqual((g.level, g.spent, g.remaining), ("near", 100000, 0))
        self.spend("0.01")
        self.assertEqual(self.groceries().level, "over")
        self.assertEqual(self.groceries().remaining, -1)

    def test_previous_period_and_transfers_and_income_ignored(self):
        self.spend("500", day="2026-11-14")
        run(["--today", "2026-11-20", "add", "transfer", "500", "--account", "Cash", "--to", "Savings"])
        run(["--today", "2026-11-20", "add", "income", "500", "--category", "Salary", "--account", "Cash"])
        self.assertEqual(self.groceries().spent, 0)

    def test_no_limit(self):
        self.spend("50", category="Other")
        o = next(c for c in period_status(store(), NOV15) if c.category == "Other")
        self.assertEqual((o.level, o.remaining, o.ratio), ("no-limit", None, None))

    def test_only_expense_categories(self):
        names = [c.category for c in period_status(store(), NOV15)]
        self.assertNotIn("Salary", names)

    def test_warnings_filter(self):
        self.spend("850")
        self.assertEqual([w.category for w in warnings(period_status(store(), NOV15))], ["Groceries"])

    def test_add_prints_category_line_and_warning(self):
        out = self.spend("850")
        self.assertIn("near", out)
        self.assertIn("₱150.00", out)

    def test_status_command(self):
        self.spend("850")
        code, out, _ = run(["--today", "2026-11-20", "status"])
        self.assertEqual(code, 0)
        self.assertIn("Nov 15–29", out)
        self.assertIn("Groceries", out)
        data = json.loads(run(["--today", "2026-11-20", "status", "--json"])[1])
        g = next(c for c in data["categories"] if c["category"] == "Groceries")
        self.assertEqual(g["spent"], 85000)


if __name__ == "__main__":
    unittest.main()
