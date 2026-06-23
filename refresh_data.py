"""Refresh the bundled data files the published app serves — on a smart schedule.

Designed to be run frequently (e.g. every 15 min by GitHub Actions) but to spend API
requests only when it matters:

  * ODDS  — fetched only when a game kicks off within ODDS_LEAD_MIN minutes and the
            last odds fetch was more than ODDS_GAP_MIN ago (≈ "30 min before each
            game"). The Odds API free tier is 500 req/month and each fetch costs 2,
            so this keeps well inside budget.
  * SCORES + scorers — fetched only while a game is in (or just after) its play
            window. Live 2-minute updates for *viewers* happen in-app; this just
            persists results back to the committed file for cold starts / the sim.

Keys come from the environment (set them as GitHub Actions secrets):

    FOOTBALL_DATA_TOKEN=...  ODDS_API_KEY=...  python refresh_data.py
    python refresh_data.py --force      # ignore gating, refresh everything now

Writes (next to this file): cache.json, scorers.json, betting_odds.json. Exits 0 when
it did its job (including "nothing was due"); non-zero only if a fetch it attempted
failed.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

from wc2026 import data
from wc2026 import odds as oddsmod

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache.json")
SCORERS = os.path.join(HERE, "scorers.json")
BETTING = os.path.join(HERE, "betting_odds.json")

ODDS_LEAD_MIN = 35      # fetch odds when a game kicks off within this many minutes
ODDS_GAP_MIN = 45       # ...but not if odds were already fetched this recently (>lead,
                        #    so the 5-min heartbeat fetches odds just once per kickoff)
SCORES_PRE_MIN = 5      # start refreshing scores this long before kickoff
SCORES_POST_MIN = 210   # ...until this long after (covers play + post-match settle)


def _matches():
    try:
        return data.load_file(CACHE)
    except (OSError, ValueError):
        return []


def _scores_due(now) -> bool:
    for m in _matches():
        if m.played:
            continue
        ko = data.parse_dt(m.kickoff)
        if ko and ko - timedelta(minutes=SCORES_PRE_MIN) <= now \
                <= ko + timedelta(minutes=SCORES_POST_MIN):
            return True
    return False


def _odds_due(now) -> bool:
    # a game kicking off soon?
    soon = any(
        (ko := data.parse_dt(m.kickoff)) and now <= ko <= now + timedelta(minutes=ODDS_LEAD_MIN)
        for m in _matches() if not m.played
    )
    if not soon:
        return False
    # ...and not already refreshed within the last ODDS_GAP_MIN
    try:
        with open(BETTING) as fh:
            last = data.parse_dt(json.load(fh).get("fetched"))
        if last and now - last < timedelta(minutes=ODDS_GAP_MIN):
            return False
    except (OSError, ValueError):
        pass
    return True


def refresh_scores(token: str) -> str:
    matches = data.fetch_live(token)
    data.save_file(CACHE, matches)
    return f"scores: {len(matches)} matches ({sum(m.played for m in matches)} played)"


def refresh_scorers(token: str) -> str:
    rows = data.fetch_scorers(token, limit=100)
    with open(SCORERS, "w") as fh:
        json.dump(rows, fh, ensure_ascii=False)
    return f"scorers: {len(rows)} rows"


def refresh_odds(okey: str) -> str:
    teams = sorted({t for m in data.load_file(CACHE) for t in (m.home, m.away)})
    fetched = oddsmod.fetch_odds(okey, teams)
    unmatched = fetched.pop("unmatched", [])
    oddsmod.save_odds(BETTING, fetched)
    msg = (f"odds: {len(fetched.get('matches', {}))} match + "
           f"{len(fetched.get('outrights', {}))} outright prices")
    if unmatched:
        msg += f" (unmatched: {', '.join(unmatched)})"
    return msg


def main(argv) -> int:
    force = "--force" in argv
    now = datetime.now(timezone.utc)
    fd = os.environ.get("FOOTBALL_DATA_TOKEN", "")
    ok = os.environ.get("ODDS_API_KEY", "")

    jobs = []
    if force or _scores_due(now):
        if fd:
            jobs += [("scores", lambda: refresh_scores(fd)),
                     ("scorers", lambda: refresh_scorers(fd))]
        else:
            print("⚠️  scores due but FOOTBALL_DATA_TOKEN not set — skipping")
    if force or _odds_due(now):
        if ok:
            jobs.append(("odds", lambda: refresh_odds(ok)))
        else:
            print("⚠️  odds due but ODDS_API_KEY not set — skipping")

    if not jobs:
        print(f"Nothing due at {now:%Y-%m-%d %H:%M UTC} (no game imminent / in play).")
        return 0

    errors = 0
    for name, fn in jobs:
        try:
            print("✅ " + fn())
        except Exception as e:
            print(f"❌ {name}: {e}")
            errors += 1
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
