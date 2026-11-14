import unittest

from fincore.cli import run
from tests.helpers import TempData, store


class SetupCommandsTest(unittest.TestCase):
    def setUp(self):
        self.ctx = TempData()
        self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_account_add_and_list(self):
        self.assertEqual(run(["account", "add", "E-wallet", "--opening", "1,000"])[0], 0)
        self.assertIn("E-wallet", [a.name for a in store().accounts()])
        self.assertEqual(next(a for a in store().accounts() if a.name == "E-wallet").opening_balance, 100000)
        self.assertEqual(run(["account", "add", "e-wallet"])[0], 1)
        self.assertIn("E-wallet", run(["account", "list"])[1])

    def test_account_remove_only_if_unused(self):
        run(["add", "expense", "50", "--category", "Other", "--account", "Cash"])
        self.assertEqual(run(["account", "remove", "Cash"])[0], 1)
        self.assertEqual(run(["account", "remove", "GCash"])[0], 0)
        self.assertNotIn("GCash", [a.name for a in store().accounts()])

    def test_category_set_limit_and_essential(self):
        self.assertEqual(run(["category", "set", "Groceries", "--limit", "4,000", "--essential", "no"])[0], 0)
        g = next(c for c in store().categories() if c.name == "Groceries")
        self.assertEqual((g.limit, g.essential), (400000, False))
        run(["category", "set", "Groceries", "--limit", "none"])
        self.assertIsNone(next(c for c in store().categories() if c.name == "Groceries").limit)

    def test_category_add(self):
        self.assertEqual(run(["category", "add", "Pets", "--limit", "1500", "--essential", "yes"])[0], 0)
        p = next(c for c in store().categories() if c.name == "Pets")
        self.assertEqual((p.kind, p.limit, p.essential), ("expense", 150000, True))
        self.assertEqual(run(["category", "add", "Freelance", "--income"])[0], 0)
        self.assertEqual(next(c for c in store().categories() if c.name == "Freelance").kind, "income")
        self.assertEqual(run(["category", "add", "pets"])[0], 1)

    def test_category_list(self):
        out = run(["category", "list"])[1]
        self.assertIn("Impulse / wants", out)
        self.assertIn("essential", out)


if __name__ == "__main__":
    unittest.main()
