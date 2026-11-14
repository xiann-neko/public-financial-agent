"""Plain data records. All money values are integer centavos."""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Optional

TxnType = Literal["income", "expense", "transfer"]


@dataclass
class Transaction:
    id: str
    date: date
    type: TxnType
    amount: int  # always > 0; direction comes from type
    category: str
    account: str
    to_account: str = ""
    payee: str = ""
    note: str = ""
    goal: str = ""  # "NAME" = contribution, "-NAME" = withdrawal (transfers only)
    source: str = "manual"
    created_at: Optional[datetime] = None


@dataclass
class Category:
    name: str
    kind: Literal["expense", "income"]
    limit: Optional[int]  # per pay period; None = no limit
    essential: bool
    impulse: bool = False
    bill_day: Optional[int] = None  # fixed bill: day of month it's due
    bill_every: int = 1  # months between bills (3 = quarterly)
    bill_from: Optional[str] = None  # YYYY-MM-DD of a due date, anchors bill_every
    bill_amount: Optional[int] = None  # expected bill; None = use the limit
    bill_via: str = "direct"  # direct | card (auto-charged; the card bill covers it) | owed (offset against someone's debt)


AccountKind = Literal["cash", "credit_card", "loan", "receivable"]
DEBT_KINDS = ("credit_card", "loan")


@dataclass
class Account:
    name: str
    opening_balance: int = 0  # for cards/loans/receivables: amount owed at setup
    kind: AccountKind = "cash"
    due_day: Optional[int] = None  # cards/loans: day of month payment is due
    credit_limit: Optional[int] = None
    rate_monthly: Optional[float] = None  # % per month, e.g. 3.0
    payment: Optional[int] = None  # planned monthly payment
    end: Optional[str] = None  # loans: last payment month, YYYY-MM
    due_date: Optional[str] = None  # receivables: YYYY-MM-DD
    tracked_since: Optional[str] = None  # YYYY-MM-DD the account became a tracked debt
    role: str = "spending"  # cash accounts: spending | savings | hidden (bookkeeping only)

    @property
    def is_debt(self) -> bool:
        return self.kind in DEBT_KINDS


@dataclass
class Installment:
    id: str
    card: str
    item: str
    category: str
    total: int
    months: int
    monthly: int
    first_billing: date
    billing_day: Optional[int] = None  # day of month shares are billed (clamped per month)


@dataclass
class Goal:
    name: str
    target: Optional[int]  # None = compute from essential spending
    priority: int
    planned_per_period: int
    target_months: int = 3


@dataclass
class WaitItem:
    id: str
    item: str
    price: int
    category: str
    added_at: datetime
    due_at: datetime
    outcome: Literal["pending", "bought", "dropped"] = "pending"
    resolved_at: Optional[datetime] = None
    txn_id: str = ""
