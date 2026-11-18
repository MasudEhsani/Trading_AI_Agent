# Trading AI Agent

A research assistant for a **paper-trading account** (simulated money, for learning),
built on Claude and the Model Context Protocol (MCP). Claude can look at prices,
compute indicators, read the portfolio and **propose** trades with a written thesis.
It **cannot execute** them: every order waits for a human to approve it, and hard risk
limits are enforced in code.

> Simulated money only. Indicators describe the past and do not predict the future;
> nothing here is financial advice.

## How it works

```
 you ──chat / commands──▶ trading_agent.py ──▶ agent_core.Agent ──▶ Claude (Anthropic API)
                               │                     │  tool calls
                               │ /approve, /reject   ▼
                               └────────────▶ trading_server.py  (MCP server)
                                              ├─ market_data.py   prices (simulated or Yahoo)
                                              ├─ indicators.py    SMA, RSI, volatility, drawdown
                                              ├─ risk.py          hard limits on every order
                                              └─ broker.py        paper broker in SQLite (paper.db)
```

**Safety design, in layers:**
1. **Claude only proposes.** `execute_order` and `reject_order` exist on the server, but
   the agent hides them from Claude (`hidden_tools`). Even if Claude guessed a tool name,
   `run_tool` refuses it.
2. **Only you execute.** Orders are executed only by host commands you type
   (`/approve <id>`), which call the server directly, not through Claude.
3. **Risk rules are code, not prompts.** They're checked when an order is proposed and
   again when it's executed, because prices may have moved in between.
4. **Every order has a reason.** A proposal needs a thesis (why + main risk) of at least
   20 characters, and it's stored with the order as a trading journal.
5. **Accounting is all or nothing.** A fill updates cash, position and order status in one
   SQLite transaction: all or nothing.

## Files

| File | Purpose |
|---|---|
| `trading_agent.py` | Entry point: interactive chat with order approval, or `--daily` unattended report |
| `agent_core.py` | Reusable MCP agent host: connects to one MCP server, runs Claude's tool-use loop, hides host-only tools, optional confirmation prompts, prompt caching, token counter |
| `trading_server.py` | MCP server with the tools Claude uses, the host-only tools, and the risk limits as a resource (`rules://risk`) |
| `market_data.py` | Price source: `SimulatedMarket` (default; reproducible random walk per symbol, offline) or `YahooMarket` (real prices via `yfinance`) |
| `indicators.py` | SMA20/50, RSI14, 5- and 20-day change, annualised 20-day volatility, max drawdown |
| `risk.py` | `RiskRules` and `check_order()`: returns the list of violated rules |
| `broker.py` | `PaperBroker`: cash, positions and orders in SQLite (`paper.db`); fills with slippage and a fee |
| `test_trading.py` | pytest suite: indicators, every risk rule, broker accounting, the safety design, end-to-end via MCP |
| `run_daily.bat` | Windows scheduled-task script for the daily run |

## Tools

| Tool | Who | What |
|---|---|---|
| `market_overview` | Claude | One line per watchlist symbol: last price, 5d / 20d change, RSI, trend (SMA20 vs SMA50) |
| `analyze_symbol` | Claude | All indicators for one symbol plus the last 10 closes |
| `get_portfolio` | Claude | Cash, positions (quantity, average price, value, weight, P/L), total value |
| `list_orders` | Claude | Recent orders with status and thesis |
| `propose_order` | Claude | Proposes a buy or sell with a thesis; checked against the risk rules |
| `execute_order` | **you only** | Re-checks the rules and fills at the current price |
| `reject_order` | **you only** | Rejects a proposal |

## Risk rules and account (defaults)

| Setting | Value | Where |
|---|---|---|
| Allowed symbols | AAPL, MSFT, SAP, NVDA, ASML | `risk.py` |
| Max order value | 2,000 EUR | `risk.py` |
| Max position | 20 % of total portfolio value | `risk.py` |
| Min cash | 10 % of total portfolio value | `risk.py` |
| Max orders per day | 3 (proposed + filled; rejected don't count) | `risk.py` |
| Short selling | not allowed | `risk.py` |
| Starting cash | 10,000 EUR | `broker.py` |
| Fee | 1 EUR per trade | `broker.py` |
| Slippage | 0.05 % against you | `broker.py` |

## Setup

Requires Python 3.10+ and an Anthropic API key.

```bash
git clone https://github.com/MasudEhsani/Trading_AI_Agent.git
cd Trading_AI_Agent
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install anthropic mcp pytest                        # + yfinance for real prices
export ANTHROPIC_API_KEY=sk-ant-...                     # Windows: set ANTHROPIC_API_KEY=...
```

`trading_server.py` uses the `MCPServer` API (`mcp.server.mcpserver`) and `agent_core.py`
uses `mcp.Client`, so install a version of the `mcp` package that provides both. The model
is set in `agent_core.py` (`DEFAULT_MODEL = "claude-sonnet-5-5"`).

## Usage

**Interactive:**
```bash
python trading_agent.py
```
Ask in plain language ("How is the market today?", "Analyse NVDA", "Should I rebalance?").
Commands you type yourself:

| Command | Effect |
|---|---|
| `/orders` | List proposed orders |
| `/approve <id>` | Execute a proposal (rules are checked again) |
| `/reject <id>` | Reject a proposal |
| `/portfolio` | Show the portfolio |
| `/tokens` | Tokens used so far in this session |
| `quit` | Exit |

After `/approve` or `/reject`, the decision is added to the conversation, so Claude knows
what happened.

**Daily, unattended:**
```bash
python trading_agent.py --daily
```
Claude reviews the market and portfolio, analyses one or two symbols, proposes at most two
orders, and writes a Markdown report to `reports/YYYY-MM-DD.md`, followed by the pending
proposals. Nothing is executed. Approve the proposals later in interactive mode.

To schedule it:
- **Windows:** edit the path in `run_daily.bat` and add it to Task Scheduler.
- **Linux/macOS:** use cron, for example at 18:00 on weekdays:
  ```
  0 18 * * 1-5 cd ~/Trading_AI_Agent && .venv/bin/python trading_agent.py --daily >> reports/log.txt 2>&1
  ```

**Real prices:**
```bash
pip install yfinance
MARKET_DATA=yahoo python trading_agent.py
```
Yahoo data via `yfinance` is unofficial and can be delayed or rate-limited, which is why
simulated prices are the default. Every tool output states which source is in use.

## Tests

```bash
python -m pytest -q test_trading.py
```

| Test | What it checks |
|---|---|
| `test_indicators` | Indicators against hand-computed values |
| `test_risk_rules` | Each risk rule, one case each |
| `test_broker_buy_and_sell` | Cash, slippage, fees and position after a buy and a sell |
| `test_failed_fill_changes_nothing` | A failed fill leaves cash, positions and order unchanged |
| `test_claude_cannot_execute` | `execute_order` is refused when called through the agent |
| `test_propose_then_execute_via_mcp` | Over MCP: disallowed symbol rejected, proposal → approval → fill, no double execution |

The tests use a temporary database; your `paper.db` is not touched.

## Data and state

- `paper.db` (created on first run) holds the account, positions and the full order
  journal. Delete it to start again with 10,000 EUR.
- `reports/` holds the daily reports and `log.txt`.

Both are created locally and contain your own trading history, so it's worth adding them
to a `.gitignore` before pushing:
```
paper.db
reports/
.venv/
__pycache__/
```

## Extending

- **New symbols:** add them to `allowed_symbols` in `risk.py`. For simulated data, also add
  a start price in `SimulatedMarket.START_PRICES`.
- **Limits:** change the fields of `RiskRules`.
- **Indicators:** add a function to `indicators.py` and to `summary()`. It then appears in
  `analyze_symbol` automatically.
- **Approval channel:** `Agent(confirm=...)` takes any function, so the terminal prompt can
  be replaced by a GUI or a messenger bot.
