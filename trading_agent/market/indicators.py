# indicators.py - classic indicators as small, pure, tested functions.
# Claude is bad at long arithmetic over 100 numbers; Python is perfect at it.
import math


def sma(closes: list[float], n: int) -> float | None:
    """Simple moving average of the last n closes."""
    return round(sum(closes[-n:]) / n, 2) if len(closes) >= n else None


def rsi(closes: list[float], n: int = 14) -> float | None:
    """Relative Strength Index (0-100). >70 often called 'overbought', <30 'oversold'."""
    if len(closes) <= n:
        return None
    changes = [b - a for a, b in zip(closes[-n - 1:-1], closes[-n:])]
    gains = sum(c for c in changes if c > 0) / n
    losses = -sum(c for c in changes if c < 0) / n
    if losses == 0:
        return 100.0
    return round(100 - 100 / (1 + gains / losses), 1)


def pct_change(closes: list[float], n: int) -> float | None:
    """Return over the last n trading days, in percent."""
    return round((closes[-1] / closes[-n - 1] - 1) * 100, 2) if len(closes) > n else None


def volatility(closes: list[float], n: int = 20) -> float | None:
    """Annualised volatility of daily returns over n days, in percent."""
    if len(closes) <= n:
        return None
    rets = [math.log(b / a) for a, b in zip(closes[-n - 1:-1], closes[-n:])]
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    return round(math.sqrt(var) * math.sqrt(252) * 100, 1)


def max_drawdown(closes: list[float]) -> float:
    """Largest fall from a peak, in percent (negative number)."""
    peak, worst = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        worst = min(worst, c / peak - 1)
    return round(worst * 100, 2)


def summary(closes: list[float]) -> dict:
    return {"last": closes[-1], "sma20": sma(closes, 20), "sma50": sma(closes, 50),
            "rsi14": rsi(closes), "change_5d_pct": pct_change(closes, 5),
            "change_20d_pct": pct_change(closes, 20), "volatility_20d_pct": volatility(closes),
            "max_drawdown_pct": max_drawdown(closes)}
