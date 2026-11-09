"""Read live odds for Polymarket US's 15-minute "Bitcoin Up or Down" markets.

READ-ONLY: uses Polymarket's official `polymarket-us` Python package with no
credentials, so it can see prices but cannot place orders.

    pip3 install polymarket-us

This is best-effort. Polymarket's public API isn't fully documented, so if it
can't find the current market, live mode falls back to assumed 50/50 odds and
says so. Run `python3 -m paper_trader probe` to see what the API returns.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .betting import Quote

KEYWORDS = ("bitcoin", "up or down")


def available() -> bool:
    try:
        import polymarket_us  # noqa: F401
        return True
    except ImportError:
        return False


def _client():
    from polymarket_us import PolymarketUS
    return PolymarketUS()  # no keys → public, read-only


def _items(resp, key):
    if isinstance(resp, dict):
        return resp.get(key) or resp.get("data") or []
    return list(resp or [])


def _time(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _money(x):
    """API prices may be '0.52', 0.52, or {'value': '0.52', 'currency': 'USD'}."""
    if isinstance(x, dict):
        x = x.get("value") or x.get("px")
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def current_btc_15m_event(client=None, now=None):
    """Find the open 'Bitcoin Up or Down' event whose window contains `now`."""
    client = client or _client()
    now = now or datetime.now(timezone.utc)
    best = None
    offset = 0
    for _ in range(10):  # page through active events
        events = _items(client.events.list({"limit": 100, "offset": offset, "active": True}), "events")
        if not events:
            break
        for e in events:
            title = str(e.get("title", "")).lower()
            if not all(k in title for k in KEYWORDS) or "15" not in (title + str(e.get("slug", ""))):
                continue
            start, end = _time(e.get("startTime") or e.get("startDate")), _time(e.get("endTime") or e.get("endDate"))
            if start and end and start <= now < end:
                return e
            if end and end > now and (best is None or end < _time(best.get("endTime") or best.get("endDate"))):
                best = e
        offset += len(events)
    return best


def quote(client=None) -> Quote | None:
    """Live ask prices for UP and DOWN in the current window, or None if not found."""
    client = client or _client()
    event = current_btc_15m_event(client)
    if not event:
        return None
    markets = event.get("markets") or []
    if not markets and event.get("slug"):
        full = client.events.retrieve_by_slug(event["slug"])
        markets = (full.get("event", full) if isinstance(full, dict) else {}).get("markets") or []
    up_ask = down_ask = None
    for m in markets:
        label = (str(m.get("outcome", "")) + " " + str(m.get("title", ""))).lower()
        slug = m.get("slug")
        if not slug:
            continue
        data = client.markets.bbo(slug)
        data = data.get("marketData", data) if isinstance(data, dict) else {}
        ask, bid = _money(data.get("bestAsk")), _money(data.get("bestBid"))
        if "down" in label:
            down_ask = ask if ask is not None else down_ask
            if up_ask is None and bid is not None:
                up_ask = 1 - bid
        elif "up" in label or "yes" in label:
            up_ask = ask if ask is not None else up_ask
            if down_ask is None and bid is not None:
                down_ask = 1 - bid
    if up_ask is None or down_ask is None:
        return None
    return Quote(up_ask, down_ask, f"polymarket:{event.get('slug', '?')}")


def probe() -> None:
    """Print what the public API returns, to debug the hookup."""
    if not available():
        print("The polymarket-us package isn't installed. Run:  pip3 install polymarket-us")
        return
    client = _client()
    event = current_btc_15m_event(client)
    if not event:
        print("Could not find an open 15-minute Bitcoin Up or Down event via the public API.")
        sample = _items(client.events.list({"limit": 5, "active": True}), "events")
        print("First few active events, for reference:")
        print(json.dumps(sample, indent=2, default=str)[:4000])
        return
    print("Found event:")
    print(json.dumps(event, indent=2, default=str)[:4000])
    print("\nQuote:", quote(client))
