"""2026 FIFA World Cup standings + tiebreaker engine.

Group ranking criteria (FIFA 2026 — note the order changed this tournament):
  0. Most points (overall)                          [primary]
  -- if level on points, "between the teams concerned" (head-to-head): --
  1. Head-to-head points
  2. Head-to-head goal difference
  3. Head-to-head goals scored
     (if some teams separate but a subset is still tied, the head-to-head
      criteria are re-applied to that subset before moving on)
  -- then overall criteria: --
  4. Overall goal difference
  5. Overall goals scored
  6. Fair-play / conduct score (higher = better, 0 is best)
  7. FIFA world ranking (lower number = better)
  (Drawing of lots has been removed for 2026.)

Best third-placed teams (ranked across the 12 groups; no head-to-head):
  points -> goal difference -> goals scored -> conduct -> FIFA ranking
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional


@dataclass
class TeamRow:
    team: str
    group: str
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    gf: int = 0
    ga: int = 0

    @property
    def points(self) -> int:
        return self.won * 3 + self.drawn

    @property
    def gd(self) -> int:
        return self.gf - self.ga


def teams_in_group(group: str, matches) -> list[str]:
    names: list[str] = []
    for m in matches:
        if m.group == group:
            for t in (m.home, m.away):
                if t not in names and t != "TBD":
                    names.append(t)
    return names


def all_groups(matches) -> list[str]:
    return sorted({m.group for m in matches})


def _stats(team: str, matches) -> TeamRow:
    """Overall row for a team across the supplied (played) matches."""
    row = TeamRow(team=team, group="")
    for m in matches:
        if not m.played:
            continue
        if team == m.home:
            row.group = m.group
            gf, ga = m.home_goals, m.away_goals
        elif team == m.away:
            row.group = m.group
            gf, ga = m.away_goals, m.home_goals
        else:
            continue
        row.played += 1
        row.gf += gf
        row.ga += ga
        if gf > ga:
            row.won += 1
        elif gf == ga:
            row.drawn += 1
        else:
            row.lost += 1
    return row


def group_rows(group: str, matches, meta: Optional[dict] = None) -> list[TeamRow]:
    """Return the ranked TeamRows for one group (best first)."""
    names = teams_in_group(group, matches)
    rows = {t: _stats(t, matches) for t in names}
    for t in names:                      # ensure group set even with 0 games played
        rows[t].group = group
    ordered = _rank(names, matches, rows, meta or {})
    return [rows[t] for t in ordered]


# ---------------------------------------------------------------------------
# Ranking core
# ---------------------------------------------------------------------------
def _h2h_stats(team: str, subset: list[str], matches) -> tuple[int, int, int]:
    """(points, gd, goals) for `team` over played matches whose BOTH sides
    are inside `subset` (head-to-head mini-league)."""
    pts = gd = gf_total = 0
    sset = set(subset)
    for m in matches:
        if not m.played or m.home not in sset or m.away not in sset:
            continue
        if team == m.home:
            gf, ga = m.home_goals, m.away_goals
        elif team == m.away:
            gf, ga = m.away_goals, m.home_goals
        else:
            continue
        gf_total += gf
        gd += gf - ga
        if gf > ga:
            pts += 3
        elif gf == ga:
            pts += 1
    return pts, gd, gf_total


def _rank(names, matches, rows, meta) -> list[str]:
    """Top-level: bucket by overall points, then break ties."""
    buckets: dict[int, list[str]] = {}
    for t in names:
        buckets.setdefault(rows[t].points, []).append(t)
    ordered: list[str] = []
    for pts in sorted(buckets, reverse=True):
        ordered.extend(_resolve(buckets[pts], matches, rows, meta, phase="h2h"))
    return ordered


def _resolve(subset, matches, rows, meta, phase) -> list[str]:
    """Order a set of teams tied on overall points.

    phase 'h2h': apply head-to-head criteria; if a sub-block stays tied,
                 re-apply head-to-head within that block (FIFA reapplication).
    phase 'overall': apply overall GD/goals/conduct/ranking, no return to h2h.
    """
    if len(subset) == 1:
        return list(subset)

    if phase == "h2h":
        crits = [
            lambda t: _h2h_stats(t, subset, matches)[0],   # h2h points
            lambda t: _h2h_stats(t, subset, matches)[1],   # h2h gd
            lambda t: _h2h_stats(t, subset, matches)[2],   # h2h goals
        ]
        next_phase = "overall"
    else:
        fifa = meta.get("fifa_ranking", {})
        conduct = meta.get("conduct", {})
        crits = [
            lambda t: rows[t].gd,                           # overall gd
            lambda t: rows[t].gf,                           # overall goals
            lambda t: conduct.get(t, 0),                    # fair play (higher better)
            lambda t: -fifa.get(t, 9999),                   # fifa rank (lower better)
        ]
        next_phase = None

    for crit in crits:
        vals = {t: crit(t) for t in subset}
        if len(set(vals.values())) > 1:                    # this criterion separates
            blocks: dict = {}
            for t in subset:
                blocks.setdefault(vals[t], []).append(t)
            result: list[str] = []
            for v in sorted(blocks, reverse=True):
                block = blocks[v]
                if len(block) == 1:
                    result.append(block[0])
                else:                                       # reapply same phase to subset
                    result.extend(_resolve(block, matches, rows, meta, phase))
            return result

    # no criterion in this phase separated the set
    if next_phase:
        return _resolve(subset, matches, rows, meta, next_phase)
    return sorted(subset)        # genuinely inseparable (needs real fair-play data)


# ---------------------------------------------------------------------------
# Tournament-wide projection
# ---------------------------------------------------------------------------
@dataclass
class Projection:
    group_order: dict[str, list[TeamRow]]          # group -> ranked rows
    winners: list[str]
    runners_up: list[str]
    thirds_ranked: list[TeamRow]                    # all 3rd-placed, ranked best->worst
    qualified_thirds: list[str]                     # best 8
    eliminated_thirds: list[str]

    def qualified(self) -> set[str]:
        return set(self.winners) | set(self.runners_up) | set(self.qualified_thirds)


def _rank_thirds(third_rows: list[TeamRow], meta: dict) -> list[TeamRow]:
    fifa = meta.get("fifa_ranking", {})
    conduct = meta.get("conduct", {})
    return sorted(
        third_rows,
        key=lambda r: (
            r.points,
            r.gd,
            r.gf,
            conduct.get(r.team, 0),
            -fifa.get(r.team, 9999),
        ),
        reverse=True,
    )


def project(matches, meta: Optional[dict] = None, thirds_slots: int = 8) -> Projection:
    meta = meta or {}
    group_order: dict[str, list[TeamRow]] = {}
    winners, runners, thirds = [], [], []
    for g in all_groups(matches):
        rows = group_rows(g, matches, meta)
        group_order[g] = rows
        if len(rows) >= 1:
            winners.append(rows[0].team)
        if len(rows) >= 2:
            runners.append(rows[1].team)
        if len(rows) >= 3:
            thirds.append(rows[2])
    ranked_thirds = _rank_thirds(thirds, meta)
    qualified = [r.team for r in ranked_thirds[:thirds_slots]]
    eliminated = [r.team for r in ranked_thirds[thirds_slots:]]
    return Projection(
        group_order=group_order,
        winners=winners,
        runners_up=runners,
        thirds_ranked=ranked_thirds,
        qualified_thirds=qualified,
        eliminated_thirds=eliminated,
    )


def find_group(team: str, matches) -> Optional[str]:
    for g in all_groups(matches):
        if team in teams_in_group(g, matches):
            return g
    return None
