import json
import os
import unittest
from unittest import mock

from fincore.cli import run
from tests.helpers import TempData


class BeforeInitTest(unittest.TestCase):
    def test_commands_ask_for_init(self):
        with TempData(init=False):
            code, out, err = run(["list"])
        self.assertEqual(code, 1)
        self.assertIn("run ./fin init", err)
        self.assertNotIn("Traceback", err)

    def test_init_creates_data(self):
        with TempData(init=False) as d:
            code, out, err = run(["init"])
            self.assertEqual(code, 0, err)
            self.assertTrue((d / "budget.json").exists())


class CoreCommandsTest(unittest.TestCase):
    def setUp(self):
        self.ctx = TempData()
        self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def add(self, *args):
        return run(["--today", "2026-11-14", "add", *args])

    def ids(self):
        return [t["id"] for t in json.loads(run(["list", "--json"])[1])]

    def test_add_expense(self):
        code, out, err = self.add("expense", "350", "--category", "Groceries", "--account", "Cash", "--payee", "Puregold")
        self.assertEqual(code, 0, err)
        self.assertIn("₱350.00", out)
        self.assertIn("20261114-001", out)

    def test_unknown_category_lists_valid_ones(self):
        code, out, err = self.add("expense", "350", "--category", "Food", "--account", "Cash")
        self.assertEqual(code, 1)
        self.assertIn("Groceries", err)

    def test_unknown_account(self):
        code, _, err = self.add("expense", "350", "--category", "Groceries", "--account", "Wallet")
        self.assertEqual(code, 1)
        self.assertIn("Cash", err)

    def test_bad_amount(self):
        code, _, err = self.add("expense", "abc", "--category", "Groceries", "--account", "Cash")
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)

    def test_transfer(self):
        code, _, err = self.add("transfer", "1000", "--account", "Cash", "--to", "Savings")
        self.assertEqual(code, 0, err)
        t = json.loads(run(["list", "--json"])[1])[0]
        self.assertEqual((t["category"], t["to_account"], t["type"]), ("", "Savings", "transfer"))

    def test_transfer_requires_to(self):
        self.assertEqual(self.add("transfer", "1000", "--account", "Cash")[0], 1)

    def test_expense_requires_category(self):
        self.assertEqual(self.add("expense", "100", "--account", "Cash")[0], 1)

    def test_income_needs_income_category(self):
        self.assertEqual(self.add("income", "100", "--category", "Groceries", "--account", "Cash")[0], 1)
        self.assertEqual(self.add("income", "100", "--category", "Salary", "--account", "Cash")[0], 0)

    def test_edit_and_delete(self):
        self.add("expense", "350", "--category", "Groceries", "--account", "Cash")
        tid = self.ids()[0]
        self.assertEqual(run(["edit", tid, "--amount", "400"])[0], 0)
        self.assertEqual(json.loads(run(["list", "--json"])[1])[0]["amount"], 40000)
        self.assertEqual(run(["delete", tid])[0], 0)
        self.assertEqual(self.ids(), [])
        self.assertEqual(run(["delete", "nope"])[0], 1)

    def test_list_filters(self):
        self.add("expense", "350", "--category", "Groceries", "--account", "Cash", "--payee", "Puregold")
        self.add("expense", "120", "--category", "Transport", "--account", "Cash", "--payee", "Grab", "--date", "2026-11-01")
        out = json.loads(run(["list", "--json", "--search", "pureg"])[1])
        self.assertEqual([t["payee"] for t in out], ["Puregold"])
        out = json.loads(run(["list", "--json", "--from", "2026-11-10"])[1])
        self.assertEqual(len(out), 1)
        out = json.loads(run(["list", "--json", "--category", "Transport"])[1])
        self.assertEqual(len(out), 1)
        code, text, _ = run(["list"])
        self.assertIn("₱120.00", text)

    def test_usage_errors_exit_1_not_guard_code(self):
        self.assertEqual(run(["add", "expense"])[0], 1)

    def test_guard_refuses_when_public(self):
        os.environ.pop("FIN_SKIP_GUARD")
        with mock.patch("fincore.guard.is_protected", return_value=True), \
             mock.patch("fincore.guard.repo_visibility", return_value="public"):
            code, _, err = self.add("expense", "350", "--category", "Groceries", "--account", "Cash")
        os.environ["FIN_SKIP_GUARD"] = "1"
        self.assertEqual(code, 2)
        self.assertIn("public", err)
        self.assertEqual(self.ids(), [])


if __name__ == "__main__":
    unittest.main()
