import unittest
from datetime import date, datetime

from fincore.cli import run
from fincore.review import startup_summary, weekly_review
from fincore.waitlist import check_purchase
from tests.helpers import TempData, store

CARD = "Example Card"


def ok(*args, today="2026-11-20"):
    code, out, err = run(["--today", today, *args])
    assert code == 0, err
    return out


def summary(day):
    return "\n".join(startup_summary(store(), datetime.fromisoformat(day + "T09:00:00")))


class DebtAlertsTest(unittest.TestCase):
    def setUp(self):
        self.ctx = TempData()
        self.ctx.__enter__()
        ok("debt", "set", CARD, "--kind", "card", "--owed", "15000", "--due-day", "25", "--limit", "50000")

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_check_with_card(self):
        r = check_purchase(store(), 250000, "Impulse / wants", date(2026, 11, 20), account=CARD)
        self.assertEqual((r.card_owed_before, r.card_owed_after, r.card_limit_pct_after), (1500000, 1750000, 35.0))
        out = ok("check", "2500", "Impulse / wants", "--account", CARD)
        self.assertIn("You still owe ₱15,000.00 on Example Card", out)
        self.assertIn("₱17,500.00", out)
        self.assertIn("35.0% of limit", out)

    def test_check_with_cash_has_no_card_line(self):
        out = ok("check", "2500", "Impulse / wants", "--account", "Cash")
        self.assertNotIn("still owe", out)

    def test_check_installment_uses_monthly_share_for_budget(self):
        r = check_purchase(store(), 2400000, "Shopping (planned)", date(2026, 11, 20), account=CARD, months=12)
        self.assertEqual(r.remaining_before - r.remaining_after, 200000)
        self.assertEqual(r.card_owed_after, 1500000 + 2400000)
        self.assertIn("₱2,000.00 a month", ok("check", "24000", "Shopping (planned)", "--account", CARD,
                                               "--months", "12"))

    def test_due_soon_reminder(self):
        self.assertIn("Example Card due Nov 25 (in 3 days)", summary("2026-11-22"))
        self.assertIn("due today", summary("2026-11-25"))
        self.assertNotIn("Example Card", summary("2026-11-10"))

    def test_payment_since_last_due_silences_reminder(self):
        ok("debt", "pay", CARD, "5000", "--from", "GCash", "--date", "2026-11-01")
        self.assertNotIn("Example Card", summary("2026-11-22"))

    def test_overdue(self):
        self.assertIn("Example Card is overdue (was due Nov 25)", summary("2026-11-27"))
        ok("debt", "pay", CARD, "5000", "--from", "GCash", "--date", "2026-11-26")
        self.assertNotIn("overdue", summary("2026-11-27"))

    def test_nothing_owed_no_reminder(self):
        ok("debt", "set", CARD, "--kind", "card", "--owed", "0")
        self.assertNotIn("Example Card", summary("2026-11-22"))

    def test_receivable_overdue(self):
        ok("owed", "lend", "Juan", "500", "--from", "Cash", "--due", "2026-11-21")
        self.assertNotIn("Juan", summary("2026-11-21"))
        self.assertIn("Juan owes you ₱500.00 (was due Nov 21)", summary("2026-11-22"))

    def test_review_debt_section(self):
        ok("debt", "charge", CARD, "300", today="2026-11-18")
        ok("debt", "pay", CARD, "2000", "--from", "GCash", today="2026-11-19")
        ok("owed", "lend", "Juan", "500", "--from", "Cash", today="2026-11-19")
        r = weekly_review(store(), date(2026, 11, 20))
        self.assertEqual(r["debt_total"], 1500000 + 30000 - 200000)
        self.assertEqual(r["debt_change_week"], 30000 - 200000)
        self.assertEqual(r["interest_this_week"], 30000)
        self.assertEqual(r["owed_to_you"], 50000)
        self.assertIn("Debt: ₱13,300.00", ok("review"))


if __name__ == "__main__":
    unittest.main()
