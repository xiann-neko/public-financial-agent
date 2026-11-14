import json
import unittest

from fincore.cli import run
from fincore.payoff import SimDebt, simulate
from tests.helpers import TempData


class SimulateTest(unittest.TestCase):
    def test_zero_interest(self):
        r = simulate([SimDebt("A", 10000, 0.0, 2500, None)], 0)
        self.assertEqual((r.debts["A"].months, r.debts["A"].interest, r.debt_free_months), (4, 0, 4))

    def test_interest_hand_checked(self):
        r = simulate([SimDebt("A", 1000, 0.10, 600, None)], 0)
        self.assertEqual((r.debts["A"].months, r.debts["A"].interest), (2, 150))

    def test_never_when_payment_only_covers_interest(self):
        r = simulate([SimDebt("A", 100000, 0.05, 5000, None)], 0)
        self.assertEqual(r.debts["A"].status, "never")
        self.assertIsNone(r.debt_free_months)

    def test_no_payment_set(self):
        r = simulate([SimDebt("A", 100000, 0.03, None, None), SimDebt("B", 1000, 0.0, 500, None)], 0)
        self.assertEqual(r.debts["A"].status, "no-payment")
        self.assertEqual(r.debts["B"].months, 2)
        self.assertIsNone(r.debt_free_months)

    def test_scheduled_loan(self):
        r = simulate([SimDebt("Loan", 120000, 0.0, None, 24)], 0)
        self.assertEqual((r.debts["Loan"].months, r.debt_free_months), (24, 24))

    def test_avalanche_targets_highest_rate_and_rolls_over(self):
        debts = lambda: [SimDebt("Low", 100000, 0.01, 10000, None), SimDebt("High", 100000, 0.03, 10000, None)]  # noqa
        base = simulate(debts(), 0)
        fast = simulate(debts(), 20000)
        self.assertEqual(fast.first_target, "High")
        self.assertLess(fast.debts["High"].months, base.debts["High"].months)
        self.assertLess(fast.debts["Low"].months, base.debts["Low"].months)
        self.assertLess(fast.total_interest, base.total_interest)
        self.assertLess(fast.debt_free_months, base.debt_free_months)

    def test_extra_rescues_never(self):
        r = simulate([SimDebt("A", 100000, 0.05, 5000, None)], 5000)
        self.assertEqual(r.debts["A"].status, "ok")


class PlanCliTest(unittest.TestCase):
    def test_plan_text_and_json(self):
        with TempData():
            run(["account", "add", "Card"])
            run(["--today", "2026-11-20", "debt", "set", "Card", "--kind", "card", "--owed", "20000", "--rate", "3",
                 "--payment", "5000"])
            run(["--today", "2026-11-20", "debt", "set", "Loan", "--kind", "loan", "--owed", "60000",
                 "--payment", "5000", "--end", "2027-10"])
            code, out, err = run(["--today", "2026-11-20", "debt", "plan", "--extra", "2000"])
            self.assertEqual(code, 0, err)
            self.assertIn("Debt-free", out)
            self.assertIn("Card", out)
            self.assertIn("Oct 2027", out)
            data = json.loads(run(["--today", "2026-11-20", "debt", "plan", "--extra", "2000", "--json"])[1])
            self.assertEqual(data["with_extra"]["first_target"], "Card")
            self.assertLess(data["with_extra"]["total_interest"], data["current"]["total_interest"])


if __name__ == "__main__":
    unittest.main()
