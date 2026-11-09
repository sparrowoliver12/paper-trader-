"""Price data: load a CSV of bars, or generate a synthetic series for practice."""
from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


@dataclass
class Bar:
    date: str  # "2024-01-02" for daily bars, "2024-01-02 13:45" (UTC) for intraday
    close: float


def parse_time(raw: str) -> str:
    """Normalize a timestamp. Unix seconds/milliseconds become 'YYYY-MM-DD HH:MM' UTC."""
    s = raw.strip()
    try:
        x = float(s)
    except ValueError:
        return s.replace("T", " ").rstrip("Z")[:16] if "T" in s else s
    if x > 1e12:  # milliseconds
        x /= 1000
    return datetime.fromtimestamp(x, timezone.utc).strftime("%Y-%m-%d %H:%M")


def load_csv(path: str) -> list[Bar]:
    """Read a CSV with a time column (Date/Timestamp/Time/Unix) and a Close column.

    Works with Yahoo Finance, Stooq, CryptoDataDownload, exchange exports,
    and the files written by `python -m paper_trader fetch`.
    """
    bars: list[Bar] = []
    with open(path, newline="") as f:
        lines = [ln for ln in f if not ln.startswith("http")]  # CryptoDataDownload adds a URL line
    reader = csv.DictReader(lines)
    cols = {c.strip().lower(): c for c in (reader.fieldnames or [])}
    time_col = next((cols[k] for k in ("unix", "timestamp", "open time", "date", "datetime", "time") if k in cols), None)
    close_col = cols.get("adj close") or cols.get("close")
    if not time_col or not close_col:
        raise ValueError(f"{path}: need a time column and a 'Close' column, found {reader.fieldnames}")
    for row in reader:
        try:
            bars.append(Bar(parse_time(row[time_col]), float(row[close_col])))
        except (ValueError, TypeError, AttributeError):
            continue  # skip blank / 'null' rows
    bars.sort(key=lambda b: b.date)
    if not bars:
        raise ValueError(f"{path}: no usable rows")
    return bars


def save_csv(bars: list[Bar], path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Close"])
        w.writerows((b.date, b.close) for b in bars)


def synthetic(n: int = 500, start: float = 100.0, drift: float = 0.0003, vol: float = 0.015,
              seed: int | None = 42, interval_minutes: int = 1440) -> list[Bar]:
    """Random-walk prices (geometric Brownian motion).

    Daily bars skip weekends (like stocks). Intraday bars run 24/7 (like crypto).
    """
    rng = random.Random(seed)
    price, bars = start, []
    if interval_minutes >= 1440:
        d = date(2024, 1, 1)
        while len(bars) < n:
            if d.weekday() < 5:
                price *= math.exp(drift - vol * vol / 2 + vol * rng.gauss(0, 1))
                bars.append(Bar(d.isoformat(), round(price, 2)))
            d += timedelta(days=1)
    else:
        t = datetime(2024, 1, 1)
        for _ in range(n):
            price *= math.exp(drift - vol * vol / 2 + vol * rng.gauss(0, 1))
            bars.append(Bar(t.strftime("%Y-%m-%d %H:%M"), round(price, 2)))
            t += timedelta(minutes=interval_minutes)
    return bars
