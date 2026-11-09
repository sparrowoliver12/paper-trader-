"""Paper betting on 15-minute "Bitcoin Up or Down" prediction markets.

Each window asks: will BTC finish the 15 minutes at or above where it started?
A winning share pays $1. You buy UP or DOWN shares at the market's price (e.g. 51¢).

A *predictor* estimates the chance BTC goes up. The bot only bets when that
estimate beats the market price by more than the fee. That gap is the "edge".
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .data import Bar
from .strategies import rsi


# ---------------------------------------------------------------- fees & prices

def taker_fee(price: float, rate: float) -> float:
    """Fee per share, in dollars: rate × p × (1 − p).

    This is the shape prediction markets use: largest at 50¢, small near 0¢/$1.
    With rate=0.07 that's 1.75¢ per share at 50¢. CHECK YOUR APP'S ACTUAL FEE and
    set --fee-rate to match (0 if your app charges no fee on these markets).
    """
    return rate * price * (1 - price)


def break_even_win_rate(price: float, rate: float) -> float:
    """How often a bet at this price must win just to not lose money."""
    return price + taker_fee(price, rate)


@dataclass
class Quote:
    """What it costs to buy each side right now (the 'ask' prices)."""
    up_ask: float
    down_ask: float
    source: str = "assumed"


def assumed_quote(spread: float = 0.02) -> Quote:
    """When we don't have live odds: a fair 50/50 market with a typical spread."""
    return Quote(0.5 + spread / 2, 0.5 + spread / 2, "assumed")


# ---------------------------------------------------------------- predictors

class Predictor:
    """Look at past closes, return the probability (0-1) that the NEXT window goes up."""

    name = "base"

    def predict(self, closes: list[float]) -> float:
        raise NotImplementedError


class CoinFlip(Predictor):
    """Always 50%. Never finds an edge, so never bets. The honest baseline."""
    name = "coin"

    def predict(self, closes):
        return 0.5


class Momentum(Predictor):
    """'What went up keeps going up.' Leans toward the direction of the last few windows."""
    name = "momentum"

    def __init__(self, lookback: int = 4, strength: float = 0.06):
        self.lookback, self.strength = lookback, strength

    def predict(self, closes):
        if len(closes) < self.lookback + 1:
            return 0.5
        moves = [1 if b >= a else -1 for a, b in zip(closes[-self.lookback - 1:-1], closes[-self.lookback:])]
        return _clip(0.5 + self.strength * sum(moves) / self.lookback)


class MeanReversion(Predictor):
    """'What went up comes back down.' The opposite bet to momentum."""
    name = "reversion"

    def __init__(self, lookback: int = 4, strength: float = 0.06):
        self._m = Momentum(lookback, strength)

    def predict(self, closes):
        return _clip(1 - self._m.predict(closes))


class RsiPredictor(Predictor):
    """Oversold (low RSI) → leans up. Overbought (high RSI) → leans down."""
    name = "rsi"

    def __init__(self, period: int = 14, strength: float = 0.10):
        self.period, self.strength = period, strength

    def predict(self, closes):
        r = rsi(closes, self.period)
        return 0.5 if r is None else _clip(0.5 + self.strength * (50 - r) / 50)


def _clip(p: float) -> float:
    return min(0.99, max(0.01, p))


PREDICTORS = {c.name: c for c in (CoinFlip, Momentum, MeanReversion, RsiPredictor)}


# ---------------------------------------------------------------- decisions

@dataclass
class Bet:
    window: str        # window start time (UTC)
    side: str          # "UP" or "DOWN"
    p_up: float        # predictor's estimate when the bet was placed
    price: float       # cost per share
    shares: float
    fee: float         # total fee paid
    quote_source: str
    outcome: str | None = None   # "UP" / "DOWN" once settled
    pnl: float | None = None

    @property
    def cost(self) -> float:
        return self.shares * self.price + self.fee


def decide(p_up: float, quote: Quote, fee_rate: float, min_edge: float) -> tuple[str, float, float] | None:
    """Pick the side with the bigger expected profit per share, if it clears min_edge.

    Returns (side, price, edge) or None.
    """
    options = []
    for side, prob, price in (("UP", p_up, quote.up_ask), ("DOWN", 1 - p_up, quote.down_ask)):
        if 0 < price < 1:
            edge = prob - price - taker_fee(price, fee_rate)  # expected profit per $1 share
            options.append((edge, side, price))
    if not options:
        return None
    edge, side, price = max(options)
    return (side, price, edge) if edge >= min_edge else None


def place(window: str, p_up: float, quote: Quote, bankroll: float, stake: float,
          fee_rate: float, min_edge: float) -> Bet | None:
    choice = decide(p_up, quote, fee_rate, min_edge)
    if not choice:
        return None
    side, price, _ = choice
    per_share = price + taker_fee(price, fee_rate)
    shares = math.floor(min(stake, bankroll) / per_share * 100) / 100
    if shares < 1:
        return None
    return Bet(window, side, p_up, price, shares, shares * taker_fee(price, fee_rate), quote.source)


def settle(bet: Bet, open_price: float, close_price: float) -> Bet:
    """UP wins if BTC closes at or above the window's opening price."""
    bet.outcome = "UP" if close_price >= open_price else "DOWN"
    payout = bet.shares if bet.outcome == bet.side else 0.0
    bet.pnl = payout - bet.cost
    return bet


# ---------------------------------------------------------------- backtest

@dataclass
class BetResult:
    start: float
    end: float
    bets: list[Bet] = field(default_factory=list)
    windows: int = 0
    brier: float = 0.25
    curve: list[tuple[str, float]] = field(default_factory=list)

    def summary(self) -> str:
        n = len(self.bets)
        wins = sum(b.pnl > 0 for b in self.bets)
        staked = sum(b.cost for b in self.bets)
        fees = sum(b.fee for b in self.bets)
        avg_price = sum(b.price for b in self.bets) / n if n else 0
        peak, dd = -math.inf, 0.0
        for _, e in self.curve:
            peak = max(peak, e)
            dd = max(dd, (peak - e) / peak if peak > 0 else 0)
        lines = [
            f"Windows seen    : {self.windows:,}",
            f"Bets placed     : {n:,} ({n / self.windows:.0%} of windows)" if self.windows else "Bets placed     : 0",
            f"Win rate        : {wins / n:.1%}" if n else "Win rate        : -",
        ]
        if n:  # each share pays $1, so break-even win rate = average cost per share
            be = staked / sum(b.shares for b in self.bets)
            lines.append(f"Break-even rate : {be:.1%}  (must win more often than this to profit)")
        lines += [
            f"Start bankroll  : ${self.start:,.2f}",
            f"End bankroll    : ${self.end:,.2f}  ({self.end / self.start - 1:+.2%})",
            f"Total staked    : ${staked:,.2f}   fees ${fees:,.2f}",
            f"ROI per $ bet   : {(self.end - self.start) / staked:+.2%}" if staked else "ROI per $ bet   : -",
            f"Max drawdown    : {dd:.2%}",
            f"Avg price paid  : {avg_price * 100:.1f}¢",
            f"Brier score     : {self.brier:.4f}  (0.2500 = coin flip; lower is better)",
        ]
        return "\n".join(lines)


def backtest(bars: list[Bar], predictor: Predictor, bankroll: float = 1000.0, stake: float = 10.0,
             fee_rate: float = 0.07, min_edge: float = 0.0, spread: float = 0.02,
             always: str | None = None) -> BetResult:
    """Walk through 15-minute candles. Before each window, predict and maybe bet; then settle.

    `always` = "UP" or "DOWN" forces a bet every window (a useful baseline).
    Prices are assumed (50/50 market with `spread`) because historical order books
    aren't available for free. Real odds move, which usually makes edges harder to find.
    """
    res = BetResult(start=bankroll, end=bankroll)
    closes: list[float] = []
    sq_err = 0.0
    quote = assumed_quote(spread)
    for bar in bars:
        open_price = bar.open if bar.open is not None else (closes[-1] if closes else None)
        if open_price is not None and closes:
            p = predictor.predict(closes)  # only uses windows that already finished
            went_up = bar.close >= open_price
            sq_err += (p - (1.0 if went_up else 0.0)) ** 2
            res.windows += 1
            if always:
                price = quote.up_ask if always == "UP" else quote.down_ask
                shares = math.floor(min(stake, res.end) / (price + taker_fee(price, fee_rate)) * 100) / 100
                bet = Bet(bar.date, always, p, price, shares, shares * taker_fee(price, fee_rate), "assumed") if shares >= 1 else None
            else:
                bet = place(bar.date, p, quote, res.end, stake, fee_rate, min_edge)
            if bet:
                settle(bet, open_price, bar.close)
                res.end += bet.pnl
                res.bets.append(bet)
            res.curve.append((bar.date, res.end))
        closes.append(bar.close)
    res.brier = sq_err / res.windows if res.windows else 0.25
    return res
