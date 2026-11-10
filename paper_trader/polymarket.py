"""Read live odds for Polymarket US's 15-minute "Bitcoin Up or Down" markets.

READ-ONLY: uses Polymarket's official `polymarket-us` Python package with no
credentials, so it can see prices but cannot place orders.

    pip3 install polymarket-us        (needs Python 3.10+)

What the public API looks like (from a real probe):
  - events.list({"limit", "offset", "active", "closed"}) returns events OLDEST
    first; without closed=False it includes long-finished events.
  - each event has "markets"; each market has "marketSides", one with
    long=true and one with long=false, each with a "description" ("Up"/"Down")
    and a last "price". Markets also carry a "feeCoefficient".
  - markets.bbo(slug) gives bestBid / bestAsk for the market's LONG side.

If anything can't be found, live mode falls back to assumed 50/50 odds and says so.
Run `python3 -m paper_trader probe` to see what the API returns.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .betting import Quote


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


# ---------------------------------------------------------------- finding the market

def _text(e) -> str:
    parts = [str(e.get(k, "")) for k in ("title", "slug", "ticker", "seriesSlug", "category", "question")]
    tag = e.get("primaryTag") or {}
    if isinstance(tag, dict):
        parts += [str(tag.get("label", "")), str(tag.get("slug", ""))]
    for t in e.get("tags") or []:
        if isinstance(t, dict):
            parts += [str(t.get("label", "")), str(t.get("slug", ""))]
    return " ".join(parts).lower()


def looks_like_btc(e) -> bool:
    t = _text(e)
    return "btc" in t or "bitcoin" in t


def window(e):
    """(start, end) of an event's betting window, if known."""
    start = _time(e.get("startTime") or e.get("startDate"))
    end = _time(e.get("endDate") or e.get("endTime"))
    return start, end


def looks_like_btc_15m(e) -> bool:
    if not looks_like_btc(e):
        return False
    t = _text(e)
    if not ("up or down" in t or "updown" in t or "up-or-down" in t or "up-down" in t):
        return False
    start, end = window(e)
    if start and end:
        return timedelta(minutes=14) <= end - start <= timedelta(minutes=16)
    return any(s in t for s in ("15m", "15 min", "15-min"))


def scan_events(client, pages: int = 60, params: dict | None = None):
    """Yield OPEN events page by page. Stops at the end, or if the API repeats a page."""
    offset, seen = 0, set()
    for _ in range(pages):
        q = {"limit": 100, "offset": offset, "active": True, "closed": False, **(params or {})}
        events = _items(client.events.list(q), "events")
        if not events:
            return
        key = str(events[0].get("id") or events[0].get("slug"))
        if key in seen:
            return
        seen.add(key)
        yield from events
        offset += len(events)


def current_btc_15m_event(client=None, now=None):
    """Find the open 15-minute Bitcoin Up or Down event whose window contains `now`."""
    client = client or _client()
    now = now or datetime.now(timezone.utc)
    best = None
    for e in scan_events(client):
        if not looks_like_btc_15m(e):
            continue
        start, end = window(e)
        if start and end and start <= now < end:
            return e
        if end and end > now and (best is None or end < window(best)[1]):
            best = e
    return best


# ---------------------------------------------------------------- prices

def sides(market) -> tuple[str | None, str | None]:
    """Which outcome the market's long side and short side stand for ('up'/'down')."""
    long_label = short_label = None
    for s in market.get("marketSides") or []:
        d = str(s.get("description", "")).lower()
        label = "up" if "up" in d else "down" if "down" in d else None
        if s.get("long"):
            long_label = label
        else:
            short_label = label
    if long_label and not short_label:
        short_label = "down" if long_label == "up" else "up"
    return long_label, short_label


def quote_from(market, bbo) -> Quote | None:
    """Turn a market + its best bid/ask into the cost of buying UP and DOWN."""
    data = bbo.get("marketData", bbo) if isinstance(bbo, dict) else {}
    ask, bid = _money(data.get("bestAsk")), _money(data.get("bestBid"))
    long_label, _ = sides(market)
    if long_label is None or ask is None or bid is None:
        return None
    long_cost, short_cost = ask, 1 - bid  # buying the short side = selling the long side
    up, down = (long_cost, short_cost) if long_label == "up" else (short_cost, long_cost)
    if not (0 < up < 1 and 0 < down < 1):
        return None
    return Quote(round(up, 4), round(down, 4), f"polymarket:{market.get('slug', '?')}")


def fee_coefficient(event) -> float | None:
    for m in event.get("markets") or []:
        if m.get("feeCoefficient") is not None:
            return float(m["feeCoefficient"])
    return None


def quote(client=None) -> Quote | None:
    """Live ask prices for UP and DOWN in the current window, or None if not found."""
    client = client or _client()
    event = current_btc_15m_event(client)
    if not event:
        return None
    for m in event.get("markets") or []:
        if m.get("slug") and m.get("marketSides"):
            q = quote_from(m, client.markets.bbo(m["slug"]))
            if q:
                return q
    return None


# ---------------------------------------------------------------- debugging

def _short(e) -> str:
    start, end = window(e)
    return f"  - {str(e.get('title') or e.get('question'))[:60]!r}  slug={e.get('slug')}  {start} → {end}"


def probe(out_path: str = "probe_output.json") -> None:
    """Search Polymarket's public data for the 15-minute Bitcoin market and print a short summary.

    The raw details are saved to probe_output.json, so they can be shared for debugging.
    """
    if not available():
        print("The polymarket-us package isn't installed. Run:  pip3 install polymarket-us")
        return
    client = _client()
    dump: dict = {}
    print("Scanning OPEN events (this can take ~30 seconds)...")
    events = list(scan_events(client))
    btc = [e for e in events if looks_like_btc(e)]
    btc15 = [e for e in btc if looks_like_btc_15m(e)]
    cats: dict = {}
    for e in events:
        cats[e.get("category")] = cats.get(e.get("category"), 0) + 1
    print(f"Open events: {len(events)}  by category: {cats}")
    print(f"Mention Bitcoin: {len(btc)}   look like 15-minute Up/Down: {len(btc15)}")
    for e in (btc15 or btc)[:8]:
        print(_short(e))
    dump["btc_events"] = btc[:10]
    dump["categories"] = cats
    dump["sample_non_sports"] = [e for e in events if e.get("category") != "sports"][:5]

    now = datetime.now(timezone.utc)
    event = next((e for e in btc15 if window(e)[0] and window(e)[0] <= now < window(e)[1]), None) \
        or current_btc_15m_event(client)
    print("\nCurrent 15-minute Bitcoin window:", _short(event).strip() if event else "NOT FOUND")
    if event:
        dump["found_event"] = event
        fee = fee_coefficient(event)
        for m in event.get("markets") or []:
            print(f"  market {m.get('slug')}: sides={sides(m)} feeCoefficient={m.get('feeCoefficient')}")
            try:
                b = client.markets.bbo(m["slug"])
                dump.setdefault("bbo", []).append(b)
                print(f"    best bid/ask: {b}"[:300])
                print("    → odds:", quote_from(m, b))
            except Exception as ex:
                print(f"    reading odds failed: {ex}")
        if fee is not None:
            print(f"\nFee coefficient on this market: {fee}")
    with open(out_path, "w") as f:
        json.dump(dump, f, indent=2, default=str)
    print(f"\nDetails saved to {out_path}")
