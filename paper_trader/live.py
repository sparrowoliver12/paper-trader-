"""Live paper trading: every new candle, check the real price and make a FAKE trade.

State (fake cash, holdings, trades) is saved to a JSON file, so you can stop with
Ctrl+C and pick up where you left off later.
"""
from __future__ import annotations

import csv
import json
import math
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone

from . import coinbase
from .broker import PaperBroker, Position, Trade
from .strategies import Strategy


def load_broker(path: str, cash: float, fee: float, slippage: float) -> tuple[PaperBroker, dict]:
    if os.path.exists(path):
        with open(path) as f:
            s = json.load(f)
        b = PaperBroker(cash=s["cash"], fee_pct=fee, slippage_pct=slippage)
        b.positions = {k: Position(**v) for k, v in s["positions"].items()}
        b.trades = [Trade(**t) for t in s["trades"]]
        b.realized_pnl = s["realized_pnl"]
        return b, s
    s = {"start_cash": cash, "started": _now(), "last_bar": None}
    return PaperBroker(cash=cash, fee_pct=fee, slippage_pct=slippage), s


def save_broker(path: str, b: PaperBroker, s: dict) -> None:
    s.update(cash=b.cash, realized_pnl=b.realized_pnl,
             positions={k: asdict(v) for k, v in b.positions.items()},
             trades=[asdict(t) for t in b.trades])
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, path)  # atomic: a crash never leaves a half-written file


def step(broker: PaperBroker, state: dict, strategy: Strategy, bars, symbol: str,
         size: float, log_path: str | None = None) -> str | None:
    """Process the newest finished candle once. Returns a status line, or None if nothing new."""
    if not bars or bars[-1].date == state.get("last_bar"):
        return None
    last = bars[-1]
    closes = [b.close for b in bars]
    holding = broker.position(symbol).qty > 0
    sig = strategy.signal(closes, holding)
    action = "hold"
    if sig == "buy" and not holding:
        t = broker.buy_with_fraction(symbol, size, last.close, last.date, fractional=True)
        action = f"BUY {t.qty:.6f} @ ${t.price:,.2f}" if t else "buy skipped (no cash)"
    elif sig == "sell" and holding:
        before = broker.realized_pnl
        t = broker.close(symbol, last.close, last.date)
        action = f"SELL {t.qty:.6f} @ ${t.price:,.2f}  (P&L ${broker.realized_pnl - before:+,.2f})"
    state["last_bar"] = last.date
    equity = broker.equity({symbol: last.close})
    start = state.get("start_cash", equity)
    if log_path:
        new = not os.path.exists(log_path)
        with open(log_path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["bar", "price", "action", "cash", "holding", "equity"])
            w.writerow([last.date, last.close, action, f"{broker.cash:.2f}",
                        f"{broker.position(symbol).qty:.8f}", f"{equity:.2f}"])
    return (f"[{last.date} UTC] {symbol} ${last.close:,.2f} | {action:<44} | "
            f"equity ${equity:,.2f} ({equity / start - 1:+.2%})")


def run_live(strategy: Strategy, product: str = "BTC-USD", interval: str = "15m",
             cash: float = 10_000, fee: float = 0.006, slippage: float = 0.0005, size: float = 1.0,
             state_path: str = "live_state.json", log_path: str = "live_log.csv",
             lookback_bars: int = 300, once: bool = False) -> None:
    g = coinbase.seconds(interval)
    symbol = product.split("-")[0]
    broker, state = load_broker(state_path, cash, fee, slippage)
    resumed = state.get("last_bar") is not None
    print(f"LIVE PAPER TRADING — fake money only. {product} {interval}, strategy={strategy.name}, "
          f"fee={fee:.2%}. {'Resumed' if resumed else 'Started with'} ${broker.cash:,.2f} cash.")
    print(f"State: {state_path}   Log: {log_path}   Stop any time with Ctrl+C.\n", flush=True)
    days = max(1, math.ceil(lookback_bars * g / 86400))
    while True:
        try:
            bars = coinbase.fetch(product, interval, days=days)
            line = step(broker, state, strategy, bars, symbol, size, log_path)
            if line:
                save_broker(state_path, broker, state)
                print(line, flush=True)
        except RuntimeError as e:
            print(f"[{_now()}] {e} — will retry next candle.", flush=True)
        if once:
            return
        wait = g - (time.time() % g) + 20  # wake 20s after the next candle closes
        try:
            time.sleep(wait)
        except KeyboardInterrupt:
            print("\nStopped. Your fake account is saved; run the same command to resume.")
            return


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
