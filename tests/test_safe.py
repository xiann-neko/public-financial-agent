import json
import unittest

from fincore.cli import run
from tests.helpers import TempData


def ok(*args, today="2026-11-14"):
    code, out, err = run(["--today", today, *args])
    assert code == 0, err
    return out


def safe(*extra, today="2026-11-14"):
    return json.loads(ok("safe", "--json", *extra, today=today))


class SafeTest(unittest.TestCase):
    def setUp(self):
        self.ctx = TempData()
        self.ctx.__enter__()
        # keep only two limited categories so expected numbers stay readable
        for c in json.loads((self.ctx.path / "budget.json").read_text())["categories"]:
            if c["kind"] == "expense" and c["name"] not in ("Groceries", "Rent/housing"):
                ok("category", "set", c["name"], "--limit", "none")
        ok("category", "set", "Groceries", "--limit", "3000")
        ok("category", "set", "Rent/housing", "--limit", "5000", "--bill-day", "20")
        ok("add", "income", "40,000", "--category", "Salary", "--account", "Cash", "--date", "2026-11-12")

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_balance_minus_set_asides_bills_and_budgets(self):
        ok("setaside", "add", "Trip", "10,000")
        r = safe("--until", "2026-11-30")
        self.assertEqual(r["money_total"], 4000000)
        self.assertEqual([b["name"] for b in r["bills"]], ["Rent/housing"])  # due Nov 20, before payday
        self.assertEqual(sum(b["amount"] for b in r["budgets"]), 600000)  # groceries, two pay periods
        self.assertEqual(r["safe"], 4000000 - 1000000 - 500000 - 600000)

    def test_bill_due_on_payday_is_not_held(self):
        ok("category", "set", "Rent/housing", "--bill-day", "30")
        self.assertEqual(safe("--until", "2026-11-30")["bills"], [])

    def test_paid_bill_and_overspent_budget_count_as_zero(self):
        ok("add", "expense", "5,000", "--category", "Rent/housing", "--account", "Cash", "--date", "2026-11-13")
        ok("add", "expense", "4,000", "--category", "Groceries", "--account", "Cash", "--date", "2026-11-13")
        r = safe()  # until the next payday, Nov 15
        self.assertEqual((r["bills"], r["budgets"]), ([], []))
        self.assertEqual(r["safe"], 4000000 - 500000 - 400000)

    def test_except_category_not_held_back(self):
        r = safe("--until", "2026-11-30", "--except", "Groceries")
        self.assertEqual(r["budgets"], [])

    def test_savings_accounts_not_counted(self):
        ok("account", "add", "Savings Acct", "--opening", "50000")
        ok("account", "set", "Savings Acct", "--role", "savings")
        self.assertEqual(safe()["money_total"], 4000000)

    def test_setaside_add_set_drop(self):
        ok("setaside", "add", "Gifts", "13,000")
        ok("setaside", "set", "Gifts", "12,000")
        self.assertEqual(safe()["set_asides"], [{"name": "Gifts", "amount": 1200000}])
        self.assertIn("already", run(["setaside", "add", "Gifts", "1"])[2])
        ok("setaside", "drop", "gifts")
        self.assertEqual(safe()["set_asides"], [])
        self.assertIn("Nothing set aside.", ok("setaside", "list"))


if __name__ == "__main__":
    unittest.main()
