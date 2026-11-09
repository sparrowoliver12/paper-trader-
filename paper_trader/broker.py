"""A simulated (paper) broker. No real money, no real orders — ever."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Trade:
    time: str
    symbol: str
    side: str  # "buy" or "sell"
    qty: float
    price: float
    fee: float

    @property
    def value(self) -> float:
        return self.qty * self.price


@dataclass
class Position:
    qty: float = 0.0
    avg_cost: float = 0.0


@dataclass
class PaperBroker:
    """Tracks fake cash, positions and a trade log.

    fee_pct: commission as a fraction of trade value (0.001 = 0.1%).
    slippage_pct: price moves against you by this fraction on every fill.
    """

    cash: float = 10_000.0
    fee_pct: float = 0.0
    slippage_pct: float = 0.0005
    positions: dict[str, Position] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)
    realized_pnl: float = 0.0

    def position(self, symbol: str) -> Position:
        return self.positions.setdefault(symbol, Position())

    def buy(self, symbol: str, qty: float, price: float, time: str | None = None) -> Trade:
        if qty <= 0:
            raise ValueError("qty must be positive")
        fill = price * (1 + self.slippage_pct)
        fee = fill * qty * self.fee_pct
        cost = fill * qty + fee
        if cost > self.cash + 1e-9:
            raise ValueError(f"insufficient cash: need {cost:.2f}, have {self.cash:.2f}")
        pos = self.position(symbol)
        pos.avg_cost = (pos.avg_cost * pos.qty + fill * qty) / (pos.qty + qty)
        pos.qty += qty
        self.cash -= cost
        return self._log(time, symbol, "buy", qty, fill, fee)

    def sell(self, symbol: str, qty: float, price: float, time: str | None = None) -> Trade:
        pos = self.position(symbol)
        if qty <= 0:
            raise ValueError("qty must be positive")
        if qty > pos.qty + 1e-9:
            raise ValueError(f"cannot sell {qty} {symbol}; only hold {pos.qty} (no shorting)")
        fill = price * (1 - self.slippage_pct)
        fee = fill * qty * self.fee_pct
        self.realized_pnl += (fill - pos.avg_cost) * qty - fee
        pos.qty -= qty
        if pos.qty < 1e-9:
            pos.qty, pos.avg_cost = 0.0, 0.0
        self.cash += fill * qty - fee
        return self._log(time, symbol, "sell", qty, fill, fee)

    def buy_with_fraction(self, symbol: str, fraction: float, price: float, time: str | None = None):
        """Spend `fraction` of available cash (whole shares only)."""
        per_share = price * (1 + self.slippage_pct) * (1 + self.fee_pct)
        qty = int((self.cash * fraction) // per_share)
        return self.buy(symbol, qty, price, time) if qty > 0 else None

    def close(self, symbol: str, price: float, time: str | None = None):
        pos = self.position(symbol)
        return self.sell(symbol, pos.qty, price, time) if pos.qty > 0 else None

    def equity(self, prices: dict[str, float]) -> float:
        held = sum(p.qty * prices.get(s, p.avg_cost) for s, p in self.positions.items())
        return self.cash + held

    def _log(self, time, symbol, side, qty, price, fee) -> Trade:
        t = Trade(time or datetime.now().isoformat(timespec="seconds"), symbol, side, qty, price, fee)
        self.trades.append(t)
        return t
