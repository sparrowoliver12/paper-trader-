# paper-trader

A small trading bot that trades **fake money only**. It never connects to a real brokerage account. Use it to test trading ideas against historical prices and see how they would have done, without risking anything.

Pure Python 3.10+, no packages to install.

## Quick start

```bash
# Backtest the default strategy on made-up (synthetic) prices
python -m paper_trader --compare

# Try a different strategy
python -m paper_trader --strategy rsi --compare

# Use real historical prices from a CSV
python -m paper_trader --csv AAPL.csv --symbol AAPL --compare
```

`--compare` also runs **buy-and-hold** on the same data. That's the bar to beat: if a strategy can't outperform just buying and waiting, it isn't adding value.

Results (every trade, plus your daily account value) are saved to `results/trades.csv` and `results/equity.csv`, which open in Excel or Google Sheets.

## 15-minute Bitcoin

Three commands. All use **fake money**. Prices come from Coinbase's free public market data, with no account or API key needed.

**1. Download real 15-minute BTC prices** (60 days ≈ 5,760 candles, takes ~10 seconds):

```bash
python3 -m paper_trader fetch --product BTC-USD --interval 15m --days 60
```

This writes `btc_15m.csv`.

**2. Backtest on them:**

```bash
python3 -m paper_trader --market crypto --csv btc_15m.csv --compare
python3 -m paper_trader --market crypto --csv btc_15m.csv --strategy rsi --compare
```

`--market crypto` turns on fractional BTC (e.g. 0.0312 BTC), 24/7 math for the stats, and a **0.6% fee per trade** by default, about what a small account pays as a taker fee on a crypto exchange. Set your real fee with `--fee` (0.006 = 0.6%). The output shows total **Fees paid**: watch that number. On 15-minute bars, fees are usually what kills a strategy.

**3. Run it live:**

```bash
python3 -m paper_trader live --strategy rsi
```

Every 15 minutes, just after a candle closes, it fetches the latest real BTC price, asks the strategy what to do, and makes a fake trade. It prints a line each time:

```
[2026-11-09 18:15 UTC] BTC $xx,xxx.xx | BUY 0.105432 @ $xx,xxx.xx | equity $9,940.00 (-0.60%)
```

- Your fake account is saved to `live_state.json`. Stop with **Ctrl+C**, then run the same command later to resume where you left off.
- Every candle is logged to `live_log.csv`, which opens in Excel or Google Sheets.
- To start over with fresh fake cash, delete `live_state.json`.
- It only trades while the command is running, so your computer has to stay awake. To run it 24/7, put it on an always-on machine such as a Raspberry Pi or a cheap cloud server. Alternatively, run `live --once` from a scheduler every 15 minutes.

Strategy settings are in *bars*, not days. On 15-minute data, `--fast 10 --slow 30` means 2.5 hours vs 7.5 hours.

## Getting real stock price data

Download daily prices as a CSV from Yahoo Finance (search a ticker → *Historical Data* → *Download*) or from stooq.com. Any CSV with a `Date` column and a `Close` (or `Adj Close`) column works.

## Strategies included

| Name   | Idea |
|--------|------|
| `sma`  | **Moving-average crossover.** Buy when the 10-day average price rises above the 30-day average (momentum turning up), sell when it drops back below. Tune with `--fast` / `--slow`. |
| `rsi`  | **RSI mean reversion.** RSI measures how hard a price has been pushed recently (0–100). Buy when it's below 30 ("oversold"), sell above 70 ("overbought"). Tune with `--rsi-low` / `--rsi-high` / `--rsi-period`. |
| `hold` | **Buy and hold.** Buy on day one, never sell. The baseline. |

## Reading the results

- **Total return** – how much the fake account grew or shrank.
- **Max drawdown** – the worst drop from a high point. A 20% drawdown means at some point you were down 20% from your peak. Lower is easier to stomach.
- **Sharpe** – return relative to how bumpy the ride was. Above 1 is decent; above 2 is rare and worth being suspicious of.
- **Win rate** – share of closed trades that made money. A high win rate doesn't mean a strategy is good if the losers are big.

## Other options

```
--cash 10000      starting fake cash
--size 0.5        spend 50% of cash per buy instead of 100%
--fee 0.001       0.1% fee per trade
--slippage 0.0005 fills are 0.05% worse than the quoted price (realistic)
--days / --seed   length and randomness of synthetic data
--out folder      where to write the CSVs
```

## Writing your own strategy

Open `paper_trader/strategies.py`, copy one of the classes, and change `signal()`. It receives the list of closing prices so far and whether you currently hold shares, and returns `"buy"`, `"sell"`, or `None`. Add your class to `STRATEGIES` at the bottom and it shows up as a `--strategy` option.

```python
class MyIdea(Strategy):
    name = "mine"

    def signal(self, closes, holding):
        if not holding and closes[-1] < closes[-2] < closes[-3]:
            return "buy"     # three down days in a row
        if holding and closes[-1] > closes[-2]:
            return "sell"
        return None
```

## Honest caveats

- Past performance on a backtest is a weak predictor of the future. It's easy to tune settings until a strategy looks great on one dataset ("overfitting") and then watch it fail on new data. Test on several tickers and time periods.
- Synthetic data is random, so a strategy "winning" on it is luck. It's there to check the plumbing works.
- The simulator fills orders at the daily close, allows whole shares only, and has no shorting, dividends, or taxes.

## Tests

```bash
python -m unittest discover -s tests
```
