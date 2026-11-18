# test_trading.py - run: python -m pytest -q test_trading.py
import asyncio
import tempfile
from pathlib import Path

import pytest
from mcp import Client

import indicators as ind
import trading_server
from broker import PaperBroker
from risk import RiskRules, check_order


@pytest.fixture()
def fresh_broker(monkeypatch):
    b = PaperBroker(Path(tempfile.mkdtemp()) / "test.db")
    monkeypatch.setattr(trading_server, "broker", b)
    return b


# ---------- indicators: known inputs, known outputs ----------
def test_indicators():
    assert ind.sma([1, 2, 3, 4], 2) == 3.5
    assert ind.sma([1, 2], 5) is None
    assert ind.rsi(list(range(1, 20))) == 100.0          # only gains
    assert ind.max_drawdown([100, 120, 90, 130]) == -25.0
    assert ind.pct_change([100, 110], 1) == 10.0


# ---------- every risk rule has a test ----------
BASE = dict(symbol="SAP", side="buy", qty=1, price=100.0, cash=10_000.0,
            positions={}, prices={"SAP": 100.0}, orders_today=0)


@pytest.mark.parametrize("change, expected", [
    ({}, None),
    ({"symbol": "TSLA", "prices": {"SAP": 100.0, "TSLA": 100.0}}, "not on the allowed list"),
    ({"qty": 21}, "exceeds max"),
    ({"orders_today": 3}, "orders today"),
    ({"qty": 19, "cash": 2_500.0, "positions": {"SAP": 75}}, "less than 10% cash"),
    ({"qty": 19, "positions": {"SAP": 5}}, "of portfolio"),
    ({"side": "sell", "qty": 2, "positions": {"SAP": 1}}, "no short selling"),
])
def test_risk_rules(change, expected):
    problems = check_order(RiskRules(), **{**BASE, **change})
    if expected is None:
        assert problems == []
    else:
        assert any(expected in p for p in problems), problems


# ---------- broker accounting ----------
def test_broker_buy_and_sell(fresh_broker):
    b = fresh_broker
    b.fill(b.propose("SAP", "buy", 10, "t"), 100.0)       # 10 x 100.05 + 1 fee
    assert b.cash() == 10_000 - 1000.5 - 1
    sold = b.fill(b.propose("SAP", "sell", 4, "t"), 110.0)  # 110 minus 0.05% slippage
    assert sold["fill_price"] == 109.95
    assert b.positions()["SAP"]["qty"] == 6
    assert b.cash() == round(10_000 - 1001.5 + 4 * 109.95 - 1, 2)


def test_failed_fill_changes_nothing(fresh_broker):
    b = fresh_broker
    oid = b.propose("SAP", "sell", 1, "t")             # we hold nothing
    with pytest.raises(ValueError):
        b.fill(oid, 100.0)
    assert b.cash() == 10_000 and b.positions() == {} and b.get(oid)["status"] == "proposed"


# ---------- the safety design ----------
def test_claude_cannot_execute(fresh_broker):
    """execute_order exists on the server, but the agent must hide it from Claude."""
    from agent_core import Agent
    assert "execute_order" in trading_server.HOST_ONLY_TOOLS
    agent = Agent.__new__(Agent)          # no API key needed for this check
    agent.hidden_tools, agent.needs_confirmation = trading_server.HOST_ONLY_TOOLS, set()
    text, is_error = asyncio.run(agent.run_tool("execute_order", {"order_id": 1}))
    assert is_error and "not available" in text


def test_propose_then_execute_via_mcp(fresh_broker):
    async def run():
        async with Client(trading_server.mcp) as c:
            r = await c.call_tool("propose_order", {"symbol": "TSLA", "side": "buy", "qty": 1,
                                                    "thesis": "a long enough thesis text"})
            assert r.is_error                                  # not allowed
            r = await c.call_tool("propose_order", {"symbol": "SAP", "side": "buy", "qty": 2,
                                                    "thesis": "a long enough thesis text"})
            assert "proposed" in r.content[0].text and fresh_broker.positions() == {}
            r = await c.call_tool("execute_order", {"order_id": 1})   # the human approves
            assert "Filled #1" in r.content[0].text
            r = await c.call_tool("execute_order", {"order_id": 1})   # twice? no.
            assert r.is_error and "already filled" in r.content[0].text
    asyncio.run(run())
