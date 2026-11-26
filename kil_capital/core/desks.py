"""Series -> desk / category / league / asset tagging (spec v4 §3.1).

Desk comes from the series-ticker prefix, with a fallback to Kalshi's category.
"""
from __future__ import annotations

DESKS = ("MLB", "NBA", "NFL", "NHL", "CFB", "CBB", "SPORTS-OTHER",
         "CRYPTO", "ECON", "WEATHER", "POLITICS", "OTHER", "PM-CARSON")

# Longest prefix wins.
_PREFIX = {
    "KXMLB": "MLB",
    "KXNBA": "NBA", "KXWNBA": "SPORTS-OTHER",
    "KXNFL": "NFL", "KXSB": "NFL",
    "KXNHL": "NHL", "KXSTANLEY": "NHL",
    "KXNCAAF": "CFB", "KXCFB": "CFB", "KXHEISMAN": "CFB",
    "KXNCAAMB": "CBB", "KXNCAAWB": "CBB", "KXNCAAB": "CBB", "KXMARMAD": "CBB", "KXCBB": "CBB",
    "KXEPL": "SPORTS-OTHER", "KXUCL": "SPORTS-OTHER", "KXMLS": "SPORTS-OTHER", "KXLALIGA": "SPORTS-OTHER",
    "KXSERIEA": "SPORTS-OTHER", "KXBUNDES": "SPORTS-OTHER", "KXFIFA": "SPORTS-OTHER", "KXWC": "SPORTS-OTHER",
    "KXATP": "SPORTS-OTHER", "KXWTA": "SPORTS-OTHER", "KXPGA": "SPORTS-OTHER", "KXGOLF": "SPORTS-OTHER",
    "KXUFC": "SPORTS-OTHER", "KXF1": "SPORTS-OTHER", "KXNASCAR": "SPORTS-OTHER", "KXBOX": "SPORTS-OTHER",
    "KXBTC": "CRYPTO", "KXETH": "CRYPTO", "KXSOL": "CRYPTO", "KXXRP": "CRYPTO", "KXDOGE": "CRYPTO",
    "KXHYPE": "CRYPTO", "KXSHIBA": "CRYPTO", "KXCRYPTO": "CRYPTO",
    "KXCPI": "ECON", "KXFED": "ECON", "KXGDP": "ECON", "KXPAYROLLS": "ECON", "KXU3": "ECON",
    "KXJOBLESS": "ECON", "KXINX": "ECON", "KXNASDAQ": "ECON", "KXAAAGAS": "ECON", "KXPCE": "ECON",
    "KXRATECUT": "ECON", "KXTSA": "ECON",
    "KXHIGH": "WEATHER", "KXLOW": "WEATHER", "KXRAIN": "WEATHER", "KXSNOW": "WEATHER", "KXHURR": "WEATHER",
    "KXTEMP": "WEATHER",
    "KXPRES": "POLITICS", "KXSENATE": "POLITICS", "KXHOUSE": "POLITICS", "KXGOV": "POLITICS",
    "KXTRUMP": "POLITICS", "KXMENTION": "POLITICS", "KXELON": "POLITICS",
}

_CATEGORY = {
    "sports": "SPORTS-OTHER", "crypto": "CRYPTO", "economics": "ECON", "financials": "ECON",
    "climate and weather": "WEATHER", "weather": "WEATHER", "politics": "POLITICS",
    "elections": "POLITICS", "world": "POLITICS", "culture": "POLITICS", "mentions": "POLITICS",
    "entertainment": "OTHER", "science and technology": "OTHER", "companies": "OTHER",
    "health": "OTHER", "transportation": "OTHER",
}

SPORTS_DESKS = {"MLB", "NBA", "NFL", "NHL", "CFB", "CBB", "SPORTS-OTHER"}
_ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE", "HYPE", "SHIBA")


def desk_for(series_ticker: str | None, category: str | None = None) -> str:
    s = (series_ticker or "").upper()
    best, blen = None, 0
    for pre, desk in _PREFIX.items():
        if s.startswith(pre) and len(pre) > blen:
            best, blen = desk, len(pre)
    if best:
        return best
    return _CATEGORY.get((category or "").strip().lower(), "OTHER")


def league_for(series_ticker: str | None, desk: str) -> str | None:
    if desk not in SPORTS_DESKS:
        return None
    if desk != "SPORTS-OTHER":
        return desk
    s = (series_ticker or "").upper()
    return s[2:].split("GAME")[0][:8] if s.startswith("KX") else s[:8] or None


def asset_for(series_ticker: str | None, desk: str) -> str | None:
    if desk != "CRYPTO":
        return None
    s = (series_ticker or "").upper()[2:]
    for a in _ASSETS:
        if s.startswith(a):
            return a
    return None


def tags(series_ticker: str | None, category: str | None = None) -> dict:
    d = desk_for(series_ticker, category)
    return {"desk": d, "category": (category or d), "league": league_for(series_ticker, d),
            "asset": asset_for(series_ticker, d)}


def series_of(ticker: str) -> str:
    """Best-effort series from a market ticker (KXMLBGAME-26NOV24... -> KXMLBGAME)."""
    return (ticker or "").split("-")[0]


def event_of(ticker: str) -> str:
    parts = (ticker or "").split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else ticker
