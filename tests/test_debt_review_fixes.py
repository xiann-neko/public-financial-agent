"""Regression tests for the debt-tracking final review."""
import json
import unittest
from datetime import date, datetime

from fincore.cli import run
from fincore.debts import installment_shares
from fincore.model import Installment
from fincore.payoff import SimDebt, simulate
from fincore.review import startup_summary
from tests.helpers import TempData, store

CARD = "Example Card"


def ok(*args, today="2026-11-20"):
    code, out, err = run(["--today", today, *args])
    assert code == 0, err
    return out


def owed_now(today="2026-11-20"):
    return {d["name"]: d for d in json.loads(ok("debt", "list", "--json", today=today))["debts"]}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.ctx = TempData()
        self.ctx.__enter__()
        ok("account", "add", CARD)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)


class OwedIsTodaysBalanceTest(Fixture):  # Critical 1
    def test_existing_spending_not_double_counted(self):
        ok("add", "expense", "2000", "--category", "Groceries", "--account", CARD, today="2026-11-10")
        ok("add", "transfer", "500", "--account", "GCash", "--to", CARD, today="2026-11-12")
        ok("debt", "set", CARD, "--kind", "card", "--owed", "12000")
        self.assertEqual(owed_now()[CARD]["owed"], 1200000)
        ok("add", "expense", "100", "--category", "Groceries", "--account", CARD, today="2026-11-21")
        self.assertEqual(owed_now("2026-11-21")[CARD]["owed"], 1210000)

    def test_converting_needs_owed(self):
        self.assertEqual(run(["debt", "set", CARD, "--kind", "card"])[0], 1)
        ok("debt", "set", CARD, "--kind", "card", "--owed", "0")
        ok("debt", "set", CARD, "--kind", "card", "--due-day", "25")  # already a debt: --owed optional
        self.assertEqual(owed_now()[CARD]["owed"], 0)


class NotOverdueBeforeTrackingTest(Fixture):  # Important 5
    def test_setup_after_due_day(self):
        ok("debt", "set", CARD, "--kind", "card", "--owed", "8000", "--due-day", "12", today="2026-11-14")
        text = "\n".join(startup_summary(store(), datetime(2026, 11, 14, 9)))
        self.assertNotIn("overdue", text)
        text = "\n".join(startup_summary(store(), datetime(2026, 12, 13, 9)))
        self.assertIn("overdue (was due Dec 12)", text)


class BasePlanNoRolloverTest(unittest.TestCase):  # Important 2, 3
    def test_never_stays_never_without_extra(self):
        r = simulate([SimDebt("Card A", 10000, 0.0, 3000, None), SimDebt("Card B", 800000, 0.03, 10000, None)], 0)
        self.assertEqual(r.debts["Card B"].status, "never")

    def test_never_interest_not_reported_and_no_savings_claim(self):
        r = simulate([SimDebt("A", 5000000, 0.03, 100000, None)], 0)
        self.assertIsNone(r.debts["A"].interest)
        with TempData():
            ok("account", "add", "Card")
            ok("debt", "set", "Card", "--kind", "card", "--owed", "50000", "--rate", "3", "--payment", "1000")
            out = ok("debt", "plan", "--extra", "2000")
            self.assertNotIn("saves about", out)
            self.assertIn("never", out.lower())


class InstallmentBillingDayTest(Fixture):  # Important 4
    def test_due_31st_keeps_31st_after_february(self):
        ok("debt", "set", CARD, "--kind", "card", "--owed", "0", "--due-day", "31")
        ok("debt", "installment", CARD, "TV", "6000", "--months", "3", "--category", "Shopping (planned)",
           today="2027-02-10")
        days = [d for d, _, _ in installment_shares(store().installments()[0])]
        self.assertEqual(days, [date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)])


class InstallmentManageTest(Fixture):  # Important 6
    def test_list_and_delete(self):
        ok("debt", "set", CARD, "--kind", "card", "--owed", "0", "--due-day", "25")
        ok("debt", "installment", CARD, "Phone", "24000", "--months", "12", "--category", "Shopping (planned)")
        self.assertIn("i001", ok("debt", "installments"))
        ok("debt", "installment-delete", "i001")
        self.assertEqual(store().installments(), [])
        self.assertEqual(run(["debt", "installment-delete", "i999"])[0], 1)

    def test_cannot_remove_card_with_installments(self):
        ok("debt", "set", CARD, "--kind", "card", "--owed", "0", "--due-day", "25")
        ok("debt", "installment", CARD, "Phone", "24000", "--months", "12", "--category", "Shopping (planned)")
        self.assertEqual(run(["account", "remove", CARD])[0], 1)


class ImportSkillTest(unittest.TestCase):  # Important 7
    def test_import_skill_covers_card_statements(self):
        from pathlib import Path
        text = (Path(__file__).resolve().parent.parent / ".claude/skills/import/SKILL.md").read_text()
        for phrase in ["installment", "debt pay", "debt charge"]:
            self.assertIn(phrase, text)


class ForwardCompatTest(unittest.TestCase):  # Important 8
    def test_unknown_account_and_installment_keys_ignored(self):
        with TempData() as d:
            accts = json.loads((d / "accounts.json").read_text())
            accts["accounts"][0]["future_field"] = 1
            (d / "accounts.json").write_text(json.dumps(accts))
            (d / "installments.json").write_text(json.dumps({"installments": [
                {"id": "i001", "card": "Cash", "item": "x", "category": "Other", "total": 100, "months": 1,
                 "monthly": 100, "first_billing": "2026-11-25", "future": True}]}))
            self.assertEqual(store().accounts()[0].name, "Cash")
            self.assertEqual(len(store().installments()), 1)


class MinorRegradedTest(Fixture):
    def test_failed_lend_leaves_no_account(self):
        self.assertEqual(run(["owed", "lend", "Juan", "500", "--from", "Cahs"])[0], 1)
        self.assertNotIn("Owed by Juan", [a.name for a in store().accounts()])

    def test_past_end_loan_with_balance_not_paid_off(self):
        ok("debt", "set", "Loan", "--kind", "loan", "--owed", "30000", "--end", "2026-06", "--payment", "5000")
        out = ok("debt", "plan")
        self.assertNotIn("paid off Nov 2026", out)

    def test_last_share_never_negative_interest(self):
        i = Installment("i1", "C", "X", "Other", 100011, 12, 8336, date(2026, 11, 25))
        self.assertTrue(all(x >= 0 for _, _, x in installment_shares(i)))
        self.assertEqual(sum(p for _, p, _ in installment_shares(i)), 100011)

    def test_rounding_is_not_interest(self):
        ok("debt", "set", CARD, "--kind", "card", "--owed", "0", "--due-day", "25")
        out = ok("debt", "installment", CARD, "Fan", "1000", "--months", "3", "--category", "Other")
        self.assertNotIn("interest", out)
        self.assertNotIn("Interest & fees", [c.name for c in store().categories()])


if __name__ == "__main__":
    unittest.main()
