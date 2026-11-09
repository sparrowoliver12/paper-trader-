"""Command line.

  python -m paper_trader [backtest options]        backtest (default command)
  python -m paper_trader fetch [options]           download crypto candles from Coinbase
  python -m paper_trader live  [options]           live paper trading on real prices
"""
from __future__ import annotations

import argparse
import os
import sys

from .backtest import run, save_equity, save_trades
from .data import load_csv, save_csv, synthetic
from .strategies import STRATEGIES, RsiMeanReversion, SmaCrossover

CRYPTO_FEE = 0.006  # ~0.6% per trade: a typical low-volume taker fee on crypto exchanges
MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "6h": 360, "1d": 1440}


def add_strategy_args(p):
    p.add_argument("--strategy", choices=sorted(STRATEGIES), default="sma")
    p.add_argument("--fast", type=int, default=10, help="sma: fast average length (bars)")
    p.add_argument("--slow", type=int, default=30, help="sma: slow average length (bars)")
    p.add_argument("--rsi-period", type=int, default=14)
    p.add_argument("--rsi-low", type=float, default=30)
    p.add_argument("--rsi-high", type=float, default=70)


def build_strategy(args):
    if args.strategy == "sma":
        return SmaCrossover(args.fast, args.slow)
    if args.strategy == "rsi":
        return RsiMeanReversion(args.rsi_period, args.rsi_low, args.rsi_high)
    return STRATEGIES[args.strategy]()


def cmd_backtest(argv):
    p = argparse.ArgumentParser(prog="paper_trader", description="Backtest a strategy with fake money.")
    p.add_argument("--market", choices=["stocks", "crypto"], default="stocks",
                   help="crypto = fractional coins, 24/7 math, realistic default fee")
    p.add_argument("--csv", help="CSV of prices (time + Close). Omit to use synthetic data.")
    p.add_argument("--symbol", default=None)
    p.add_argument("--interval", choices=list(MINUTES), default=None,
                   help="bar size (default: 1d stocks, 15m crypto)")
    add_strategy_args(p)
    p.add_argument("--cash", type=float, default=10_000)
    p.add_argument("--size", type=float, default=1.0, help="fraction of cash per buy (0-1)")
    p.add_argument("--fee", type=float, default=None,
                   help=f"fee as a fraction (default 0 stocks, {CRYPTO_FEE} crypto)")
    p.add_argument("--slippage", type=float, default=0.0005)
    p.add_argument("--bars", "--days", dest="bars", type=int, default=None, help="synthetic data length")
    p.add_argument("--seed", type=int, default=42, help="synthetic data seed")
    p.add_argument("--compare", action="store_true", help="also show buy-and-hold for comparison")
    p.add_argument("--out", default="results", help="folder for trades.csv and equity.csv")
    args = p.parse_args(argv)

    crypto = args.market == "crypto"
    interval = args.interval or ("15m" if crypto else "1d")
    minutes = MINUTES[interval]
    fee = args.fee if args.fee is not None else (CRYPTO_FEE if crypto else 0.0)
    symbol = args.symbol or ("BTC" if crypto else "SYM")
    # How many bars make a year: stocks trade ~252 days; crypto never closes.
    per_year = 365 * 24 * 60 / minutes if crypto else (252 if minutes >= 1440 else 252 * 390 / minutes)

    if args.csv:
        bars, source = load_csv(args.csv), args.csv
    else:
        n = args.bars or (2880 if crypto else 500)
        if crypto:
            per_bar_vol = 0.55 / per_year ** 0.5  # ~55% annual volatility, like BTC
            bars = synthetic(n, start=90_000, drift=0, vol=per_bar_vol, seed=args.seed, interval_minutes=minutes)
        else:
            bars = synthetic(n, seed=args.seed, interval_minutes=minutes)
        source = f"synthetic ({n} {interval} bars, seed {args.seed})"
    print(f"Data: {source}  |  {bars[0].date} → {bars[-1].date}  |  fee {fee:.2%}  |  PAPER MONEY ONLY\n")

    kwargs = dict(symbol=symbol, cash=args.cash, position_size=args.size, fee_pct=fee,
                  slippage_pct=args.slippage, fractional=crypto, periods_per_year=per_year)
    result = run(bars, build_strategy(args), **kwargs)
    print(f"Strategy: {args.strategy}")
    print(result.summary())
    fees = sum(t.fee for t in result.broker.trades)
    if fees:
        print(f"Fees paid    : ${fees:,.2f}")

    if args.compare and args.strategy != "hold":
        print("\nBaseline: buy and hold")
        print(run(bars, STRATEGIES["hold"](), **kwargs).summary())

    os.makedirs(args.out, exist_ok=True)
    save_trades(result, os.path.join(args.out, "trades.csv"))
    save_equity(result, os.path.join(args.out, "equity.csv"))
    print(f"\nSaved {args.out}/trades.csv and {args.out}/equity.csv")


def cmd_fetch(argv):
    from . import coinbase
    p = argparse.ArgumentParser(prog="paper_trader fetch",
                                description="Download crypto candles from Coinbase's public API (no account needed).")
    p.add_argument("--product", default="BTC-USD")
    p.add_argument("--interval", choices=list(coinbase.INTERVALS), default="15m")
    p.add_argument("--days", type=float, default=30)
    p.add_argument("--out", default=None, help="CSV path (default: btc_15m.csv style)")
    args = p.parse_args(argv)
    out = args.out or f"{args.product.split('-')[0].lower()}_{args.interval}.csv"
    print(f"Downloading {args.days:g} days of {args.interval} {args.product} candles from Coinbase...")
    bars = coinbase.fetch(args.product, args.interval, args.days, verbose=True)
    save_csv(bars, out)
    print(f"Saved {len(bars):,} candles ({bars[0].date} → {bars[-1].date} UTC) to {out}")


def cmd_live(argv):
    from .live import run_live
    p = argparse.ArgumentParser(prog="paper_trader live",
                                description="Paper trade live on real Coinbase prices. Fake money only.")
    p.add_argument("--product", default="BTC-USD")
    p.add_argument("--interval", choices=list(MINUTES)[:-1], default="15m")
    add_strategy_args(p)
    p.add_argument("--cash", type=float, default=10_000, help="starting fake cash (new accounts only)")
    p.add_argument("--size", type=float, default=1.0)
    p.add_argument("--fee", type=float, default=CRYPTO_FEE)
    p.add_argument("--slippage", type=float, default=0.0005)
    p.add_argument("--state", default="live_state.json", help="where the fake account is saved")
    p.add_argument("--log", default="live_log.csv", help="one row per candle")
    p.add_argument("--once", action="store_true", help="check one candle and exit (for schedulers)")
    args = p.parse_args(argv)
    run_live(build_strategy(args), args.product, args.interval, args.cash, args.fee, args.slippage,
             args.size, args.state, args.log, once=args.once)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {"backtest": cmd_backtest, "fetch": cmd_fetch, "live": cmd_live}
    if argv and argv[0] in commands:
        return commands[argv.pop(0)](argv)
    return cmd_backtest(argv)


if __name__ == "__main__":
    main()
