"""Strategies look at price history and return "buy", "sell" or None.

To make your own: subclass Strategy, implement signal(), and add it to STRATEGIES.
"""
from __future__ import annotations


class Strategy:
    name = "base"

    def signal(self, closes: list[float], holding: bool) -> str | None:
        raise NotImplementedError


def sma(values: list[float], n: int) -> float | None:
    return sum(values[-n:]) / n if len(values) >= n else None


class SmaCrossover(Strategy):
    """Buy when the fast moving average crosses above the slow one; sell on the cross back down."""

    name = "sma"

    def __init__(self, fast: int = 10, slow: int = 30):
        if fast >= slow:
            raise ValueError("fast must be shorter than slow")
        self.fast, self.slow = fast, slow

    def signal(self, closes, holding):
        if len(closes) < self.slow + 1:
            return None
        f_now, s_now = sma(closes, self.fast), sma(closes, self.slow)
        f_prev, s_prev = sma(closes[:-1], self.fast), sma(closes[:-1], self.slow)
        if not holding and f_prev <= s_prev and f_now > s_now:
            return "buy"
        if holding and f_prev >= s_prev and f_now < s_now:
            return "sell"
        return None


def rsi(closes: list[float], n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for a, b in zip(closes[-n - 1:-1], closes[-n:]):
        change = b - a
        gains += max(change, 0)
        losses += max(-change, 0)
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - 100 / (1 + rs)


class RsiMeanReversion(Strategy):
    """Buy when RSI says 'oversold', sell when it says 'overbought'."""

    name = "rsi"

    def __init__(self, period: int = 14, low: float = 30, high: float = 70):
        self.period, self.low, self.high = period, low, high

    def signal(self, closes, holding):
        r = rsi(closes, self.period)
        if r is None:
            return None
        if not holding and r < self.low:
            return "buy"
        if holding and r > self.high:
            return "sell"
        return None


class BuyAndHold(Strategy):
    """Baseline: buy on day one and never sell. Beat this or the bot isn't helping."""

    name = "hold"

    def signal(self, closes, holding):
        return None if holding else "buy"


STRATEGIES = {cls.name: cls for cls in (SmaCrossover, RsiMeanReversion, BuyAndHold)}
