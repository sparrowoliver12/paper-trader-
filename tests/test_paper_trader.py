import os
import tempfile
import unittest

from paper_trader import PaperBroker, run, synthetic, load_csv
from paper_trader.data import Bar
from paper_trader.strategies import BuyAndHold, SmaCrossover, RsiMeanReversion, rsi


class BrokerTests(unittest.TestCase):
    def test_round_trip_profit(self):
        b = PaperBroker(cash=1000, slippage_pct=0)
        b.buy("X", 10, 50)
        self.assertAlmostEqual(b.cash, 500)
        b.sell("X", 10, 60)
        self.assertAlmostEqual(b.cash, 1100)
        self.assertAlmostEqual(b.realized_pnl, 100)

    def test_cannot_overspend_or_short(self):
        b = PaperBroker(cash=100, slippage_pct=0)
        with self.assertRaises(ValueError):
            b.buy("X", 10, 50)
        with self.assertRaises(ValueError):
            b.sell("X", 1, 50)

    def test_fees_and_slippage_cost_money(self):
        b = PaperBroker(cash=1000, fee_pct=0.01, slippage_pct=0.01)
        b.buy("X", 5, 100)
        b.sell("X", 5, 100)
        self.assertLess(b.cash, 1000)

    def test_avg_cost(self):
        b = PaperBroker(cash=10_000, slippage_pct=0)
        b.buy("X", 10, 100)
        b.buy("X", 10, 200)
        self.assertAlmostEqual(b.position("X").avg_cost, 150)


class StrategyTests(unittest.TestCase):
    def test_sma_buys_on_uptrend_turn(self):
        closes = [100 - i for i in range(30)] + [70 + 3 * i for i in range(15)]
        s, sigs = SmaCrossover(3, 10), []
        for i in range(1, len(closes) + 1):
            sigs.append(s.signal(closes[:i], holding=False))
        self.assertIn("buy", sigs)

    def test_rsi_extremes(self):
        self.assertEqual(rsi([float(i) for i in range(20)]), 100.0)
        self.assertLess(rsi([float(20 - i) for i in range(20)]), 1)
        self.assertEqual(RsiMeanReversion().signal([float(20 - i) for i in range(20)], False), "buy")


class BacktestTests(unittest.TestCase):
    def test_hold_tracks_price(self):
        bars = [Bar(f"2024-01-{d:02d}", p) for d, p in [(1, 100), (2, 110), (3, 120)]]
        r = run(bars, BuyAndHold(), cash=1000, slippage_pct=0)
        self.assertAlmostEqual(r.total_return, 0.2)
        self.assertEqual(r.num_trades, 1)

    def test_synthetic_is_reproducible(self):
        self.assertEqual(synthetic(50, seed=1), synthetic(50, seed=1))

    def test_full_run_never_negative_cash(self):
        r = run(synthetic(400, seed=7), SmaCrossover())
        self.assertGreaterEqual(r.broker.cash, 0)
        self.assertGreater(r.end_equity, 0)

    def test_load_csv(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p.csv")
            with open(path, "w") as f:
                f.write("Date,Open,High,Low,Close,Adj Close,Volume\n"
                        "2024-01-03,1,1,1,11,10.5,100\n2024-01-02,1,1,1,10,9.5,100\n2024-01-04,null,,,,null,\n")
            bars = load_csv(path)
            self.assertEqual([b.close for b in bars], [9.5, 10.5])


if __name__ == "__main__":
    unittest.main()
