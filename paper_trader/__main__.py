"""Command line: python -m paper_trader --help"""
from __future__ import annotations

import argparse
import os

from .backtest import run, save_equity, save_trades
from .data import load_csv, synthetic
from .strategies import STRATEGIES, SmaCrossover, RsiMeanReversion


def build_strategy(args):
    if args.strategy == "sma":
        return SmaCrossover(args.fast, args.slow)
    if args.strategy == "rsi":
        return RsiMeanReversion(args.rsi_period, args.rsi_low, args.rsi_high)
    return STRATEGIES[args.strategy]()


def main(argv=None):
    p = argparse.ArgumentParser(prog="paper_trader", description="Backtest a strategy with fake money.")
    p.add_argument("--csv", help="CSV of daily prices (Date, Close). Omit to use synthetic data.")
    p.add_argument("--symbol", default="SYM")
    p.add_argument("--strategy", choices=sorted(STRATEGIES), default="sma")
    p.add_argument("--cash", type=float, default=10_000)
    p.add_argument("--size", type=float, default=1.0, help="fraction of cash per buy (0-1)")
    p.add_argument("--fee", type=float, default=0.0, help="fee as a fraction, e.g. 0.001")
    p.add_argument("--slippage", type=float, default=0.0005)
    p.add_argument("--fast", type=int, default=10)
    p.add_argument("--slow", type=int, default=30)
    p.add_argument("--rsi-period", type=int, default=14)
    p.add_argument("--rsi-low", type=float, default=30)
    p.add_argument("--rsi-high", type=float, default=70)
    p.add_argument("--days", type=int, default=500, help="synthetic data length")
    p.add_argument("--seed", type=int, default=42, help="synthetic data seed")
    p.add_argument("--compare", action="store_true", help="also show buy-and-hold for comparison")
    p.add_argument("--out", default="results", help="folder for trades.csv and equity.csv")
    args = p.parse_args(argv)

    bars = load_csv(args.csv) if args.csv else synthetic(args.days, seed=args.seed)
    source = args.csv or f"synthetic ({args.days} days, seed {args.seed})"
    print(f"Data: {source}  |  {bars[0].date} → {bars[-1].date}  |  PAPER MONEY ONLY\n")

    kwargs = dict(symbol=args.symbol, cash=args.cash, position_size=args.size,
                  fee_pct=args.fee, slippage_pct=args.slippage)
    result = run(bars, build_strategy(args), **kwargs)
    print(f"Strategy: {args.strategy}")
    print(result.summary())

    if args.compare and args.strategy != "hold":
        print("\nBaseline: buy and hold")
        print(run(bars, STRATEGIES["hold"](), **kwargs).summary())

    os.makedirs(args.out, exist_ok=True)
    save_trades(result, os.path.join(args.out, "trades.csv"))
    save_equity(result, os.path.join(args.out, "equity.csv"))
    print(f"\nSaved {args.out}/trades.csv and {args.out}/equity.csv")


if __name__ == "__main__":
    main()
