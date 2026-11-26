"""Market blocklist (spec v4 §2.4).  Currently EMPTY: the Mississippi State block was lifted 2026-11-26.

There is deliberately NO setting, env var, flag or reload that turns this off.  The term
lists are module-level tuples (immutable) and `is_enabled()` always returns True.

Over-blocking is acceptable; under-blocking is not.  Ambiguous "MSU" hits are blocked and
recorded via `review_log` for Carson to look at.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping

REASON = "BLOCKLIST"

# Carson lifted the Mississippi State block on 2026-11-26 (he is not connected to any NCAA athletics
# program).  The machinery stays so a team or term can be blocked again by adding it here.
ALWAYS_BLOCKED: tuple[str, ...] = ()

# Fields matched on markets / events / series (§2.4).
TEXT_FIELDS: tuple[str, ...] = (
    "series_ticker", "event_ticker", "ticker", "title", "subtitle", "sub_title",
    "yes_sub_title", "no_sub_title", "rules_primary", "rules_secondary",
    "category", "competition", "team", "teams", "participants", "participant",
    "home_team", "away_team", "player", "name", "description", "product_metadata",
    "custom_strike", "mutually_exclusive_side",
)

_norm_re = re.compile(r"[^a-z0-9]+")
_msu_re = re.compile(r"\bmsu\b")
# Ticker codes concatenate team codes (e.g. ...-26NOV28MSSTOLE), so match MSST as a raw
# substring.  [VERIFY] Kalshi's team code for Mississippi State on each league's series.
_TICKER_CODES: tuple[str, ...] = ()


def _norm(s: str) -> str:
    return " " + _norm_re.sub(" ", s.lower()).strip() + " "


def is_enabled() -> bool:  # the block cannot be disabled
    return True


@dataclass
class Verdict:
    blocked: bool
    reason: str = ""
    term: str = ""
    ambiguous: bool = False


@dataclass
class ReviewLog:
    items: list = field(default_factory=list)

    def add(self, text: str, term: str):
        self.items.append({"text": text[:300], "term": term})
        del self.items[:-500]


review_log = ReviewLog()


def check_text(text: str) -> Verdict:
    if not text:
        return Verdict(False)
    raw = str(text)
    n = _norm(raw)
    for term in ALWAYS_BLOCKED:
        t = _norm(term)
        if t.strip() and t in n:
            return Verdict(True, REASON, term)
    up = raw.upper()
    for code in _TICKER_CODES:
        if code in up:
            return Verdict(True, REASON, code)
    return Verdict(False)


def _flatten(v) -> Iterable[str]:
    if v is None:
        return
    if isinstance(v, str):
        yield v
    elif isinstance(v, Mapping):
        for x in v.values():
            yield from _flatten(x)
    elif isinstance(v, (list, tuple, set)):
        for x in v:
            yield from _flatten(x)
    else:
        yield str(v)


def market_text(obj: Mapping) -> str:
    parts = []
    for f in TEXT_FIELDS:
        if f in obj:
            parts.extend(_flatten(obj[f]))
    # combo / RFQ legs: every leg is checked (§2.4)
    for legkey in ("legs", "mve_selected_legs", "selected_markets", "markets"):
        if legkey in obj:
            for leg in obj[legkey] or []:
                if isinstance(leg, Mapping):
                    parts.append(market_text(leg))
                else:
                    parts.extend(_flatten(leg))
    return " | ".join(parts)


def check_market(obj: Mapping) -> Verdict:
    return check_text(market_text(obj))


def is_blocked(obj_or_text) -> bool:
    if isinstance(obj_or_text, Mapping):
        return check_market(obj_or_text).blocked
    return check_text(str(obj_or_text)).blocked


def event_excluded(markets: Iterable[Mapping], event: Mapping | None = None) -> bool:
    """Whole-event exclusion: complete-set / arbitrage strategies skip the whole event if
    any leg (outcome) is blocked, and SEC-champion events with MSU as an outcome are excluded."""
    if event and check_market(event).blocked:
        return True
    return any(check_market(m).blocked for m in markets)


def filter_markets(markets: Iterable[Mapping]) -> list:
    return [m for m in markets if not check_market(m).blocked]
