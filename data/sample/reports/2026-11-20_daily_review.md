# Daily review, Friday 20 November 2026

> **Sample report.** Written by `scripts/generate_sample_data.py` from a template, not by
> Claude. `python -m trading_agent --daily` writes reports with the same structure in
> `data/live/reports/`. Prices are SIMULATED.

## Market
```
[SIMULATED prices (not real market data)]
symbol | last | 5d % | 20d % | rsi14 | trend
AAPL | 251.79 | 3.36 | 12.08 | 53.6 | up (sma20 244.57 vs sma50 226.48)
ASML | 1110.36 | 2.48 | 13.27 | 72.3 | up (sma20 1049.52 vs sma50 986.64)
MSFT | 394.48 | 0.4 | -1.23 | 57.9 | down (sma20 385.35 vs sma50 402.84)
NVDA | 116.54 | 2.0 | 4.6 | 58.4 | up (sma20 113.26 vs sma50 107.52)
SAP | 427.02 | -4.84 | -6.62 | 36.0 | up (sma20 440.89 vs sma50 438.19)
```

## Portfolio
```
cash: 3478.5 EUR | total value: 9924.11 EUR
SAP: 4 @ avg 437.9 | now 427.02 | value 1708.08 (17.2%) | P/L -2.48%
AAPL: 7 @ avg 229.15 | now 251.79 | value 1762.53 (17.8%) | P/L 9.88%
ASML: 1 @ avg 988.04 | now 1110.36 | value 1110.36 (11.2%) | P/L 12.38%
NVDA: 16 @ avg 112.06 | now 116.54 | value 1864.64 (18.8%) | P/L 4.0%
```
Since 2026-05-25: account **-0.76 %**, buy-and-hold benchmark
**+0.01 %**. Max drawdown -5.57 %
(benchmark -11.10 %).

## Risk rules
65 proposals were blocked by the risk rules over the period
(see `trading/risk_rejections.csv`).

## What to watch
- Symbols near an SMA20/SMA50 crossover: their trend label may flip tomorrow.
- Approve or reject with `/approve <id>` and `/reject <id>` in interactive mode; the risk
  rules are checked again at execution.

---
**Pending proposals** (approve with /approve <id>):
```
No orders.
```
