# trading_server.py - Milestone 5: MCP server for research + paper trading.
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

import indicators as ind
from broker import PaperBroker
from market_data import get_market
from risk import RiskRules, check_order

market = get_market()
broker = PaperBroker()
RULES = RiskRules()
WATCHLIST = sorted(RULES.allowed_symbols)

# Tools only the HUMAN may call (through host commands). The host hides them from Claude.
HOST_ONLY_TOOLS = {"execute_order", "reject_order"}

mcp = MCPServer("paper-trading", instructions=(
    "Paper trading with simulated money for learning. You can research and PROPOSE orders; "
    "only the human can execute them. All amounts in EUR."))


def closes(symbol: str, days: int = 120) -> list[float]:
    try:
        return [b["close"] for b in market.history(symbol, days)]
    except KeyError as e:
        raise ToolError(e.args[0])
    except Exception as e:
        raise ToolError(f"Market data unavailable: {e}")


def current_prices() -> dict[str, float]:
    return {s: closes(s, 1)[-1] for s in WATCHLIST}


def portfolio_state() -> dict:
    prices = current_prices()
    pos = broker.positions()
    rows, invested = [], 0.0
    for s, p in pos.items():
        value = p["qty"] * prices[s]
        invested += value
        rows.append({"symbol": s, "qty": p["qty"], "avg_price": round(p["avg_price"], 2),
                     "price": prices[s], "value": round(value, 2),
                     "pnl_pct": round((prices[s] / p["avg_price"] - 1) * 100, 2)})
    total = broker.cash() + invested
    return {"cash": round(broker.cash(), 2), "total": round(total, 2), "positions": rows,
            "prices": prices, "qty": {s: p["qty"] for s, p in pos.items()}}


# ---------------- research (read-only) ----------------
@mcp.tool()
def market_overview() -> str:
    """One line per watchlist symbol: last price, 5-day and 20-day change, RSI, trend."""
    lines = [f"[{market.label}]", "symbol | last | 5d % | 20d % | rsi14 | trend"]
    for s in WATCHLIST:
        x = ind.summary(closes(s))
        trend = "up" if x["sma20"] > x["sma50"] else "down"
        lines.append(f"{s} | {x['last']} | {x['change_5d_pct']} | {x['change_20d_pct']} | "
                     f"{x['rsi14']} | {trend} (sma20 {x['sma20']} vs sma50 {x['sma50']})")
    return "\n".join(lines)


@mcp.tool()
def analyze_symbol(symbol: str) -> str:
    """Indicators for one symbol (SMA20/50, RSI14, changes, volatility, max drawdown over
    ~6 months) plus the last 10 closing prices."""
    c = closes(symbol.upper())
    x = ind.summary(c)
    body = "\n".join(f"{k}: {v}" for k, v in x.items())
    return f"[{market.label}]\n{symbol.upper()}\n{body}\nlast 10 closes: {c[-10:]}"


@mcp.tool()
def get_portfolio() -> str:
    """Cash, positions (qty, average buy price, current value, profit/loss %), total value."""
    p = portfolio_state()
    lines = [f"cash: {p['cash']} EUR | total value: {p['total']} EUR"]
    for r in p["positions"]:
        weight = r["value"] / p["total"] * 100
        lines.append(f"{r['symbol']}: {r['qty']} @ avg {r['avg_price']} | now {r['price']} | "
                     f"value {r['value']} ({weight:.1f}%) | P/L {r['pnl_pct']}%")
    if not p["positions"]:
        lines.append("no positions")
    return "\n".join(lines)


@mcp.tool()
def list_orders(status: str | None = None) -> str:
    """Recent orders with their thesis. status: proposed, filled or rejected (optional)."""
    rows = broker.orders(status)
    if not rows:
        return "No orders."
    return "\n".join(f"#{o['id']} {o['created'][:10]} {o['side']} {o['qty']} {o['symbol']} "
                     f"[{o['status']}{' @ ' + str(o['fill_price']) if o['fill_price'] else ''}]"
                     f" - {o['thesis']}" for o in rows)


# ---------------- proposing (write, but harmless) ----------------
@mcp.tool()
def propose_order(symbol: str, side: str, qty: int, thesis: str) -> str:
    """Propose a paper trade for the human to approve. side: 'buy' or 'sell'. qty: whole shares.
    thesis: 2-3 sentences WHY, citing the indicators, plus the main risk.
    The order is checked against the risk rules; violations are returned as an error."""
    symbol, side = symbol.upper(), side.lower()
    if len(thesis.strip()) < 20:
        raise ToolError("Write a real thesis (why + main risk) before proposing.")
    p = portfolio_state()
    if symbol not in p["prices"]:
        raise ToolError(f"{symbol} is not on the allowed list: {', '.join(WATCHLIST)}")
    problems = check_order(RULES, symbol=symbol, side=side, qty=qty, price=p["prices"][symbol],
                           cash=p["cash"], positions=p["qty"], prices=p["prices"],
                           orders_today=broker.orders_today())
    if problems:
        raise ToolError("Rejected by risk rules: " + "; ".join(problems))
    oid = broker.propose(symbol, side, qty, thesis.strip())
    value = qty * p["prices"][symbol]
    return (f"Order #{oid} proposed: {side} {qty} {symbol} (~{value:.2f} EUR). "
            f"Waiting for human approval.")


# ---------------- HOST-ONLY: execution ----------------
@mcp.tool()
def execute_order(order_id: int) -> str:
    """HOST ONLY. Execute a proposed order after human approval."""
    try:
        o = broker.get(order_id)
    except KeyError as e:
        raise ToolError(e.args[0])
    if o["status"] != "proposed":
        raise ToolError(f"Order #{order_id} is already {o['status']}.")
    p = portfolio_state()
    # check the rules AGAIN: prices and the portfolio may have changed since the proposal
    problems = check_order(RULES, symbol=o["symbol"], side=o["side"], qty=o["qty"],
                           price=p["prices"][o["symbol"]], cash=p["cash"],
                           positions=p["qty"], prices=p["prices"],
                           orders_today=broker.orders_today() - 1)  # don't count itself
    if problems:
        raise ToolError("Cannot execute, risk rules now fail: " + "; ".join(problems))
    try:
        f = broker.fill(order_id, p["prices"][o["symbol"]])
    except (ValueError, KeyError) as e:
        raise ToolError(str(e))
    return f"Filled #{order_id}: {f['side']} {f['qty']} {f['symbol']} @ {f['fill_price']}"


@mcp.tool()
def reject_order(order_id: int) -> str:
    """HOST ONLY. Reject a proposed order."""
    try:
        status = broker.get(order_id)["status"]
    except KeyError as e:
        raise ToolError(e.args[0])
    if status != "proposed":
        raise ToolError("Only proposed orders can be rejected.")
    broker.reject(order_id)
    return f"Order #{order_id} rejected."


@mcp.resource("rules://risk", description="The hard risk limits enforced by the server")
def risk_rules() -> str:
    return str(RULES)


if __name__ == "__main__":
    mcp.run(transport="stdio")
