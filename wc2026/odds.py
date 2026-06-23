"""Betting-odds layer: an alternate strength model for the Monte-Carlo engine.

The default simulation weights teams by their FIFA ranking (see analysis._lambdas).
This module supplies the *other* mode the user asked for: weighting by **pre-match
betting odds** — 1X2 (home / draw / away) odds for the remaining group fixtures, and
**tournament outright-winner** odds used wherever a specific match price isn't
available (notably the entire knockout stage).

Sources, in priority order:
  1. A local ``betting_odds.json`` (hand-entered, or cached from a previous fetch).
  2. The Odds API (https://the-odds-api.com), free tier, if an API key is supplied:
       - 1X2 prices:  sport ``soccer_fifa_world_cup``         market ``h2h``
       - outrights:   sport ``soccer_fifa_world_cup_winner``  market ``outrights``

Only UNPLAYED matches are ever simulated, so we only ever need odds for upcoming
fixtures — pre-match prices for games already played are irrelevant to the sim.

File shape (decimal odds, as printed on a sportsbook; we de-vig in code):
    {
      "matches":   {"Spain vs Curaçao": {"home": 1.12, "draw": 8.5, "away": 21.0}, ...},
      "outrights": {"Argentina": 4.5, "Spain": 5.0, ...},
      "fetched":   "2026-06-21T12:00:00Z"          # optional provenance
    }
Keys use the SAME team names as the match feed (football-data.org). A manual file
should therefore spell teams the way the app does ("United States", "Czechia", ...).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional

ODDS_API_BASE = "https://api.the-odds-api.com/v4"
SPORT_MATCH = "soccer_fifa_world_cup"
SPORT_WINNER = "soccer_fifa_world_cup_winner"

# The Odds API spells a few nations differently from football-data.org. Map the
# ALTERNATIVE provider spelling -> the match-feed name so prices line up. Only add
# entries whose key differs from the feed name (never rewrite a correct name).
# Values are the exact football-data.org spellings used in cache.json.
NAME_ALIASES = {
    "usa": "United States",
    "united states of america": "United States",
    "korea republic": "South Korea",
    "republic of korea": "South Korea",
    "cote divoire": "Ivory Coast",        # accent stripped by _norm
    "cote d ivoire": "Ivory Coast",
    "czech republic": "Czechia",
    "curacao": "Curaçao",                 # accent stripped by _norm
    "cape verde": "Cape Verde Islands",
    "dr congo": "Congo DR",
    "democratic republic of congo": "Congo DR",
    "congo dr": "Congo DR",
    "bosnia and herzegovina": "Bosnia-Herzegovina",
    "bosnia herzegovina": "Bosnia-Herzegovina",      # provider uses "Bosnia & Herzegovina"
    "turkiye": "Turkey",
}


# ---------------------------------------------------------------------------
# de-vig helpers  (strip the bookmaker margin so probabilities sum to 1)
# ---------------------------------------------------------------------------
def devig_1x2(home: float, draw: float, away: float) -> dict:
    """Decimal 1X2 odds -> de-vigged {'H','D','A'} probabilities summing to 1."""
    raw = {"H": 1.0 / home, "D": 1.0 / draw, "A": 1.0 / away}
    tot = sum(raw.values())
    return {k: v / tot for k, v in raw.items()}


def devig_outrights(odds: dict) -> dict:
    """{team: decimal outright odds} -> {team: implied win-cup probability}.

    The book's outright market overrounds heavily (sum of 1/odds ≫ 1 across a
    48-team field); normalising to 1 turns it into a usable strength rating."""
    raw = {t: 1.0 / o for t, o in odds.items() if o and o > 1}
    tot = sum(raw.values()) or 1.0
    return {t: v / tot for t, v in raw.items()}


# ---------------------------------------------------------------------------
# local file
# ---------------------------------------------------------------------------
def load_odds(path: str) -> dict:
    """Load a betting_odds.json into the normalised in-memory shape the engine
    consumes:  {'matches': {'Home vs Away': {'H','D','A'}}, 'outrights_strength':
    {team: prob}, 'fetched': iso|None}.  Returns empty dict-of-dicts if absent."""
    if not path or not os.path.exists(path):
        return {"matches": {}, "outrights_strength": {}, "fetched": None}
    with open(path) as fh:
        raw = json.load(fh)
    return _normalise(raw)


def _normalise(raw: dict) -> dict:
    matches = {}
    for key, o in (raw.get("matches") or {}).items():
        try:
            matches[key] = devig_1x2(o["home"], o["draw"], o["away"])
        except (KeyError, TypeError, ZeroDivisionError):
            continue
    strength = devig_outrights(raw.get("outrights") or {})
    return {"matches": matches, "outrights_strength": strength,
            "fetched": raw.get("fetched")}


def save_odds(path: str, raw: dict) -> None:
    """Persist the *raw* (decimal-odds) shape, stamping a fetch time."""
    raw = dict(raw)
    raw.setdefault("fetched", datetime.now(timezone.utc).isoformat())
    with open(path, "w") as fh:
        json.dump(raw, fh, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# team-name resolution (odds feed -> match feed)
# ---------------------------------------------------------------------------
def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", (name or "").lower())).strip()


def resolve_team(name: str, teams: list[str]) -> Optional[str]:
    """Map an odds-provider team name onto one of the match-feed `teams`."""
    n = _norm(name)
    if n in NAME_ALIASES:
        name = NAME_ALIASES[n]
        n = _norm(name)
    by_norm = {_norm(t): t for t in teams}
    if n in by_norm:
        return by_norm[n]
    for t in teams:                              # substring either direction
        nt = _norm(t)
        if n and (n in nt or nt in n):
            return t
    return None


# ---------------------------------------------------------------------------
# The Odds API fetch
# ---------------------------------------------------------------------------
def _get(url: str) -> list:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def _avg_prices(event: dict, market_key: str) -> dict:
    """Average each outcome's decimal price across all bookmakers in an event."""
    acc: dict[str, list] = {}
    for bk in event.get("bookmakers", []):
        for mk in bk.get("markets", []):
            if mk.get("key") != market_key:
                continue
            for oc in mk.get("outcomes", []):
                acc.setdefault(oc["name"], []).append(oc["price"])
    return {name: sum(ps) / len(ps) for name, ps in acc.items() if ps}


def fetch_odds(api_key: str, teams: list[str], regions: str = "eu") -> dict:
    """Pull 1X2 + outright odds from The Odds API, keyed to the feed's team names.

    Returns the *raw* (decimal) shape ready for save_odds, plus an ``unmatched``
    list of provider names we couldn't line up (so the caller can warn/alias)."""
    unmatched: set[str] = set()

    def fix(nm):
        r = resolve_team(nm, teams)
        if r is None and nm and _norm(nm) != "draw":
            unmatched.add(nm)
        return r

    matches: dict = {}
    m_url = (f"{ODDS_API_BASE}/sports/{SPORT_MATCH}/odds?regions={regions}"
             f"&markets=h2h&oddsFormat=decimal&apiKey={api_key}")
    for ev in _get(m_url):
        home, away = fix(ev.get("home_team")), fix(ev.get("away_team"))
        if not home or not away:
            continue
        prices = _avg_prices(ev, "h2h")
        h = prices.get(ev.get("home_team"))
        a = prices.get(ev.get("away_team"))
        d = prices.get("Draw")
        if h and a and d:
            matches[f"{home} vs {away}"] = {"home": h, "draw": d, "away": a}

    outrights: dict = {}
    o_url = (f"{ODDS_API_BASE}/sports/{SPORT_WINNER}/odds?regions={regions}"
             f"&markets=outrights&oddsFormat=decimal&apiKey={api_key}")
    try:
        for ev in _get(o_url):
            for name, price in _avg_prices(ev, "outrights").items():
                t = fix(name)
                if t:
                    outrights[t] = price
    except urllib.error.HTTPError as e:
        # outright market may be absent off-season / on some keys — non-fatal
        if e.code not in (404, 422):
            raise

    return {"matches": matches, "outrights": outrights,
            "fetched": datetime.now(timezone.utc).isoformat(),
            "unmatched": sorted(unmatched)}
