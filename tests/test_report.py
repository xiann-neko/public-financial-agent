import json
import os
import tempfile
import unittest

from fincore.cli import run
from tests.helpers import TempData

CARD = "Example Card"


def ok(*args, today="2026-11-20"):
    code, out, err = run(["--today", today, *args])
    assert code == 0, err
    return out


def report(month="2026-11", today="2026-11-20"):
    return json.loads(ok("report", "--month", month, "--json", today=today))


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.ctx = TempData()
        self.ctx.__enter__()
        ok("account", "add", CARD)
        ok("debt", "set", CARD, "--kind", "card", "--owed", "10,000", "--due-day", "25", "--payment", "10,000")

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_income_expenses_and_net_for_the_month_only(self):
        ok("add", "income", "40,000", "--category", "Salary", "--account", "Cash", "--date", "2026-11-14")
        ok("add", "expense", "500", "--category", "Groceries", "--account", "Cash", "--date", "2026-11-03")
        ok("add", "expense", "999", "--category", "Groceries", "--account", "Cash", "--date", "2026-10-31")
        s = report()["summary"]
        self.assertEqual((s["income"], s["expenses"], s["net"]), (4000000, 50000, 3950000))

    def test_installment_share_counts_in_its_billing_month(self):
        ok("debt", "installment", CARD, "Phone", "12,000", "--months", "12", "--category", "Shopping (planned)",
           "--first", "2026-12-25")
        self.assertEqual(report()["summary"]["expenses"], 0)
        dec = report("2026-12")
        self.assertEqual(dec["summary"]["expenses"], 100000)
        self.assertEqual(dec["installments"][0]["left"], 12)

    def test_opening_savings_not_counted_as_saved_this_month(self):
        ok("goal", "set", "Emergency fund", "--planned", "1000")
        ok("goal", "opening", "Emergency fund", "5000", "--account", "Cash", today="2026-11-02")
        ok("account", "add", "Bank")
        ok("goal", "contribute", "Emergency fund", "1,000", "--from", "Cash", "--to", "Bank", today="2026-11-16")
        s = report()["summary"]
        self.assertEqual(s["savings_actual"], 100000)
        self.assertEqual(s["savings_goal"], 200000)  # two pay periods start in November

    def test_debt_goal_only_for_bills_due_that_month_and_payments_count(self):
        ok("debt", "pay", CARD, "4,000", "--from", "Cash", today="2026-11-20")
        s = report()["summary"]
        self.assertEqual((s["debt_goal"], s["debt_paid"]), (1000000, 400000))
        ok("debt", "set", CARD, "--kind", "card", "--due-day", "5")
        self.assertEqual(report()["summary"]["debt_goal"], 0)  # Nov 5 came before tracking began (Nov 20)
        self.assertEqual(report("2026-12")["summary"]["debt_goal"], 1000000)

    def test_due_date_before_tracking_is_not_a_goal(self):
        ok("account", "add", "Other Card", today="2026-11-14")
        ok("debt", "set", "Other Card", "--kind", "card", "--owed", "5,000", "--due-day", "7", "--payment", "5,000",
           today="2026-11-14")
        self.assertNotIn("Other Card", [b["name"] for b in report()["debt_bills"]])
        self.assertIn("Other Card", [b["name"] for b in report("2026-12")["debt_bills"]])

    def test_html_page_has_the_seven_rows(self):
        path = os.path.join(tempfile.mkdtemp(), "t.html")
        ok("report", "--html", path)
        with open(path, encoding="utf-8") as f:
            html = f.read()
        for label in ("Total income", "Total expenses", "Income − expenses", "Savings goal", "Actual savings",
                      "Debt payment goal", "Actual debt paid"):
            self.assertIn(label, html)
        self.assertNotIn("<script src", html)

    def test_monthly_bill_status_due_paid_overdue(self):
        ok("category", "set", "Rent/housing", "--bill-day", "15", "--limit", "5000")
        bill = lambda r: next(x for x in r["to_pay"] if x["name"] == "Rent/housing")
        self.assertEqual(bill(report(today="2026-11-10"))["status"], "due")
        self.assertEqual(bill(report(today="2026-11-20"))["status"], "overdue")
        ok("add", "expense", "5,000", "--category", "Rent/housing", "--account", "Cash", "--date", "2026-11-12")
        b = bill(report(today="2026-11-20"))
        self.assertEqual((b["due"], b["expected"], b["paid"], b["status"]), ("2026-11-15", 500000, 500000, "paid"))

    def test_quarterly_bill_only_in_its_months(self):
        ok("category", "add", "Quarterly bill", "--bill-day", "10", "--every", "3", "--from", "2026-12-10",
           "--bill-amount", "1,000")
        names = lambda m: [x["name"] for x in report(m)["to_pay"]]
        self.assertNotIn("Quarterly bill", names("2026-11"))
        self.assertIn("Quarterly bill", names("2026-12"))
        self.assertNotIn("Quarterly bill", names("2027-01"))
        self.assertIn("Quarterly bill", names("2027-03"))

    def test_quarterly_bill_needs_a_from_date(self):
        code, _, err = run(["category", "add", "Quarterly bill", "--bill-day", "2", "--every", "3"])
        self.assertEqual(code, 1)
        self.assertIn("--from", err)

    def test_card_bill_paid_by_debt_payment_in_window(self):
        card = lambda r: next(x for x in r["to_pay"] if x["name"] == CARD)
        self.assertEqual(card(report())["status"], "due")
        ok("debt", "pay", CARD, "10,000", "--from", "Cash", today="2026-11-24")
        self.assertEqual(card(report(today="2026-11-26"))["status"], "paid")

    def test_savings_moves(self):
        ok("goal", "set", "Emergency fund", "--planned", "1000")
        ok("account", "add", "Bank")
        moves = lambda today: {x["period"]: x["status"] for x in report(today=today)["savings_moves"]}
        self.assertEqual(moves("2026-11-20"), {"Nov 15–29": "not yet moved", "Nov 30–Dec 14": "upcoming"})
        # moved 2 days before the Nov 30 payday: counts toward that pay period
        ok("goal", "contribute", "Emergency fund", "1,000", "--from", "Cash", "--to", "Bank", today="2026-11-28")
        self.assertEqual(moves("2026-11-28")["Nov 30–Dec 14"], "moved")

    def test_money_in_and_out_lists(self):
        ok("add", "income", "40,000", "--category", "Salary", "--account", "Cash", "--date", "2026-11-14")
        ok("add", "expense", "500", "--category", "Groceries", "--account", "Cash", "--date", "2026-11-03",
           "--payee", "Market")
        ok("owed", "lend", "Friend", "1,000", "--from", "Cash", "--date", "2026-11-01")
        ok("owed", "repay", "Friend", "400", "--to", "Cash", "--date", "2026-11-05")
        r = report()
        self.assertEqual([(x["what"], x["amount"]) for x in r["inflows"]], [("Salary", 4000000), ("Friend", 40000)])
        self.assertEqual([(x["what"], x["amount"]) for x in r["outflows"]], [("Market", 50000)])

    def test_old_budget_without_bill_fields_loads(self):
        import json as _json
        path = self.ctx.path / "budget.json"
        data = _json.loads(path.read_text())
        for c in data["categories"]:
            for k in ("bill_day", "bill_every", "bill_from", "bill_amount"):
                c.pop(k, None)
        path.write_text(_json.dumps(data))
        self.assertEqual(report()["to_pay"][0]["name"], CARD)

    def test_balances_and_money_left_leave_out_savings(self):
        ok("account", "add", "Savings Acct")
        ok("account", "set", "Savings Acct", "--role", "savings")
        ok("add", "income", "40,000", "--category", "Salary", "--account", "Cash", "--date", "2026-11-14")
        ok("add", "expense", "500", "--category", "Groceries", "--account", "Cash", "--date", "2026-11-15")
        ok("add", "expense", "300", "--category", "Groceries", "--account", CARD, "--date", "2026-11-15")
        ok("goal", "contribute", "Emergency fund", "1,000", "--from", "Cash", "--to", "Savings Acct",
           today="2026-11-16")
        r = report()
        self.assertEqual(r["money_left"], 3850000)  # card spending isn't cash until the card is paid
        bal = {b["name"]: (b["role"], b["balance"]) for b in r["balances"]}
        self.assertEqual(bal["Cash"], ("spending", 3850000))
        self.assertEqual(bal["Savings Acct"], ("savings", 100000))

    def test_account_set_balance_matches_today(self):
        ok("add", "expense", "500", "--category", "Groceries", "--account", "Cash", "--date", "2026-11-10")
        ok("account", "set", "Cash", "--balance", "2,000")
        bal = {b["name"]: b["balance"] for b in report()["balances"]}
        self.assertEqual(bal["Cash"], 200000)
        ok("account", "set", "Cash", "--role", "hidden")
        self.assertNotIn("Cash", [b["name"] for b in report()["balances"]])

    def test_bad_month_is_rejected(self):
        code, _, err = run(["report", "--month", "2026-13"])
        self.assertEqual(code, 1)
        self.assertIn("YYYY-MM", err)


if __name__ == "__main__":
    unittest.main()
