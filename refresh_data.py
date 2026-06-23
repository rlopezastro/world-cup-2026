"""Refresh the bundled data files the published app serves.

Run on a schedule (e.g. GitHub Actions) with the API keys in the environment:

    FOOTBALL_DATA_TOKEN=...  ODDS_API_KEY=...  python refresh_data.py

Writes (next to this file): cache.json (scores), scorers.json (top scorers),
betting_odds.json (de-vigged match + outright prices). Each source is independent —
a failure in one is reported but doesn't abort the others, so a partial refresh still
updates what it can. Exits non-zero only if nothing could be refreshed.
"""

from __future__ import annotations

import json
import os
import sys

from wc2026 import data
from wc2026 import odds as oddsmod

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache.json")
SCORERS = os.path.join(HERE, "scorers.json")
BETTING = os.path.join(HERE, "betting_odds.json")


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


def main() -> int:
    fd = os.environ.get("FOOTBALL_DATA_TOKEN", "")
    ok = os.environ.get("ODDS_API_KEY", "")

    jobs = []
    if fd:
        jobs += [("scores", lambda: refresh_scores(fd)),
                 ("scorers", lambda: refresh_scorers(fd))]
    else:
        print("⚠️  FOOTBALL_DATA_TOKEN not set — skipping scores + scorers")
    if ok:
        jobs.append(("odds", lambda: refresh_odds(ok)))
    else:
        print("⚠️  ODDS_API_KEY not set — skipping odds")

    if not jobs:
        print("Nothing to refresh: no API keys in the environment.")
        return 1

    ok_count = 0
    for name, fn in jobs:
        try:
            print("✅ " + fn())
            ok_count += 1
        except Exception as e:
            print(f"❌ {name}: {e}")

    return 0 if ok_count else 1


if __name__ == "__main__":
    sys.exit(main())
