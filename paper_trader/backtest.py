"""Run a strategy over historical bars with a PaperBroker and report results."""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass

from .broker import PaperBroker
from .data import Bar
from .strategies import Strategy


@dataclass
class Result:
    start_equity: float
    end_equity: float
    total_return: float
    max_drawdown: float
    sharpe: float
    num_trades: int
    win_rate: float
    equity_curve: list[tuple[str, float]]
    broker: PaperBroker

    def summary(self) -> str:
        return "\n".join([
            f"Start equity : ${self.start_equity:,.2f}",
            f"End equity   : ${self.end_equity:,.2f}",
            f"Total return : {self.total_return:+.2%}",
            f"Max drawdown : {self.max_drawdown:.2%}",
            f"Sharpe (ann.): {self.sharpe:.2f}",
            f"Trades       : {self.num_trades}",
            f"Win rate     : {self.win_rate:.0%}",
        ])


def run(bars: list[Bar], strategy: Strategy, symbol: str = "SYM", cash: float = 10_000.0,
        position_size: float = 1.0, fee_pct: float = 0.0, slippage_pct: float = 0.0005,
        fractional: bool = False, periods_per_year: float = 252) -> Result:
    """periods_per_year: 252 for daily stocks; 35,040 for 15-minute crypto (24/7)."""
    broker = PaperBroker(cash=cash, fee_pct=fee_pct, slippage_pct=slippage_pct)
    closes: list[float] = []
    curve: list[tuple[str, float]] = []
    sell_pnls: list[float] = []

    for bar in bars:
        closes.append(bar.close)
        holding = broker.position(symbol).qty > 0
        sig = strategy.signal(closes, holding)
        if sig == "buy" and not holding:
            broker.buy_with_fraction(symbol, position_size, bar.close, bar.date, fractional=fractional)
        elif sig == "sell" and holding:
            before = broker.realized_pnl
            broker.close(symbol, bar.close, bar.date)
            sell_pnls.append(broker.realized_pnl - before)
        curve.append((bar.date, broker.equity({symbol: bar.close})))

    end = curve[-1][1] if curve else cash
    return Result(
        start_equity=cash,
        end_equity=end,
        total_return=end / cash - 1,
        max_drawdown=_max_drawdown([e for _, e in curve]),
        sharpe=_sharpe([e for _, e in curve], periods_per_year),
        num_trades=len(broker.trades),
        win_rate=(sum(p > 0 for p in sell_pnls) / len(sell_pnls)) if sell_pnls else 0.0,
        equity_curve=curve,
        broker=broker,
    )


def _max_drawdown(equity: list[float]) -> float:
    peak, worst = -math.inf, 0.0
    for e in equity:
        peak = max(peak, e)
        worst = max(worst, (peak - e) / peak if peak > 0 else 0)
    return worst


def _sharpe(equity: list[float], periods: float = 252) -> float:
    rets = [b / a - 1 for a, b in zip(equity, equity[1:]) if a > 0]
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))
    return mean / sd * math.sqrt(periods) if sd > 0 else 0.0


def save_trades(result: Result, path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "symbol", "side", "qty", "price", "fee"])
        for t in result.broker.trades:
            w.writerow([t.time, t.symbol, t.side, round(t.qty, 8), f"{t.price:.4f}", f"{t.fee:.4f}"])


def save_equity(result: Result, path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "equity"])
        w.writerows((d, f"{e:.2f}") for d, e in result.equity_curve)
