import unittest
from datetime import date

from fincore.dedupe import find_duplicates, normalize_payee
from fincore.model import Transaction


def t(**kw):
    base = dict(id="20261110-001", date=date(2026, 11, 10), type="expense", amount=24500,
                category="Dining & food delivery", account="GCash", payee="Grab food")
    base.update(kw)
    return Transaction(**base)


class DedupeTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_payee("GRAB*FOOD, MNL 8891"), "grab food mnl")

    def test_same_purchase_from_screenshot_and_statement(self):
        existing = [t()]
        self.assertEqual(find_duplicates(existing, "expense", 24500, date(2026, 11, 11), "GRAB*FOOD MNL 8891"), existing)

    def test_too_far_apart(self):
        self.assertEqual(find_duplicates([t()], "expense", 24500, date(2026, 11, 13), "Grab food"), [])

    def test_different_amount_or_type(self):
        self.assertEqual(find_duplicates([t()], "expense", 24600, date(2026, 11, 10), "Grab food"), [])
        self.assertEqual(find_duplicates([t()], "income", 24500, date(2026, 11, 10), "Grab food"), [])

    def test_empty_payee_matches(self):
        self.assertEqual(len(find_duplicates([t(payee="")], "expense", 24500, date(2026, 11, 12), "Jollibee")), 1)

    def test_different_merchant_same_amount(self):
        self.assertEqual(find_duplicates([t()], "expense", 24500, date(2026, 11, 10), "Mercury Drug"), [])


if __name__ == "__main__":
    unittest.main()
