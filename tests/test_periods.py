import unittest
from datetime import date, timedelta

from fincore.periods import Period, next_period, period_for, previous


class PeriodForTest(unittest.TestCase):
    def test_day_before_payday_is_in_previous_period(self):
        self.assertEqual(period_for(date(2026, 11, 14)), Period(date(2026, 10, 30), date(2026, 11, 14)))

    def test_fifteenth_starts_period_a(self):
        self.assertEqual(period_for(date(2026, 11, 15)), Period(date(2026, 11, 15), date(2026, 11, 29)))

    def test_thirty_first_is_in_period_b(self):
        self.assertEqual(period_for(date(2026, 12, 31)), Period(date(2026, 12, 30), date(2027, 1, 14)))

    def test_new_year(self):
        self.assertEqual(period_for(date(2027, 1, 1)).start, date(2026, 12, 30))

    def test_february_non_leap(self):
        self.assertEqual(period_for(date(2027, 2, 27)), Period(date(2027, 2, 15), date(2027, 2, 27)))
        self.assertEqual(period_for(date(2027, 2, 28)), Period(date(2027, 2, 28), date(2027, 3, 14)))

    def test_february_leap(self):
        self.assertEqual(period_for(date(2028, 2, 28)).end, date(2028, 2, 28))
        self.assertEqual(period_for(date(2028, 2, 29)).start, date(2028, 2, 29))

    def test_january_period_b_ends_feb_14(self):
        self.assertEqual(period_for(date(2027, 1, 30)).end, date(2027, 2, 14))


class NavigationTest(unittest.TestCase):
    def test_previous_crosses_february(self):
        self.assertEqual(previous(period_for(date(2027, 3, 1))), Period(date(2027, 2, 15), date(2027, 2, 27)))

    def test_previous_and_next_are_inverse_and_contiguous(self):
        p = period_for(date(2026, 1, 1))
        for _ in range(30):
            n = next_period(p)
            self.assertEqual(n.start, p.end + timedelta(days=1))
            self.assertEqual(previous(n), p)
            p = n

    def test_label_and_contains(self):
        p = period_for(date(2026, 11, 20))
        self.assertEqual(p.label, "Nov 15–29")
        self.assertEqual(period_for(date(2026, 11, 30)).label, "Nov 30–Dec 14")
        self.assertTrue(p.contains(date(2026, 11, 29)))
        self.assertFalse(p.contains(date(2026, 11, 30)))


if __name__ == "__main__":
    unittest.main()
