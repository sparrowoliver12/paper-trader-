"""Download historical crypto candles from Coinbase's free public market-data API.

Read-only price data: no account, no API key, no trading.
"""
from __future__ import annotations

import json
import ssl
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .data import Bar

API = "https://api.exchange.coinbase.com/products/{product}/candles"
INTERVALS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "1d": 86400}
MAX_PER_REQUEST = 299  # Coinbase rejects ranges over 300 candles; stay one under (start/end are inclusive)


def seconds(interval: str) -> int:
    if interval not in INTERVALS:
        raise ValueError(f"interval must be one of {', '.join(INTERVALS)}")
    return INTERVALS[interval]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_candles(rows: list, granularity: int, now: float | None = None) -> list[Bar]:
    """Coinbase rows are [time, low, high, open, close, volume], newest first.

    Drops the candle that is still forming, so we only ever act on finished bars.
    """
    now = time.time() if now is None else now
    out = {}
    for r in rows:
        start = int(r[0])
        if start + granularity <= now:
            out[start] = Bar(datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%d %H:%M"), float(r[4]), float(r[3]))
    return [out[k] for k in sorted(out)]


def fetch(product: str = "BTC-USD", interval: str = "15m", days: float = 30,
          pause: float = 0.35, verbose: bool = False) -> list[Bar]:
    g = seconds(interval)
    end = time.time()
    t = end - days * 86400
    raw: list = []
    while t < end:
        chunk_end = min(t + MAX_PER_REQUEST * g, end)
        url = f"{API.format(product=product)}?granularity={g}&start={_iso(t)}&end={_iso(chunk_end)}"
        raw.extend(_get(url))
        if verbose:
            print(f"  fetched through {_iso(chunk_end)}", flush=True)
        t = chunk_end
        time.sleep(pause)  # stay well under Coinbase's public rate limit
    return parse_candles(raw, g, now=end)


def _ssl_context():
    """Use certifi's certificates when available.

    Python from python.org on macOS ships without system certificates, which
    causes CERTIFICATE_VERIFY_FAILED. certifi (installed alongside polymarket-us)
    fixes that without the user running "Install Certificates.command".
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_CTX = None


def _get(url: str, retries: int = 3) -> list:
    global _CTX
    if _CTX is None:
        _CTX = _ssl_context()
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "paper-trader/0.2", "Accept": "application/json"})
            with urlopen(req, timeout=20, context=_CTX) as resp:
                data = json.load(resp)
            if isinstance(data, dict):  # error payload, e.g. {"message": "..."}
                raise RuntimeError(f"Coinbase error: {data.get('message', data)}")
            return data
        except (HTTPError, URLError, TimeoutError) as e:
            if "CERTIFICATE_VERIFY_FAILED" in str(e):
                raise RuntimeError(
                    "Security certificate error. Fix: run  pip3 install certifi  then start the robot again.") from e
            if attempt == retries - 1:
                raise RuntimeError(f"Could not reach Coinbase ({e}). Check your internet connection.") from e
            time.sleep(2 * (attempt + 1))
    return []
