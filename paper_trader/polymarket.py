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


def _text(e) -> str:
    return " ".join(str(e.get(k, "")) for k in ("title", "slug", "ticker", "identifier", "description", "category")).lower()


def looks_like_btc(e) -> bool:
    t = _text(e)
    return "btc" in t or "bitcoin" in t


def looks_like_btc_15m(e) -> bool:
    t = _text(e)
    return looks_like_btc(e) and ("up or down" in t or "updown" in t or "up-or-down" in t) and "15" in t


def scan_events(client, pages: int = 20, params: dict | None = None):
    """Yield active events page by page. Stops if the API repeats a page (ignores offset)."""
    offset, seen = 0, set()
    for _ in range(pages):
        q = {"limit": 100, "offset": offset, "active": True, **(params or {})}
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
    """Find the open 'Bitcoin Up or Down' 15-minute event whose window contains `now`."""
    client = client or _client()
    now = now or datetime.now(timezone.utc)
    best = None
    for e in scan_events(client):
        if not looks_like_btc_15m(e):
            continue
        start, end = _time(e.get("startTime") or e.get("startDate")), _time(e.get("endTime") or e.get("endDate"))
        if start and end and start <= now < end:
            return e
        if end and end > now and (best is None or end < _time(best.get("endTime") or best.get("endDate"))):
            best = e
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


def _short(e) -> str:
    when = e.get("startTime") or e.get("startDate") or "?"
    return f"  - {str(e.get('title'))[:70]!r}  slug={e.get('slug')}  start={when}"


def probe(out_path: str = "probe_output.json") -> None:
    """Search Polymarket's public data for Bitcoin markets and print a short summary.

    The full raw data is saved to probe_output.json, so it can be shared for debugging.
    """
    if not available():
        print("The polymarket-us package isn't installed. Run:  pip3 install polymarket-us")
        return
    client = _client()
    dump: dict = {}

    print("Scanning active events...")
    events = list(scan_events(client))
    btc = [e for e in events if looks_like_btc(e)]
    print(f"Scanned {len(events)} active events; {len(btc)} mention Bitcoin/BTC.")
    for e in btc[:15]:
        print(_short(e))
    dump["btc_events"] = btc[:20]
    dump["first_event_keys"] = sorted(events[0].keys()) if events else []

    for params in ({"category": "crypto"}, {"tag": "crypto"}, {"search": "bitcoin"}, {"query": "bitcoin"}):
        try:
            got = _items(client.events.list({"limit": 50, "active": True, **params}), "events")
            hits = [e for e in got if looks_like_btc(e)]
            print(f"Filter {params}: {len(got)} events, {len(hits)} Bitcoin")
            for e in hits[:5]:
                print(_short(e))
            dump[f"filter_{list(params.items())[0][0]}"] = got[:10]
        except Exception as ex:  # unsupported filter
            print(f"Filter {params}: not supported ({type(ex).__name__})")

    try:
        markets = _items(client.markets.list({"limit": 100, "active": True}), "markets")
        mb = [m for m in markets if looks_like_btc(m)]
        print(f"Markets list: {len(markets)} markets, {len(mb)} Bitcoin")
        for m in mb[:5]:
            print(_short(m))
        dump["btc_markets"] = mb[:10]
        dump["first_market"] = markets[:1]
    except Exception as ex:
        print(f"Markets list failed: {ex}")

    event = current_btc_15m_event(client)
    print("\n15-minute Bitcoin event found:", _short(event) if event else "NO")
    if event:
        dump["found_event"] = event
        try:
            print("Live odds:", quote(client))
        except Exception as ex:
            print(f"Found the event but reading odds failed: {ex}")

    with open(out_path, "w") as f:
        json.dump(dump, f, indent=2, default=str)
    print(f"\nFull details saved to {out_path}")
