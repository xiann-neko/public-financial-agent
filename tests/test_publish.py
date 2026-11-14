import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("publish", ROOT / "scripts" / "publish.py")
publish_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish_mod)


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class PublishTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src, self.dest = root / "src", root / "dest"
        for rel in ["fincore/x.py", "data/transactions.csv", "data.example/transactions.csv", "data/.staging/i.json"]:
            (self.src / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.src / rel).write_text("x\n")
        git(self.src, "init", "-q")
        git(self.src, "add", "-f", ".")
        self.dest.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_copies_code_and_examples_not_data(self):
        copied = publish_mod.publish(self.src, self.dest)
        self.assertEqual(sorted(copied), ["data.example/transactions.csv", "fincore/x.py"])
        self.assertFalse((self.dest / "data" / "transactions.csv").exists())
        self.assertTrue((self.dest / "fincore" / "x.py").exists())

    def test_refuses_if_destination_has_real_data(self):
        (self.dest / "data").mkdir()
        (self.dest / "data" / "transactions.csv").write_text("secret\n")
        with self.assertRaises(publish_mod.PublishError):
            publish_mod.publish(self.src, self.dest)

    def test_gitkeep_in_destination_is_fine(self):
        (self.dest / "data").mkdir()
        (self.dest / "data" / ".gitkeep").write_text("")
        publish_mod.publish(self.src, self.dest)


TXN_HEADER = "id,date,type,amount,category,account,to_account,payee,note,goal,source,created_at\n"


class LeakGuardTest(unittest.TestCase):
    """publish() refuses to copy files that mention the owner's real ledger."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src, self.dest = root / "src", root / "dest"
        self.dest.mkdir()
        files = {
            "data/transactions.csv": TXN_HEADER
            + "20261101-001,2026-11-01,expense,48550,Dining,Cash,,Noodle Palace,lunch w/ Sammy,,manual,\n",
            "data/accounts.json": '{"accounts": [{"name": "Cash"}, {"name": "Owed by Kristoff", "kind": "receivable"},'
                                  ' {"name": "Interest & fees"}, {"name": "x", "opening_balance": 150000}]}',
            "data/budget.json": '{"categories": [{"name": "Hobby fund", "bill_amount": 765432}]}',
            "data.example/accounts.json": '{"accounts": [{"name": "Cash"}, {"name": "Example Card"}]}',
            "fincore/clean.py": "x = 'Example Card'  # paid 1,000.00 for lunch\n",
        }
        for rel, text in files.items():
            (self.src / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.src / rel).write_text(text)
        git(self.src, "init", "-q")
        git(self.src, "add", "-f", ".")

    def tearDown(self):
        self.tmp.cleanup()

    def add_file(self, rel, text):
        (self.src / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.src / rel).write_text(text)
        git(self.src, "add", "-f", rel)

    def test_terms_come_from_real_data_minus_examples_and_common_words(self):
        terms = publish_mod.personal_terms(self.src / "data", self.src / "data.example")
        for t in ["Noodle Palace", "Palace", "Kristoff", "Owed by Kristoff", "Hobby fund",
                  "765432", "7,654.32", "7654.32"]:
            self.assertIn(t, terms)
        for t in ["Cash", "lunch", "Dining", "Interest & fees", "150000"]:
            self.assertNotIn(t, terms)

    def test_clean_code_publishes(self):
        self.assertIn("fincore/clean.py", publish_mod.publish(self.src, self.dest))

    def test_refuses_a_real_payee(self):
        self.add_file("tests/test_x.py", "ok('add', 'expense', '1', '--payee', 'Palace')\n")
        with self.assertRaises(publish_mod.PublishError) as cm:
            publish_mod.publish(self.src, self.dest)
        self.assertIn("tests/test_x.py:1", str(cm.exception))
        self.assertIn("Palace", str(cm.exception))
        self.assertFalse((self.dest / "tests" / "test_x.py").exists())

    def test_refuses_a_real_amount(self):
        self.add_file("tests/test_y.py", "ok('--bill-amount', '7,654.32')\n")
        with self.assertRaises(publish_mod.PublishError):
            publish_mod.publish(self.src, self.dest)

    def test_whole_words_only(self):
        self.add_file("fincore/ok.py", "Palaces = 1  # 97654.325 isn't the amount\n")
        publish_mod.publish(self.src, self.dest)

    def test_allow_overrides(self):
        self.add_file("tests/test_x.py", "'Hobby fund'\n")
        publish_mod.publish(self.src, self.dest, allow={"Hobby fund"})

    def test_no_data_dir_skips_guard(self):
        import shutil
        shutil.rmtree(self.src / "data")
        self.add_file("tests/test_x.py", "'Palace'\n")
        publish_mod.publish(self.src, self.dest)


if __name__ == "__main__":
    unittest.main()
