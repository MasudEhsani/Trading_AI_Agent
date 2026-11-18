# market_data.py - Milestone 1: where prices come from. Two sources, one interface.
import hashlib
import math
import os
import random
from datetime import date, timedelta


class SimulatedMarket:
    """Fake but realistic daily prices (random walk). Offline, free, reproducible.
    Each symbol has its own seed, so 'AAPL' always produces the same history."""

    label = "SIMULATED prices (not real market data)"
    START_PRICES = {"AAPL": 190.0, "MSFT": 420.0, "SAP": 230.0, "NVDA": 120.0, "ASML": 700.0}

    def history(self, symbol: str, days: int = 120, end: date | None = None) -> list[dict]:
        symbol = symbol.upper()
        if symbol not in self.START_PRICES:
            raise KeyError(f"Unknown symbol {symbol}. Known: {', '.join(self.START_PRICES)}")
        end = end or date.today()
        seed = int(hashlib.md5(symbol.encode()).hexdigest(), 16) % 10**8
        rng = random.Random(seed)
        bars, price, day = [], self.START_PRICES[symbol], date(2025, 1, 1)
        while day <= end:
            if day.weekday() < 5:  # trading days only
                price *= math.exp(rng.gauss(0.0004, 0.018))  # ~ +10%/year, 1.8% daily moves
                bars.append({"date": day.isoformat(), "close": round(price, 2)})
            day += timedelta(days=1)
        return bars[-days:]

    def price(self, symbol: str) -> float:
        return self.history(symbol, days=1)[-1]["close"]


class YahooMarket:
    """Real prices via the unofficial yfinance package (pip install yfinance).
    Can break or be rate-limited at any time: that's why the default is simulated."""

    label = "Yahoo Finance via yfinance (unofficial, may be delayed)"

    def history(self, symbol: str, days: int = 120, end: date | None = None) -> list[dict]:
        import yfinance as yf  # imported here so the project works without it
        df = yf.Ticker(symbol).history(period=f"{int(days * 1.5) + 10}d", auto_adjust=True)
        if df.empty:
            raise KeyError(f"No data for {symbol}")
        bars = [{"date": idx.date().isoformat(), "close": round(float(row["Close"]), 2)}
                for idx, row in df.iterrows()]
        return bars[-days:]

    def price(self, symbol: str) -> float:
        return self.history(symbol, days=1)[-1]["close"]


def get_market():
    """Choose the source with an environment variable: MARKET_DATA=sim (default) or yahoo."""
    return YahooMarket() if os.getenv("MARKET_DATA", "sim") == "yahoo" else SimulatedMarket()
