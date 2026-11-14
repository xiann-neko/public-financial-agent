import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from fincore.model import Account, Installment
from fincore.store import Store, init_data


class DebtModelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "data"
        init_data(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_old_accounts_file_loads_with_defaults(self):
        (self.dir / "accounts.json").write_text(json.dumps({"accounts": [{"name": "Bank", "opening_balance": 0}]}))
        a = Store.open(self.dir).accounts()[0]
        self.assertEqual((a.kind, a.due_day, a.credit_limit, a.rate_monthly, a.payment, a.end, a.due_date),
                         ("cash", None, None, None, None, None, None))

    def test_debt_fields_round_trip(self):
        accts = [Account("Example Card", 1500000, kind="credit_card", due_day=25, credit_limit=5000000,
                         rate_monthly=3.0, payment=500000),
                 Account("Example Loan", 30000000, kind="loan", due_day=5, payment=1200000, end="2028-06"),
                 Account("Owed by Juan", 0, kind="receivable", due_date="2026-12-01")]
        s = Store.open(self.dir)
        s.save_accounts(accts)
        self.assertEqual(Store.open(self.dir).accounts(), accts)

    def test_installments_optional_and_round_trip(self):
        (self.dir / "installments.json").unlink()
        s = Store.open(self.dir)
        self.assertEqual(s.installments(), [])
        inst = [Installment("i001", "Example Card", "Phone", "Shopping (planned)", 2400000, 12, 200000,
                            date(2026, 11, 25))]
        s.save_installments(inst)
        self.assertEqual(Store.open(self.dir).installments(), inst)
        self.assertEqual(s.new_installment_id(), "i002")

    def test_init_leaves_out_example_debts(self):
        self.assertEqual({a.kind for a in Store.open(self.dir).accounts()}, {"cash"})
        self.assertEqual(Store.open(self.dir).installments(), [])

    def test_init_with_examples_includes_debts(self):
        d = Path(self.tmp.name) / "demo"
        init_data(d, examples=True)
        self.assertIn("credit_card", {a.kind for a in Store.open(d).accounts()})
        self.assertEqual(len(Store.open(d).installments()), 1)

    def test_init_creates_installments_file(self):
        self.assertEqual(json.loads((self.dir / "installments.json").read_text()), {"installments": []})


if __name__ == "__main__":
    unittest.main()
