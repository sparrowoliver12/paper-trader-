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

## Polymarket-style 15-minute "Bitcoin Up or Down" betting (paper)

Prediction markets such as Polymarket US run a new market every 15 minutes: *will BTC end this window at or above where it started?* A winning share pays **$1**. You buy UP or DOWN at the market price, for example 51¢.

This mode **paper bets** on those windows: fake money, no account, no orders.

**1. Get real 15-minute BTC data**, then backtest a model on it:

```bash
python3 -m paper_trader fetch --days 60
python3 -m paper_trader bet --csv btc_15m.csv --model momentum --compare
python3 -m paper_trader bet --csv btc_15m.csv --model reversion
python3 -m paper_trader bet --csv btc_15m.csv --model rsi
```

**2. Run it live:**

```bash
pip3 install polymarket-us        # optional: real Polymarket odds (read-only, no account)
python3 -m paper_trader probe     # check the odds hookup works
python3 -m paper_trader bet-live --model reversion
```

Every 15 minutes it settles the last fake bet, predicts the new window, and bets if the model sees an edge:

```
[2026-11-09 18:30 UTC] BTC $xx,xxx | model 53% up | UP 51¢ / DOWN 51¢ (assumed) | no edge, skip
[2026-11-09 18:45 UTC] BTC $xx,xxx | model 56% up | UP 51¢ / DOWN 51¢ (assumed) | BET UP 19.0 sh @ 51¢ = $10.00
  settled 2026-11-09 18:45: bet UP, BTC went DOWN → LOST $-10.00   bankroll $990.00
```

State is saved in `bet_state.json` (Ctrl+C, then rerun to resume). Every settled bet goes to `bet_log.csv`.

### How it decides

- A **model** estimates the chance BTC goes up this window. `momentum` leans the way the last few windows went, `reversion` leans the other way, `rsi` uses the RSI indicator, and `coin` always says 50% (so it never bets).
- **Edge** = model's probability − price − fee. It bets only when edge > `--min-edge`.
- **Fee**: `--fee-rate 0.07` charges 0.07 × price × (1 − price) per share, which is 1.75¢ at 50¢. **Check what your app actually charges** and set this to match (0 if it's free).

### Reading the results

The number that matters is **Win rate vs Break-even rate**. At ~51¢ plus fees, you must win about **52–53%** of bets just to break even. **Brier score** measures how good the probabilities are: 0.2500 is a coin flip, and anything not clearly below that has no real predictive power.

### Honest caveats

- Over 15 minutes, Bitcoin's direction is very close to random, and these markets are full of fast professional bots. Most people who bet on them lose money over time.
- Backtests assume 50/50 odds with a spread, because historical Polymarket order books aren't freely available. Real odds move with the market, which usually makes edges *smaller* than the backtest shows.
- BTC prices here come from Coinbase. Polymarket US settles on CF Benchmarks' BRTI index (an average over the last 60 seconds), so a window that barely moves can resolve differently.
- Live mode uses each market's own fee coefficient (0.095 on the 15-minute BTC markets when last checked). Backtests use `--fee-rate`, so pass `--fee-rate 0.095` to match.
- The Polymarket odds hookup is read-only and best-effort. If it can't find the current market, it says so and falls back to assumed odds.
- Run it for a few weeks and hundreds of bets before trusting a result. Even then, a backtest that wins is not proof the strategy will win with real money.

## 15-minute Bitcoin (trading, not betting)

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
