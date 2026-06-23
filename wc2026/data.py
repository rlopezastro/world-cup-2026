"""Data layer: load matches from a local cache, a manual file, or the live
football-data.org API, and normalize them into a common Match shape.

football-data.org free tier covers the FIFA World Cup (competition code "WC").
Get a free API key at https://www.football-data.org/client/register and either
export it as FOOTBALL_DATA_TOKEN or pass --token on the command line.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

API_BASE = "https://api.football-data.org/v4"
DEFAULT_COMPETITION = "WC"


@dataclass
class Match:
    group: str                      # single letter, e.g. "A"
    home: str
    away: str
    home_goals: Optional[int] = None
    away_goals: Optional[int] = None
    kickoff: Optional[str] = None       # match start time (ISO, UTC) from source
    status: Optional[str] = None        # FINISHED / IN_PLAY / TIMED / ...
    last_updated: Optional[str] = None  # when the SOURCE last changed this record
    # in-play score while a match is live; kept separate from home_goals/away_goals
    # so a live game is NOT treated as final anywhere except the explicit
    # "if result stands" view. None unless the match is currently live.
    live_home: Optional[int] = None
    live_away: Optional[int] = None

    @property
    def played(self) -> bool:
        return self.home_goals is not None and self.away_goals is not None

    @property
    def is_live(self) -> bool:
        return (self.status or "").upper() in ("IN_PLAY", "PAUSED", "LIVE")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Match":
        return cls(
            group=str(d["group"]).upper(),
            home=d["home"],
            away=d["away"],
            home_goals=d.get("home_goals"),
            away_goals=d.get("away_goals"),
            kickoff=d.get("kickoff"),
            status=d.get("status"),
            last_updated=d.get("last_updated"),
            live_home=d.get("live_home"),
            live_away=d.get("live_away"),
        )


def _norm_group(raw: Optional[str]) -> Optional[str]:
    """'GROUP_A' / 'Group A' / 'A' -> 'A'.  Non-group stages -> None."""
    if not raw:
        return None
    s = str(raw).upper().replace("GROUP", "").replace("_", " ").strip()
    if len(s) == 1 and s.isalpha():
        return s
    return None


# ---------------------------------------------------------------------------
# Live fetch
# ---------------------------------------------------------------------------
def _request_json(url: str, token: str, max_retries: int = 3) -> dict:
    """GET JSON from football-data.org, honoring its throttling headers.

    The API exposes `X-Requests-Available-Minute` (calls left this minute) and
    `X-RequestCounter-Reset` (seconds until the counter resets). On a 429 we wait
    for the reset window and retry instead of hammering the limiter.
    """
    req = urllib.request.Request(url, headers={"X-Auth-Token": token})
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.load(resp)
                left = resp.headers.get("X-Requests-Available-Minute")
                if left is not None:
                    print(f"(rate limit: {left} request(s) left this minute)")
                    if int(left) <= 0:
                        wait = int(resp.headers.get("X-RequestCounter-Reset", 60)) + 1
                        print(f"(throttling: sleeping {wait}s to respect the limit)")
                        time.sleep(wait)
                return payload
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                wait = int(e.headers.get("X-RequestCounter-Reset", 60)) + 1
                print(f"(rate limited — waiting {wait}s before retry "
                      f"{attempt + 2}/{max_retries})")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("Exceeded retry budget talking to football-data.org")


def fetch_live(token: str, competition: str = DEFAULT_COMPETITION) -> list[Match]:
    """Pull all group-stage matches from football-data.org."""
    url = f"{API_BASE}/competitions/{competition}/matches"
    payload = _request_json(url, token)

    matches: list[Match] = []
    for m in payload.get("matches", []):
        group = _norm_group(m.get("group") or m.get("stage"))
        if group is None:                       # skip knockout / playoff fixtures
            continue
        ft = (m.get("score") or {}).get("fullTime") or {}
        status = m.get("status")
        finished = status == "FINISHED"
        live = status in ("IN_PLAY", "PAUSED", "LIVE")
        matches.append(
            Match(
                group=group,
                home=(m.get("homeTeam") or {}).get("name") or "TBD",
                away=(m.get("awayTeam") or {}).get("name") or "TBD",
                home_goals=ft.get("home") if finished else None,
                away_goals=ft.get("away") if finished else None,
                kickoff=m.get("utcDate"),
                status=status,
                last_updated=m.get("lastUpdated"),
                # running score during play (0–0 default so a kicked-off game shows 0)
                live_home=(ft.get("home") or 0) if live else None,
                live_away=(ft.get("away") or 0) if live else None,
            )
        )
    return matches


def fetch_scorers(token: str, competition: str = DEFAULT_COMPETITION,
                  limit: int = 30) -> list[dict]:
    """Top scorers for the competition (free tier supports this endpoint).

    Per-match goal events ('who scored in this game') are NOT on the free tier.
    """
    url = f"{API_BASE}/competitions/{competition}/scorers?limit={limit}"
    payload = _request_json(url, token)
    out = []
    for s in payload.get("scorers", []):
        p = s.get("player") or {}
        t = s.get("team") or {}
        out.append({
            "player": p.get("name"),
            "nationality": p.get("nationality"),
            "team": t.get("name"),
            "tla": t.get("tla"),
            "goals": s.get("goals") or 0,
            "assists": s.get("assists") or 0,
            "penalties": s.get("penalties") or 0,
            "matches": s.get("playedMatches") or 0,
        })
    return out


# ---------------------------------------------------------------------------
# Local files
# ---------------------------------------------------------------------------
def load_file(path: str) -> list[Match]:
    with open(path) as fh:
        raw = json.load(fh)
    items = raw["matches"] if isinstance(raw, dict) else raw
    return [Match.from_dict(d) for d in items]


def save_file(path: str, matches: list[Match]) -> None:
    with open(path, "w") as fh:
        json.dump({"matches": [m.to_dict() for m in matches]}, fh, indent=2)


def load_meta(path: str) -> dict:
    """Per-team metadata for deep tiebreakers.

    FIFA rankings come from the bundled static snapshot (wc2026/fifa.py) and take
    precedence; an optional file can add conduct scores or extra/override ranks.
        {"fifa_ranking": {...}, "conduct": {...}}   # conduct: 0 best, negative worse
    """
    from . import fifa
    file_raw = {}
    if path and os.path.exists(path):
        with open(path) as fh:
            file_raw = json.load(fh)
    return {
        # real rankings win; file entries fill gaps (e.g. sample-only teams)
        "fifa_ranking": {**file_raw.get("fifa_ranking", {}), **fifa.RANKINGS},
        "conduct": file_raw.get("conduct", {}),
    }


# ---------------------------------------------------------------------------
# Source freshness — "what time is this data from?" (the provider's clock,
# not when you fetched it)
# ---------------------------------------------------------------------------
def parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def source_freshness(matches: list[Match]) -> dict:
    """Describe how current the *source data* is, using the timestamps the
    provider stamped on the matches themselves."""
    now = datetime.now(timezone.utc)
    updates = [parse_dt(m.last_updated) for m in matches]
    updates = [u for u in updates if u]
    finished, live, scheduled = [], [], []
    for m in matches:
        st = (m.status or "").upper()
        if m.played or st == "FINISHED":
            finished.append(m)
        elif st in ("IN_PLAY", "PAUSED", "LIVE"):
            live.append(m)
        else:
            scheduled.append(m)

    def _ko(m):
        return parse_dt(m.kickoff)

    fin_with_ko = [m for m in finished if _ko(m)]
    sched_future = [m for m in scheduled if _ko(m) and _ko(m) > now]
    return {
        "now": now,
        "source_as_of": max(updates) if updates else None,
        "counts": {"finished": len(finished), "live": len(live),
                   "scheduled": len(scheduled), "total": len(matches)},
        "latest_finished": max(fin_with_ko, key=_ko) if fin_with_ko else None,
        "live_matches": live,
        "next_match": min(sched_future, key=_ko) if sched_future else None,
        "has_timestamps": bool(updates) or any(_ko(m) for m in matches),
    }
