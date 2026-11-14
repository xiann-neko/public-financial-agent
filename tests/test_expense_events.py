import unittest
from datetime import date

from fincore.budget import expense_events, period_status
from fincore.goals import essential_monthly
from fincore.model import Category, Installment
from fincore.periods import period_for
from fincore.review import weekly_review
from tests.helpers import TempData, store

CARD = "GCash"  # any account works for share accounting in the budget


def spent(category, d):
    return next(s.spent for s in period_status(store(), period_for(d)) if s.category == category)


class ExpenseEventsTest(unittest.TestCase):
    def setUp(self):
        self.ctx = TempData()
        self.ctx.__enter__()
        s = store()
        s.save_budget(s.categories() + [Category("Interest & fees", "expense", None, False)])

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def add(self, *inst):
        store().save_installments(list(inst))

    def test_share_counts_in_billing_period_only(self):
        self.add(Installment("i001", CARD, "Phone", "Shopping (planned)", 2400000, 12, 200000, date(2026, 11, 25)))
        self.assertEqual(spent("Shopping (planned)", date(2026, 11, 20)), 200000)
        self.assertEqual(spent("Shopping (planned)", date(2026, 12, 5)), 0)
        self.assertEqual(spent("Shopping (planned)", date(2026, 12, 25)), 200000)
        self.assertEqual(spent("Shopping (planned)", date(2027, 11, 25)), 0)

    def test_interest_part_goes_to_interest_category(self):
        self.add(Installment("i001", CARD, "TV", "Shopping (planned)", 1200000, 12, 110000, date(2026, 11, 25)))
        self.assertEqual(spent("Shopping (planned)", date(2026, 11, 25)), 100000)
        self.assertEqual(spent("Interest & fees", date(2026, 11, 25)), 10000)

    def test_events_list(self):
        self.add(Installment("i001", CARD, "Phone", "Impulse / wants", 300000, 3, 100000, date(2026, 11, 18)))
        ev = expense_events(store(), date(2026, 11, 14), date(2026, 11, 20))
        self.assertEqual(ev, [(date(2026, 11, 18), "Impulse / wants", 100000)])

    def test_review_and_essentials_see_shares(self):
        self.add(Installment("i001", CARD, "Phone", "Impulse / wants", 300000, 3, 100000, date(2026, 11, 18)),
                 Installment("i002", CARD, "Ref", "Groceries", 600000, 2, 300000, date(2026, 10, 1)))
        r = weekly_review(store(), date(2026, 11, 20))
        self.assertEqual(r["impulse_this_week"], 100000)
        self.assertEqual(r["total_spent"], 100000)
        self.assertEqual(essential_monthly(store(), date(2026, 11, 20)), 400000)  # 2 shares over 3 periods


if __name__ == "__main__":
    unittest.main()
