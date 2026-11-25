# generate_sample_data.py - fills data/sample/ with example output, WITHOUT Claude or an API key.
#
# It replays ~6 months of trading days through the project's real code: market_data,
# indicators, risk rules and the paper broker. The decisions Claude would normally
# propose are made by a simple rule-based stand-in (trend following + stop-loss), and
# every proposal that passes the risk rules is approved, as if you had typed /approve.
# On the last day the proposals are left pending, exactly like the --daily mode.
#
#   python scripts/generate_sample_data.py          (from the repository folder)
#
# Prices are SIMULATED. The results say nothing about real markets.
import csv
import json
import math
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# importing the server creates a broker: point it at a temp folder, not data/live
os.environ["TRADING_DATA_DIR"] = tempfile.mkdtemp(prefix="sample_gen_")

from trading_agent.config import SAMPLE_DIR  # noqa: E402
from trading_agent.market import indicators as ind  # noqa: E402
from trading_agent.market.market_data import SimulatedMarket  # noqa: E402
from trading_agent.server import trading_server as server  # noqa: E402
from trading_agent.trading.broker import FEE_EUR, START_CASH, PaperBroker  # noqa: E402
from trading_agent.trading.risk import RiskRules, check_order  # noqa: E402

END = date(2026, 11, 20)        # last replayed day (a Friday); fixed, so output is reproducible
REPLAY_DAYS = 130               # ~6 months of trading days
BUY_BUDGET_EUR = 1_800.0        # stand-in's order size (the risk limit is 2,000)
STOP_LOSS_PCT = -8.0
ADD_TO_WINNER_PCT = 5.0         # stand-in wants to buy more of a position up 5%+ ...
ADD_EUR = 1_000.0               # ... which the 20% position limit usually blocks
RULES = RiskRules()
SYMBOLS = sorted(RULES.allowed_symbols)


class FixedEndMarket(SimulatedMarket):
    """The simulated market, but 'today' is a chosen day instead of the real date."""

    def __init__(self, end: date):
        self.end = end

    def history(self, symbol, days=120, end=None):
        return super().history(symbol, days, end or self.end)


# ---------------------------------------------------------------- the replay
def replay(broker: PaperBroker):
    sim = SimulatedMarket()
    calendar = [date.fromisoformat(b["date"]) for b in sim.history("SAP", REPLAY_DAYS, END)]
    full = {s: sim.history(s, REPLAY_DAYS + 80, END) for s in SYMBOLS}  # + warm-up for SMA50
    index = {s: {b["date"]: i for i, b in enumerate(full[s])} for s in SYMBOLS}

    def closes_until(sym, day):
        i = index[sym][day.isoformat()]
        return [b["close"] for b in full[sym][: i + 1]]

    first_prices = {s: closes_until(s, calendar[0])[-1] for s in SYMBOLS}
    bench_qty = {s: START_CASH / len(SYMBOLS) / first_prices[s] for s in SYMBOLS}

    equity, indicator_rows, rejections = [], [], []
    for day in calendar:
        last_day = day == END
        at = datetime.combine(day, time(17, 30))
        stats = {s: ind.summary(closes_until(s, day)) for s in SYMBOLS}
        prices = {s: stats[s]["last"] for s in SYMBOLS}
        for s in SYMBOLS:
            indicator_rows.append({"date": day.isoformat(), "symbol": s, **stats[s]})

        # --- what the stand-in "Claude" proposes today: sells first, then buys
        proposals = []
        for s, pos in broker.positions().items():
            x, pnl = stats[s], (prices[s] / pos["avg_price"] - 1) * 100
            if pnl <= STOP_LOSS_PCT:
                proposals.append((s, "sell", pos["qty"],
                                  f"Stop-loss: {s} is {pnl:.1f}% below the average buy price "
                                  f"({pos['avg_price']:.2f}). Main risk: selling just before "
                                  f"a rebound."))
            elif x["sma20"] < x["sma50"]:
                proposals.append((s, "sell", pos["qty"],
                                  f"Trend turned down: SMA20 {x['sma20']} below SMA50 "
                                  f"{x['sma50']}, 20-day change {x['change_20d_pct']}%. "
                                  f"Main risk: a false signal in a sideways market."))
        held = broker.positions()
        for s, pos in held.items():   # "add to winners": a common instinct the rules must stop
            x, pnl = stats[s], (prices[s] / pos["avg_price"] - 1) * 100
            if pnl >= ADD_TO_WINNER_PCT and x["sma20"] > x["sma50"] and x["rsi14"] < 70:
                proposals.append((s, "buy", int(ADD_EUR // prices[s]),
                                  f"Add to winner: {s} is up {pnl:.1f}% and still trending up "
                                  f"(SMA20 {x['sma20']} > SMA50 {x['sma50']}). Main risk: "
                                  f"buying high, bigger loss if the trend breaks."))
        candidates = [s for s in SYMBOLS if s not in held
                      and stats[s]["sma20"] > stats[s]["sma50"]
                      and stats[s]["rsi14"] < 70 and stats[s]["change_20d_pct"] > 0]
        for s in sorted(candidates, key=lambda c: -stats[c]["change_20d_pct"]):
            x = stats[s]
            qty = int(BUY_BUDGET_EUR // prices[s])
            proposals.append((s, "buy", qty,
                              f"Uptrend: SMA20 {x['sma20']} above SMA50 {x['sma50']}, RSI "
                              f"{x['rsi14']} (not overbought), {x['change_20d_pct']:+}% over "
                              f"20 days. Main risk: reversal; volatility "
                              f"{x['volatility_20d_pct']}% a year."))

        # --- each proposal goes through the real risk rules, then the "human" approves
        for s, side, qty, thesis in proposals:
            qtys = {sym: p["qty"] for sym, p in broker.positions().items()}
            problems = check_order(RULES, symbol=s, side=side, qty=qty, price=prices[s],
                                   cash=broker.cash(), positions=qtys, prices=prices,
                                   orders_today=broker.orders_today(day))
            if problems:
                rejections.append({"date": day.isoformat(), "symbol": s, "side": side,
                                   "qty": qty, "value_eur": round(qty * prices[s], 2),
                                   "reasons": "; ".join(problems)})
                continue
            oid = broker.propose(s, side, qty, thesis, at=at)
            if not last_day:        # on the last day proposals stay pending, like --daily
                broker.fill(oid, prices[s], at=at.replace(minute=35))

        # --- end-of-day valuation
        pos = broker.positions()
        invested = sum(p["qty"] * prices[s] for s, p in pos.items())
        total = broker.cash() + invested
        bench = sum(q * prices[s] for s, q in bench_qty.items())
        row = {"date": day.isoformat(), "cash": round(broker.cash(), 2),
               "invested": round(invested, 2), "total": round(total, 2),
               "benchmark_total": round(bench, 2), "positions": len(pos)}
        for s in SYMBOLS:
            value = pos[s]["qty"] * prices[s] if s in pos else 0.0
            row[f"weight_{s}"] = round(value / total * 100, 2)
        equity.append(row)
    return calendar, equity, indicator_rows, rejections


# ---------------------------------------------------------------- writers
def write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def add_drawdown(equity):
    peak = bpeak = 0.0
    for r in equity:
        peak, bpeak = max(peak, r["total"]), max(bpeak, r["benchmark_total"])
        r["drawdown_pct"] = round((r["total"] / peak - 1) * 100, 2)
        r["benchmark_drawdown_pct"] = round((r["benchmark_total"] / bpeak - 1) * 100, 2)


def round_trips(orders):
    """Pair each sell with the position it closed: realised P/L per completed trade."""
    open_cost, trips = {}, []
    for o in sorted(orders, key=lambda o: o["id"]):
        if o["status"] != "filled":
            continue
        s = o["symbol"]
        if o["side"] == "buy":
            q, c = open_cost.get(s, (0, 0.0))
            open_cost[s] = (q + o["qty"], c + o["qty"] * o["fill_price"] + FEE_EUR)
        else:
            q, c = open_cost.pop(s)
            proceeds = o["qty"] * o["fill_price"] - FEE_EUR
            trips.append({"symbol": s, "closed": o["decided"][:10], "qty": o["qty"],
                          "cost_eur": round(c, 2), "proceeds_eur": round(proceeds, 2),
                          "pnl_eur": round(proceeds - c, 2),
                          "pnl_pct": round((proceeds / c - 1) * 100, 2),
                          "exit_reason": o["thesis"].split(":")[0]})
    return trips


def charts(out: Path, calendar, equity, indicator_rows, orders):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateFormatter

    out.mkdir(parents=True, exist_ok=True)
    days = [date.fromisoformat(r["date"]) for r in equity]
    style = {"axes.spines.top": False, "axes.spines.right": False, "font.size": 9}
    agent_c, bench_c = "#C2571A", "#5B6470"

    with plt.rc_context(style):
        # 1) equity vs benchmark + drawdown
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 5.4), sharex=True,
                                     gridspec_kw={"height_ratios": [3, 1.2]})
        a1.plot(days, [r["total"] for r in equity], color=agent_c, lw=1.8,
                label="Agent (rule-based stand-in)")
        a1.plot(days, [r["benchmark_total"] for r in equity], color=bench_c, lw=1.4,
                ls="--", label="Buy & hold, equal weights")
        a1.axhline(START_CASH, color="#D8DCE1", lw=0.8)
        a1.set_ylabel("EUR")
        a1.set_title("Paper account vs. benchmark (SIMULATED prices)", loc="left")
        a1.legend(frameon=False, loc="lower left")
        a2.fill_between(days, [r["drawdown_pct"] for r in equity], 0, color=agent_c, alpha=.35,
                        lw=0)
        a2.plot(days, [r["benchmark_drawdown_pct"] for r in equity], color=bench_c, lw=1,
                ls="--")
        a2.set_ylabel("Drawdown %")
        a2.xaxis.set_major_formatter(DateFormatter("%b %y"))
        fig.tight_layout()
        fig.savefig(out / "equity_vs_benchmark.png", dpi=130)
        plt.close(fig)

        # 2) price + SMAs per symbol with fills
        fig, axes = plt.subplots(len(SYMBOLS), 1, figsize=(9, 2.0 * len(SYMBOLS)), sharex=True)
        for ax, s in zip(axes, SYMBOLS):
            rows = [r for r in indicator_rows if r["symbol"] == s]
            d = [date.fromisoformat(r["date"]) for r in rows]
            ax.plot(d, [r["last"] for r in rows], color="#1F2328", lw=1.2, label="close")
            ax.plot(d, [r["sma20"] for r in rows], color="#1F5FA8", lw=1, label="SMA20")
            ax.plot(d, [r["sma50"] for r in rows], color="#B48A00", lw=1, label="SMA50")
            for o in orders:
                if o["symbol"] == s and o["status"] == "filled":
                    buy = o["side"] == "buy"
                    ax.scatter(date.fromisoformat(o["decided"][:10]), o["fill_price"],
                               marker="^" if buy else "v", s=46, zorder=3,
                               color="#2E7D4F" if buy else "#B3261E")
            ax.set_ylabel(s, rotation=0, ha="right", va="center", fontweight="bold")
        axes[0].legend(frameon=False, ncol=3, loc="upper left")
        axes[0].set_title("Prices, moving averages and fills  (▲ buy  ▼ sell, SIMULATED)",
                          loc="left")
        axes[-1].xaxis.set_major_formatter(DateFormatter("%b %y"))
        fig.tight_layout()
        fig.savefig(out / "prices_and_trades.png", dpi=130)
        plt.close(fig)

        # 3) allocation over time
        fig, ax = plt.subplots(figsize=(9, 3.6))
        colors = ["#1F5FA8", "#C2571A", "#2E7D4F", "#7B4FA0", "#B48A00"]
        layers = [[r[f"weight_{s}"] for r in equity] for s in SYMBOLS]
        cash = [r["cash"] / r["total"] * 100 for r in equity]
        ax.stackplot(days, *layers, cash, labels=SYMBOLS + ["cash"],
                     colors=colors + ["#E4E7EB"])
        ax.axhline(100 - RULES.min_cash_pct, color="#1F2328", lw=0.8, ls=":")
        ax.text(days[0], 100 - RULES.min_cash_pct + 1, "min. 10% cash rule", fontsize=7.5)
        ax.set_ylim(0, 100)
        ax.set_ylabel("% of portfolio")
        ax.set_title("Allocation over time", loc="left")
        ax.legend(frameon=False, ncol=6, loc="upper center", bbox_to_anchor=(.5, -.12))
        ax.xaxis.set_major_formatter(DateFormatter("%b %y"))
        fig.tight_layout()
        fig.savefig(out / "allocation.png", dpi=130)
        plt.close(fig)


def daily_report(day, overview, portfolio, pending, summary):
    s = summary
    return f"""# Daily review, {day:%A %d %B %Y}

> **Sample report.** Written by `scripts/generate_sample_data.py` from a template, not by
> Claude. `python -m trading_agent --daily` writes reports with the same structure in
> `data/live/reports/`. Prices are SIMULATED.

## Market
```
{overview}
```

## Portfolio
```
{portfolio}
```
Since {s['period_start']}: account **{s['agent_return_pct']:+.2f} %**, buy-and-hold benchmark
**{s['benchmark_return_pct']:+.2f} %**. Max drawdown {s['agent_max_drawdown_pct']:.2f} %
(benchmark {s['benchmark_max_drawdown_pct']:.2f} %).

## Risk rules
{s['proposals_blocked_by_risk_rules']} proposals were blocked by the risk rules over the period
(see `trading/risk_rejections.csv`).

## What to watch
- Symbols near an SMA20/SMA50 crossover: their trend label may flip tomorrow.
- Approve or reject with `/approve <id>` and `/reject <id>` in interactive mode; the risk
  rules are checked again at execution.

---
**Pending proposals** (approve with /approve <id>):
```
{pending}
```
"""


# ---------------------------------------------------------------- main
def main():
    tmp_db = Path(tempfile.mkdtemp()) / "paper_sample.db"
    broker = PaperBroker(tmp_db)
    calendar, equity, indicator_rows, rejections = replay(broker)
    add_drawdown(equity)
    orders = sorted(broker.orders(limit=10_000), key=lambda o: o["id"])
    trips = round_trips(orders)

    if SAMPLE_DIR.exists():
        shutil.rmtree(SAMPLE_DIR)
    out = SAMPLE_DIR

    # prices (wide: one column per symbol)
    sim = SimulatedMarket()
    hist = {s: {b["date"]: b["close"] for b in sim.history(s, REPLAY_DAYS, END)}
            for s in SYMBOLS}
    write_csv(out / "market" / "prices.csv",
              [{"date": d.isoformat(), **{s: hist[s][d.isoformat()] for s in SYMBOLS}}
               for d in calendar])
    write_csv(out / "market" / "indicators_daily.csv", indicator_rows)

    write_csv(out / "trading" / "orders.csv", orders)
    write_csv(out / "trading" / "round_trips.csv", trips)
    empty = dict.fromkeys(["date", "symbol", "side", "qty", "value_eur", "reasons"], "")
    write_csv(out / "trading" / "risk_rejections.csv", rejections or [empty])
    write_csv(out / "trading" / "equity_curve.csv", equity)
    shutil.copy(tmp_db, out / "trading" / "paper_sample.db")

    # the exact text Claude sees from each tool on the last day
    server.market = FixedEndMarket(END)
    server.broker = broker
    tools_dir = out / "tool_outputs"
    tools_dir.mkdir(parents=True)
    texts = {"market_overview.txt": server.market_overview(),
             "analyze_symbol_NVDA.txt": server.analyze_symbol("NVDA"),
             "get_portfolio.txt": server.get_portfolio(),
             "list_orders.txt": server.list_orders(),
             "rules_risk.txt": server.risk_rules()}
    for name, text in texts.items():
        (tools_dir / name).write_text(text + "\n", encoding="utf-8")

    first, last = equity[0], equity[-1]
    wins = [t for t in trips if t["pnl_eur"] > 0]
    filled = [o for o in orders if o["status"] == "filled"]
    summary = {
        "note": "SIMULATED prices; decisions by a rule-based stand-in for Claude.",
        "period_start": first["date"], "period_end": last["date"],
        "trading_days": len(equity), "start_cash_eur": START_CASH,
        "final_total_eur": last["total"],
        "agent_return_pct": round((last["total"] / START_CASH - 1) * 100, 2),
        "benchmark_return_pct": round((last["benchmark_total"] / START_CASH - 1) * 100, 2),
        "agent_max_drawdown_pct": min(r["drawdown_pct"] for r in equity),
        "benchmark_max_drawdown_pct": min(r["benchmark_drawdown_pct"] for r in equity),
        "orders_filled": len(filled),
        "orders_pending": sum(o["status"] == "proposed" for o in orders),
        "proposals_blocked_by_risk_rules": len(rejections),
        "completed_round_trips": len(trips),
        "win_rate_pct": round(len(wins) / len(trips) * 100, 1) if trips else None,
        "realised_pnl_eur": round(sum(t["pnl_eur"] for t in trips), 2),
        "fees_paid_eur": len(filled) * FEE_EUR,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    (out / "reports").mkdir()
    (out / "reports" / f"{END.isoformat()}_daily_review.md").write_text(
        daily_report(END, texts["market_overview.txt"], texts["get_portfolio.txt"],
                     server.list_orders("proposed"), summary), encoding="utf-8")

    charts(out / "charts", calendar, equity, indicator_rows, orders)
    print(json.dumps(summary, indent=2))
    print(f"\nSample data written to {out}")


if __name__ == "__main__":
    main()
