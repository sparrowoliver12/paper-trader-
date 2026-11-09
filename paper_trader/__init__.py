"""paper-trader: a small, dependency-free paper-trading bot for learning."""
from .broker import PaperBroker
from .backtest import run
from .data import load_csv, synthetic
from .strategies import STRATEGIES

__all__ = ["PaperBroker", "run", "load_csv", "synthetic", "STRATEGIES"]
__version__ = "0.1.0"
