import unittest
from datetime import date

from fincore.cli import run
from fincore.debts import installment_remaining, installment_shares, owed
from fincore.model import Account, Installment
from tests.helpers import TempData, store

CARD = "Example Card"


def ok(*args, today="2026-11-20"):
    code, out, err = run(["--today", today, *args])
    assert code == 0, err
    return out


def acct(name):
    return next(a for a in store().accounts() if a.name == name)


class OwedTest(unittest.TestCase):
    def setUp(self):
        self.ctx = TempData()
        self.ctx.__enter__()
        s = store()
        s.save_accounts(s.accounts() + [
            Account(CARD, 1500000, kind="credit_card", due_day=25),
            Account("Example Loan", 30000000, kind="loan", due_day=5),
            Account("Owed by Juan", 0, kind="receivable")])

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_card(self):
        ok("add", "expense", "1000", "--category", "Groceries", "--account", CARD)
        ok("add", "transfer", "500", "--account", CARD, "--to", "Cash")  # cash advance
        ok("add", "transfer", "5000", "--account", "GCash", "--to", CARD)  # payment
        s = store()
        s.save_installments([
            Installment("i001", CARD, "Phone", "Shopping (planned)", 2400000, 12, 200000, date(2026, 11, 25)),
            Installment("i002", CARD, "Later", "Shopping (planned)", 100000, 2, 50000, date(2027, 1, 25))])
        # only billed shares are in "owed"; unbilled ones are installment_remaining (no double count)
        self.assertEqual(owed(store(), acct(CARD), date(2026, 11, 25)),
                         1500000 + 100000 + 50000 + 200000 - 500000)
        self.assertEqual(owed(store(), acct(CARD), date(2026, 11, 20)), 1500000 + 100000 + 50000 - 500000)

    def test_loan(self):
        ok("add", "transfer", "12000", "--account", "GCash", "--to", "Example Loan")
        self.assertEqual(owed(store(), acct("Example Loan"), date(2026, 11, 20)), 30000000 - 1200000)

    def test_receivable(self):
        ok("add", "transfer", "500", "--account", "Cash", "--to", "Owed by Juan")
        ok("add", "transfer", "200", "--account", "Owed by Juan", "--to", "Cash")
        ok("add", "expense", "100", "--category", "Other", "--account", "Owed by Juan")
        self.assertEqual(owed(store(), acct("Owed by Juan"), date(2026, 11, 20)), 20000)


class NoDoubleCountTest(unittest.TestCase):
    def test_total_owed_after_first_share(self):
        import json
        with TempData():
            ok("account", "add", CARD)
            ok("debt", "set", CARD, "--kind", "card", "--owed", "1000", "--due-day", "25")
            ok("debt", "installment", CARD, "Phone", "24000", "--months", "12", "--category", "Shopping (planned)")
            ok("debt", "pay", CARD, "1000", "--from", "GCash", today="2026-11-26")
            r = json.loads(run(["--today", "2026-11-26", "debt", "list", "--json"])[1])
            d = r["debts"][0]
            self.assertEqual((d["owed"], d["installments_left"], r["total_owed"]), (200000, 2200000, 2400000))


class SharesTest(unittest.TestCase):
    def test_zero_interest_schedule_clamps_day(self):
        i = Installment("i1", "C", "X", "Shopping (planned)", 100000, 3, 33334, date(2027, 1, 31))
        shares = installment_shares(i)
        self.assertEqual([d for d, _, _ in shares], [date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31)])
        self.assertEqual([p for _, p, _ in shares], [33333, 33333, 33334])
        self.assertEqual(sum(p + x for _, p, x in shares), 100000)
        self.assertTrue(all(x == 0 for _, _, x in shares))

    def test_interest_split(self):
        i = Installment("i1", "C", "X", "Shopping (planned)", 1200000, 12, 110000, date(2026, 12, 25))
        shares = installment_shares(i)
        self.assertEqual(shares[0][1:], (100000, 10000))
        self.assertEqual(sum(p for _, p, _ in shares), 1200000)
        self.assertEqual(sum(x for _, _, x in shares), 120000)

    def test_remaining_unbilled(self):
        i = Installment("i1", "C", "X", "Shopping (planned)", 1200000, 12, 100000, date(2026, 11, 25))
        self.assertEqual(installment_remaining([i], "C", date(2026, 11, 24)), 1200000)
        self.assertEqual(installment_remaining([i], "C", date(2026, 11, 25)), 1100000)
        self.assertEqual(installment_remaining([i], "C", date(2027, 12, 1)), 0)


if __name__ == "__main__":
    unittest.main()
