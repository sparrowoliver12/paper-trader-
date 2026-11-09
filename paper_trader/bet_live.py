"""Live PAPER betting on 15-minute Bitcoin Up or Down. Fake money only.

Every 15 minutes, just after a window closes:
  1. settle the fake bet on the window that just finished (did BTC go up?)
  2. predict the new window, read the odds, and maybe place a new fake bet
State is saved to JSON so you can stop with Ctrl+C and resume.
"""
from __future__ import annotations

import csv
import json
import os
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from . import coinbase, polymarket
from .betting import Bet, Predictor, Quote, assumed_quote, place, settle

WINDOW = 900  # 15 minutes


def load(path: str, bankroll: float) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"start": bankroll, "bankroll": bankroll, "open_bet": None, "history": [],
            "last_window": None, "started": _now()}


def save(path: str, state: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def tick(state: dict, bars, predictor: Predictor, quote: Quote, stake: float, fee_rate: float,
         min_edge: float, now: datetime, log_path: str | None = None) -> list[str]:
    """One cycle. `bars` = finished 15-min candles, oldest first. Returns lines to print."""
    out = []
    by_time = {b.date: b for b in bars}
    # 1. settle the open bet once its window's candle has finished
    ob = state.get("open_bet")
    if ob and ob["window"] in by_time:
        c = by_time[ob["window"]]
        bet = settle(Bet(**ob), c.open, c.close)
        state["bankroll"] += bet.pnl + bet.cost  # cost was set aside when the bet was placed
        state["history"].append(asdict(bet))
        state["open_bet"] = None
        result = "WON " if bet.pnl > 0 else "LOST"
        out.append(f"  settled {bet.window}: bet {bet.side}, BTC went {bet.outcome} → {result} "
                   f"${bet.pnl:+,.2f}   bankroll ${state['bankroll']:,.2f}")
        _log(log_path, bet, state["bankroll"])
    # 2. maybe bet on the window that is open right now
    window = (now - timedelta(seconds=now.timestamp() % WINDOW)).strftime("%Y-%m-%d %H:%M")
    if state.get("last_window") == window:
        return out
    ob = state.get("open_bet")
    if ob and ob["window"] != window:
        if now.timestamp() % WINDOW < 120:
            state["waiting"] = True  # price feed hasn't published the finished candle yet; retry soon
            return out
        # still missing after 2 minutes: refund rather than guess the result
        state["bankroll"] += Bet(**ob).cost
        state["open_bet"] = None
        out.append(f"  could not get the result for {ob['window']}; bet refunded")
    state["waiting"] = False
    state["last_window"] = window
    closes = [b.close for b in bars]
    p_up = predictor.predict(closes)
    bet = None if state.get("open_bet") else place(window, p_up, quote, state["bankroll"], stake, fee_rate, min_edge)
    price_line = f"UP {quote.up_ask * 100:.0f}¢ / DOWN {quote.down_ask * 100:.0f}¢ ({quote.source})"
    if bet:
        state["bankroll"] -= bet.cost
        state["open_bet"] = asdict(bet)
        out.append(f"[{window} UTC] BTC ${closes[-1]:,.2f} | model {p_up:.0%} up | {price_line} | "
                   f"BET {bet.side} {bet.shares:g} sh @ {bet.price * 100:.0f}¢ = ${bet.cost:,.2f}")
    else:
        out.append(f"[{window} UTC] BTC ${closes[-1]:,.2f} | model {p_up:.0%} up | {price_line} | no edge, skip")
    return out


def stats(state: dict) -> str:
    h = state["history"]
    if not h:
        return f"No settled bets yet. Bankroll ${state['bankroll']:,.2f}"
    wins = sum(b["pnl"] > 0 for b in h)
    cost = sum(b["shares"] * b["price"] + b["fee"] for b in h)
    shares = sum(b["shares"] for b in h)
    total = state["bankroll"] + (state["open_bet"]["shares"] * state["open_bet"]["price"] + state["open_bet"]["fee"]
                                 if state.get("open_bet") else 0)
    return (f"{len(h)} bets | won {wins / len(h):.1%} (break-even {cost / shares:.1%}) | "
            f"bankroll ${total:,.2f} ({total / state['start'] - 1:+.2%})")


def run(predictor: Predictor, bankroll: float = 1000, stake: float = 10, fee_rate: float = 0.07,
        min_edge: float = 0.0, spread: float = 0.02, use_polymarket: bool = True,
        state_path: str = "bet_state.json", log_path: str = "bet_log.csv", once: bool = False) -> None:
    state = load(state_path, bankroll)
    live_odds = use_polymarket and polymarket.available()
    print("PAPER BETTING — fake money only. 15-minute Bitcoin Up or Down.")
    print(f"Predictor: {predictor.name} | stake ${stake:g}/bet | fee rate {fee_rate} | "
          f"odds: {'Polymarket live (falls back to assumed)' if live_odds else 'assumed 50/50 + spread'}")
    if use_polymarket and not live_odds:
        print("  (For real Polymarket odds: pip3 install polymarket-us)")
    print(f"State: {state_path}   Log: {log_path}   Ctrl+C to stop.\n{stats(state)}\n", flush=True)
    while True:
        try:
            bars = coinbase.fetch("BTC-USD", "15m", days=1)
            q = None
            if live_odds:
                try:
                    q = polymarket.quote()
                except Exception as e:  # API shape changes, network blips: never crash the loop
                    print(f"  (Polymarket odds unavailable: {e}; using assumed odds)")
            lines = tick(state, bars, predictor, q or assumed_quote(spread), stake, fee_rate,
                         min_edge, datetime.now(timezone.utc), log_path)
            for line in lines:
                print(line, flush=True)
            if any("settled" in ln for ln in lines):
                print("  " + stats(state), flush=True)
            save(state_path, state)
            if state.get("waiting") and not once:
                time.sleep(15)  # retry shortly instead of waiting a whole window
                continue
        except RuntimeError as e:
            print(f"[{_now()}] {e} — retrying next window.", flush=True)
        if once:
            return
        wait = WINDOW - (time.time() % WINDOW) + 8  # 8s after the window flips
        try:
            time.sleep(wait)
        except KeyboardInterrupt:
            print("\nStopped. " + stats(state) + "\nRun the same command to resume.")
            return


def _log(path, bet: Bet, bankroll: float) -> None:
    if not path:
        return
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["window", "side", "model_p_up", "price", "shares", "fee", "outcome", "pnl", "bankroll", "odds_source"])
        w.writerow([bet.window, bet.side, f"{bet.p_up:.3f}", bet.price, bet.shares, f"{bet.fee:.4f}",
                    bet.outcome, f"{bet.pnl:.2f}", f"{bankroll:.2f}", bet.quote_source])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
