import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from fincore.model import Account, Category, Goal, Transaction, WaitItem
from fincore.store import NoDataError, Store, init_data


def txn(**kw):
    base = dict(id="20261114-001", date=date(2026, 11, 14), type="expense", amount=35000,
                category="Groceries", account="Cash", created_at=datetime(2026, 11, 14, 9, 30))
    base.update(kw)
    return Transaction(**base)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "data"
        init_data(self.dir, examples=False)
        self.store = Store.open(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_transactions_round_trip_including_commas_and_quotes(self):
        t = txn(payee='Jollibee, "Ayala"', note="lunch, w/ team", goal="", source="manual")
        tr = txn(id="20261114-002", type="transfer", category="", account="Cash", to_account="Savings",
                 goal="Emergency fund")
        self.store.save_transactions([t, tr])
        self.assertEqual(Store.open(self.dir).transactions(), [t, tr])

    def test_other_files_round_trip(self):
        cats = [Category("Groceries", "expense", 300000, True), Category("Impulse / wants", "expense", None, False, impulse=True),
                Category("Salary", "income", None, False)]
        accts = [Account("Cash", 50000), Account("GCash")]
        goals = [Goal("Emergency fund", None, 1, 100000, 3)]
        wait = [WaitItem("w001", "Headphones", 250000, "Impulse / wants", datetime(2026, 11, 14, 10),
                         datetime(2026, 11, 16, 10))]
        self.store.save_budget(cats)
        self.store.save_accounts(accts)
        self.store.save_goals(goals)
        self.store.save_waitlist(wait)
        self.store.save_meta({"last_review": "2026-11-10"})
        s = Store.open(self.dir)
        self.assertEqual((s.categories(), s.accounts(), s.goals(), s.waitlist(), s.meta()),
                         (cats, accts, goals, wait, {"last_review": "2026-11-10"}))

    def test_new_txn_id_increments_per_date(self):
        self.assertEqual(self.store.new_txn_id(date(2026, 11, 14)), "20261114-001")
        self.store.save_transactions([txn()])
        self.assertEqual(self.store.new_txn_id(date(2026, 11, 14)), "20261114-002")
        self.assertEqual(self.store.new_txn_id(date(2026, 11, 15)), "20261115-001")

    def test_new_wait_id(self):
        self.assertEqual(self.store.new_wait_id(), "w001")

    def test_bom_csv_loads(self):
        self.store.save_transactions([txn()])
        p = self.dir / "transactions.csv"
        p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
        self.assertEqual(len(Store.open(self.dir).transactions()), 1)


class InitTest(unittest.TestCase):
    def test_open_missing_dir_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(NoDataError):
                Store.open(Path(d) / "data")
            (Path(d) / "empty").mkdir()
            with self.assertRaises(NoDataError):
                Store.open(Path(d) / "empty")

    def test_init_copies_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            init_data(Path(d) / "data")
            names = [c.name for c in Store.open(Path(d) / "data").categories()]
            self.assertIn("Impulse / wants", names)

    def test_init_into_non_empty_dir_raises(self):
        with tempfile.TemporaryDirectory() as d:
            init_data(Path(d) / "data")
            with self.assertRaises(FileExistsError):
                init_data(Path(d) / "data")


if __name__ == "__main__":
    unittest.main()
