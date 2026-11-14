import json
import unittest

from fincore.cli import run
from tests.helpers import TempData

CARD = "Example Card"


def ok(*args, today="2026-11-14"):
    code, out, err = run(["--today", today, *args])
    assert code == 0, err
    return out


def plan(*extra, today="2026-11-14"):
    return json.loads(ok("plan", "--json", *extra, today=today))


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.ctx = TempData()
        self.ctx.__enter__()
        for c in json.loads((self.ctx.path / "budget.json").read_text())["categories"]:
            if c["kind"] == "expense":
                ok("category", "set", c["name"], "--limit", "none")
        ok("category", "set", "Groceries", "--limit", "3000")
        ok("category", "set", "Rent/housing", "--limit", "5000", "--bill-day", "30")
        ok("goal", "set", "Emergency fund", "--planned", "1000")
        ok("payday", "set", "15", "20,000")
        ok("payday", "set", "30", "19,000")

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_two_periods_from_next_payday(self):
        a, b = plan()
        self.assertEqual((a["period"], a["pay"]), ("Nov 15–29", 2000000))
        self.assertEqual(a["bills"], [])
        self.assertEqual(a["total_out"], 300000 + 100000)
        self.assertEqual(a["left"], 2000000 - 400000)
        self.assertEqual((b["period"], [x["name"] for x in b["bills"]]), ("Nov 30–Dec 14", ["Rent/housing"]))
        self.assertEqual(b["left"], 1900000 - 500000 - 300000 - 100000)

    def test_installment_share_in_its_period(self):
        ok("account", "add", CARD)
        ok("debt", "set", CARD, "--kind", "card", "--owed", "0", "--due-day", "20")
        ok("debt", "installment", CARD, "Phone", "12,000", "--months", "12", "--category", "Shopping (planned)",
           "--first", "2026-11-20")
        a = plan()[0]
        self.assertEqual([(x["name"], x["amount"]) for x in a["installments"]], [("Phone", 100000)])

    def test_short_and_unset_pay(self):
        ok("category", "set", "Groceries", "--limit", "30000")
        self.assertLess(plan()[0]["left"], 0)
        self.assertIn("Short by", ok("plan"))
        (self.ctx.path / "plan.json").unlink()
        self.assertIsNone(plan()[0]["left"])

    def test_bill_via_owed_not_cash_and_card_bill_counted(self):
        ok("category", "set", "Rent/housing", "--via", "owed")
        b = plan()[1]
        self.assertEqual(b["bills"], [])
        self.assertEqual([x["name"] for x in b["not_cash"]], ["Rent/housing"])
        ok("category", "set", "Groceries", "--bill-day", "4", "--via", "card")
        self.assertEqual([x["name"] for x in plan(today="2026-11-30")[0]["bills"]], ["Groceries"])
        # card-charged bills stay off the to-pay list: the card statement covers them
        r = json.loads(ok("report", "--month", "2026-12", "--json"))
        self.assertNotIn("Groceries", [x["name"] for x in r["to_pay"]])
        self.assertEqual([x["kind"] for x in r["to_pay"] if x["name"] == "Rent/housing"], ["owed"])

    def test_bad_payday(self):
        code, _, err = run(["payday", "set", "10", "1000"])
        self.assertEqual(code, 1)
        self.assertIn("15 or 30", err)


if __name__ == "__main__":
    unittest.main()
