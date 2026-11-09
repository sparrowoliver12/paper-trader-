"""Price data: load a CSV of daily bars, or generate a synthetic series for practice."""
from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class Bar:
    date: str
    close: float


def load_csv(path: str) -> list[Bar]:
    """Read a CSV with a Date column and a Close (or Adj Close) column.

    Works with the files Yahoo Finance / Stooq / most brokers export.
    """
    bars: list[Bar] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        cols = {c.strip().lower(): c for c in (reader.fieldnames or [])}
        date_col = cols.get("date") or cols.get("timestamp")
        close_col = cols.get("adj close") or cols.get("close")
        if not date_col or not close_col:
            raise ValueError(f"{path}: need 'Date' and 'Close' columns, found {reader.fieldnames}")
        for row in reader:
            try:
                bars.append(Bar(row[date_col].strip(), float(row[close_col])))
            except (ValueError, TypeError):
                continue  # skip blank / 'null' rows
    bars.sort(key=lambda b: b.date)
    if not bars:
        raise ValueError(f"{path}: no usable rows")
    return bars


def synthetic(days: int = 500, start: float = 100.0, drift: float = 0.0003,
              vol: float = 0.015, seed: int | None = 42) -> list[Bar]:
    """Random-walk prices (geometric Brownian motion) on weekdays."""
    rng = random.Random(seed)
    d, price, bars = date(2024, 1, 1), start, []
    while len(bars) < days:
        if d.weekday() < 5:
            price *= math.exp(drift - vol * vol / 2 + vol * rng.gauss(0, 1))
            bars.append(Bar(d.isoformat(), round(price, 2)))
        d += timedelta(days=1)
    return bars
