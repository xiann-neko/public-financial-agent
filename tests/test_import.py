import json
import tempfile
import unittest
from pathlib import Path

from fincore.cli import run
from fincore.importer import parse_statement
from tests.helpers import TempData, store

FIX = Path(__file__).parent / "fixtures"
MAPPING = {"date_column": "Date", "date_format": "%m/%d/%Y", "payee_column": "Description",
           "debit_column": "Debit", "credit_column": "Credit", "account": "GCash", "skip_rows": 2}


class ParseTest(unittest.TestCase):
    def test_debit_credit_with_bom_and_skip_rows(self):
        rows = parse_statement(FIX / "bank_debit_credit.csv", MAPPING, source="mybank")
        self.assertEqual([(r["date"], r["type"], r["amount"], r["payee"]) for r in rows], [
            ("2026-11-10", "expense", 24500, "GRAB*FOOD, MNL 8891"),
            ("2026-11-15", "income", 1500000, "PAYROLL ACME"),
            ("2026-11-16", "expense", 231055, "MERALCO"),
        ])
        self.assertEqual({r["source"] for r in rows}, {"import:mybank"})
        self.assertEqual({r["account"] for r in rows}, {"GCash"})

    def test_single_amount_column_negative_is_expense(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "s.csv"
            f.write_text("When,What,Amount\n2026-11-10,Jollibee,-199.00\n2026-11-11,Refund,50\n")
            rows = parse_statement(f, {"date_column": "When", "date_format": "%Y-%m-%d", "payee_column": "What",
                                       "amount_column": "Amount", "expense_is_negative": True, "account": "Cash"},
                                   source="x")
        self.assertEqual([(r["type"], r["amount"]) for r in rows], [("expense", 19900), ("income", 5000)])

    def test_bad_date_names_line(self):
        with self.assertRaises(ValueError) as cm:
            parse_statement(FIX / "bad_date.csv", dict(MAPPING, skip_rows=0), source="x")
        self.assertIn("line 3", str(cm.exception))


class ImportCliTest(unittest.TestCase):
    def setUp(self):
        self.ctx = TempData()
        self.dir = self.ctx.__enter__()
        self.importers = Path(tempfile.mkdtemp())
        (self.importers / "mybank.json").write_text(json.dumps(MAPPING))

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def add(self, *args):
        return run(["--today", "2026-11-10", "add", *args])

    def test_add_flags_duplicate_with_exit_3(self):
        self.add("expense", "245", "--category", "Dining & food delivery", "--account", "GCash", "--payee", "Grab food")
        code, out, err = run(["--today", "2026-11-11", "add", "expense", "245", "--category", "Dining & food delivery",
                              "--account", "GCash", "--payee", "GRAB*FOOD MNL 8891"])
        self.assertEqual(code, 3)
        self.assertIn("20261110-001", err)
        self.assertEqual(len(store().transactions()), 1)
        code, _, _ = run(["--today", "2026-11-11", "add", "expense", "245", "--category", "Dining & food delivery",
                          "--account", "GCash", "--payee", "GRAB*FOOD MNL 8891", "--allow-duplicate"])
        self.assertEqual(code, 0)

    def test_import_parse_flags_duplicates_and_writes_nothing(self):
        self.add("expense", "245", "--category", "Dining & food delivery", "--account", "GCash", "--payee", "Grab food")
        code, out, err = run(["import", "parse", str(FIX / "bank_debit_credit.csv"), "--source", "mybank",
                              "--importers", str(self.importers), "--json"])
        self.assertEqual(code, 0, err)
        rows = json.loads(out)
        self.assertEqual([r["n"] for r in rows], [1, 2, 3])
        self.assertEqual(rows[0]["duplicates"], ["20261110-001"])
        self.assertEqual(rows[1]["duplicates"], [])
        self.assertEqual(len(store().transactions()), 1)

    def test_unknown_source(self):
        code, _, err = run(["import", "parse", str(FIX / "bank_debit_credit.csv"), "--source", "nope",
                            "--importers", str(self.importers)])
        self.assertEqual(code, 1)
        self.assertIn("mybank", err)

    def batch(self, rows):
        f = self.dir / "batch.json"
        f.write_text(json.dumps(rows))
        return run(["--today", "2026-11-20", "add-batch", str(f)])

    def rows(self):
        return [
            {"date": "2026-11-10", "type": "expense", "amount": 24500, "payee": "Grab", "account": "GCash",
             "category": "Dining & food delivery", "source": "import:mybank"},
            {"date": "2026-11-15", "type": "income", "amount": 1500000, "payee": "Payroll", "account": "GCash",
             "category": "Salary", "source": "import:mybank"},
            {"date": "2026-11-16", "type": "expense", "amount": "2,310.55", "payee": "Meralco", "account": "GCash",
             "category": "Bills & utilities", "source": "import:mybank"},
        ]

    def test_add_batch_all_or_nothing(self):
        rows = self.rows()
        rows[1]["category"] = "Nope"
        code, _, err = self.batch(rows)
        self.assertEqual(code, 1)
        self.assertIn("row 2", err)
        self.assertEqual(store().transactions(), [])
        code, out, err = self.batch(self.rows())
        self.assertEqual(code, 0, err)
        txns = store().transactions()
        self.assertEqual([t.amount for t in txns], [24500, 1500000, 231055])
        self.assertEqual(txns[0].source, "import:mybank")

    def test_add_batch_duplicate_needs_allow(self):
        self.add("expense", "245", "--category", "Dining & food delivery", "--account", "GCash", "--payee", "Grab food")
        code, _, err = self.batch(self.rows())
        self.assertEqual(code, 3)
        self.assertEqual(len(store().transactions()), 1)
        rows = self.rows()
        rows[0]["allow_duplicate"] = True
        self.assertEqual(self.batch(rows)[0], 0)
        self.assertEqual(len(store().transactions()), 4)


if __name__ == "__main__":
    unittest.main()
