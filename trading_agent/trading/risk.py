# risk.py - hard limits, enforced in CODE. Claude cannot talk its way past them.
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RiskRules:
    allowed_symbols: frozenset = field(
        default_factory=lambda: frozenset({"AAPL", "MSFT", "SAP", "NVDA", "ASML"}))
    max_order_eur: float = 2_000.0       # no single order bigger than this
    max_position_pct: float = 20.0       # no symbol more than 20% of total portfolio value
    min_cash_pct: float = 10.0           # always keep 10% cash
    max_orders_per_day: int = 3          # stops over-trading loops


def check_order(rules: RiskRules, *, symbol: str, side: str, qty: int, price: float,
                cash: float, positions: dict[str, int], prices: dict[str, float],
                orders_today: int) -> list[str]:
    """Return a list of rule violations. Empty list = order allowed."""
    problems = []
    value = qty * price
    total = cash + sum(q * prices[s] for s, q in positions.items())

    if symbol not in rules.allowed_symbols:
        problems.append(f"{symbol} is not on the allowed list")
    if side not in ("buy", "sell"):
        problems.append("side must be 'buy' or 'sell'")
    if qty <= 0:
        problems.append("quantity must be positive")
    if value > rules.max_order_eur:
        problems.append(f"order value {value:.2f} EUR exceeds max {rules.max_order_eur:.0f} EUR")
    if orders_today >= rules.max_orders_per_day:
        problems.append(f"already {orders_today} orders today (max {rules.max_orders_per_day})")

    if side == "buy":
        if cash - value < total * rules.min_cash_pct / 100:
            problems.append(f"would leave less than {rules.min_cash_pct:.0f}% cash")
        new_pos_value = (positions.get(symbol, 0) + qty) * price
        if new_pos_value > total * rules.max_position_pct / 100:
            problems.append(f"{symbol} would be {new_pos_value / total * 100:.1f}% of portfolio "
                            f"(max {rules.max_position_pct:.0f}%)")
    if side == "sell" and qty > positions.get(symbol, 0):
        problems.append(f"cannot sell {qty} {symbol}: you hold {positions.get(symbol, 0)} "
                        f"(no short selling)")
    return problems
