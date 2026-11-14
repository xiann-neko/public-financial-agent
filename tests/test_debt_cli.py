import json
import unittest

from fincore.cli import run
from tests.helpers import TempData, store

CARD = "Example Card"


def ok(*args, today="2026-11-20"):
    code, out, err = run(["--today", today, *args])
    assert code == 0, err
    return out


def debts():
    return {d["name"]: d for d in json.loads(ok("debt", "list", "--json"))["debts"]}


class DebtCliTest(unittest.TestCase):
    def setUp(self):
        self.ctx = TempData()
        self.ctx.__enter__()
        ok("account", "add", CARD)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_set_converts_existing_account(self):
        ok("debt", "set", CARD, "--kind", "card", "--owed", "15,000", "--due-day", "25", "--limit", "50000",
           "--rate", "3", "--payment", "5000")
        a = next(a for a in store().accounts() if a.name == CARD)
        self.assertEqual((a.kind, a.opening_balance, a.due_day, a.credit_limit, a.rate_monthly, a.payment),
                         ("credit_card", 1500000, 25, 5000000, 3.0, 500000))
        d = debts()[CARD]
        self.assertEqual((d["owed"], d["next_due"], d["days_to_due"], d["limit_used_pct"]),
                         (1500000, "2026-11-25", 5, 30.0))

    def test_set_creates_loan(self):
        ok("debt", "set", "Pag-IBIG loan", "--kind", "loan", "--owed", "120000", "--due-day", "5",
           "--payment", "3500", "--end", "2029-12")
        self.assertEqual(debts()["Pag-IBIG loan"]["owed"], 12000000)
        self.assertEqual(run(["debt", "set", "X", "--kind", "loan", "--owed", "0", "--end", "2029-13"])[0], 1)
        self.assertEqual(run(["debt", "set", "Y", "--kind", "loan", "--owed", "0", "--due-day", "32"])[0], 1)

    def test_pay_with_interest_split(self):
        ok("debt", "set", "Pag-IBIG loan", "--kind", "loan", "--owed", "120000")
        ok("debt", "pay", "Pag-IBIG loan", "3500", "--from", "GCash", "--interest", "900")
        self.assertEqual(debts()["Pag-IBIG loan"]["owed"], 12000000 - 260000)
        txns = store().transactions()
        self.assertEqual({(t.type, t.amount, t.category) for t in txns},
                         {("transfer", 260000, ""), ("expense", 90000, "Interest & fees")})
        self.assertIn("Interest & fees", [c.name for c in store().categories()])

    def test_pay_rejects_interest_over_amount_and_non_debt(self):
        ok("debt", "set", CARD, "--kind", "card", "--owed", "0")
        self.assertEqual(run(["debt", "pay", CARD, "100", "--from", "GCash", "--interest", "200"])[0], 1)
        self.assertEqual(run(["debt", "pay", "GCash", "100", "--from", "Cash"])[0], 1)

    def test_charge_adds_to_owed(self):
        ok("debt", "set", CARD, "--kind", "card", "--owed", "1000")
        ok("debt", "charge", CARD, "350", "--note", "late fee")
        self.assertEqual(debts()[CARD]["owed"], 135000)

    def test_card_purchase_adds_to_owed(self):
        ok("debt", "set", CARD, "--kind", "card", "--owed", "0")
        ok("add", "expense", "2,000", "--category", "Groceries", "--account", CARD)
        self.assertEqual(debts()[CARD]["owed"], 200000)

    def test_installment(self):
        ok("debt", "set", CARD, "--kind", "card", "--owed", "0", "--due-day", "25")
        out = ok("debt", "installment", CARD, "Phone", "24000", "--months", "12", "--category", "Shopping (planned)")
        self.assertIn("₱2,000.00", out)
        i = store().installments()[0]
        self.assertEqual((i.monthly, i.first_billing.isoformat()), (200000, "2026-11-25"))
        self.assertEqual(debts()[CARD]["owed"], 0)  # not billed yet on Nov 20
        self.assertEqual(debts()[CARD]["installments_left"], 2400000)
        code, _, err = run(["--today", "2026-11-20", "debt", "installment", CARD, "Phone", "24000", "--months", "12",
                            "--category", "Shopping (planned)"])
        self.assertEqual(code, 3)
        ok("debt", "installment", CARD, "Phone", "24000", "--months", "12", "--category", "Shopping (planned)",
           "--allow-duplicate")
        self.assertEqual(len(store().installments()), 2)

    def test_installment_needs_card(self):
        ok("debt", "set", "Loan", "--kind", "loan", "--owed", "0")
        self.assertEqual(run(["debt", "installment", "Loan", "X", "100", "--months", "2", "--category", "Other"])[0], 1)
        self.assertEqual(run(["debt", "installment", CARD, "X", "100", "--months", "0", "--category", "Other"])[0], 1)

    def test_next_due_rolls_to_next_month_and_clamps(self):
        ok("debt", "set", CARD, "--kind", "card", "--owed", "0", "--due-day", "31")
        self.assertEqual(debts()[CARD]["next_due"], "2026-11-30")
        d = json.loads(run(["--today", "2027-02-10", "debt", "list", "--json"])[1])["debts"][0]
        self.assertEqual(d["next_due"], "2027-02-28")

    def test_list_text(self):
        ok("debt", "set", CARD, "--kind", "card", "--owed", "15000", "--due-day", "25")
        out = ok("debt", "list")
        self.assertIn("₱15,000.00", out)
        self.assertIn("Nov 25", out)


if __name__ == "__main__":
    unittest.main()
