"""Money as integer centavos. Never floats."""
import re
from decimal import Decimal

_PLAIN = re.compile(r"^(\d{1,3}(,\d{3})+|\d+)(\.\d{1,2})?$")
_PREFIX = re.compile(r"^(php|₱|p)\s*", re.IGNORECASE)


def parse_amount(text: str) -> int:
    """Parse a positive peso amount typed by a person into centavos."""
    s = (text or "").strip()
    s = _PREFIX.sub("", s).strip()
    if not _PLAIN.match(s):
        raise ValueError(f"Not a valid peso amount: {text!r} (examples: 350, ₱1,299, 1299.50)")
    centavos = int(Decimal(s.replace(",", "")) * 100)
    if centavos <= 0:
        raise ValueError(f"Amount must be more than ₱0: {text!r}")
    return centavos


def format_amount(centavos: int) -> str:
    sign = "-" if centavos < 0 else ""
    pesos, cents = divmod(abs(centavos), 100)
    return f"{sign}₱{pesos:,}.{cents:02d}"
