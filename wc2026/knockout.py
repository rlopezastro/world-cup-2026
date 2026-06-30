"""Knockout bracket: structure, seeding, and a forward play-out to a champion.

The 2026 Round of 32 is fed by the 12 group winners, 12 runners-up and the 8 best
third-placed teams. This module:

  * holds the official R32 pairings (BRACKET) and the round-by-round nesting (ROUNDS);
  * SEEDS the 32 slots three ways (see `bracket_view`):
      - "standings": current table order, even with games unplayed
      - "fifa":      most-likely finish from the FIFA-weighted simulation
      - "odds":      most-likely finish from the betting-odds-weighted simulation
  * assigns the 8 qualified thirds to the 8 third-slots using FIFA's official
    Annex-C combinations table (`annexc.json`, all 495 cases) when a full set of 8
    thirds is known; otherwise (partial/early brackets) falls back to a legal
    bipartite matching that respects each slot's allowed-group list;
  * plays the bracket forward, advancing the favourite of each tie by team strength
    (FIFA ranking, or outright-winner odds in "odds" mode), to a predicted winner.
"""

from __future__ import annotations

import itertools
import json
import math
import os
from typing import Callable, Optional

from .tiebreakers import all_groups, project, teams_in_group

# Official 2026 R32 (matches 73–88). Slot = (type, value):
#   ('W','A') winner of group A · ('R','A') runner-up A · ('3', [groups]) a best 3rd
BRACKET = [
    (73, ("R", "A"), ("R", "B")),
    (74, ("W", "E"), ("3", ["A", "B", "C", "D", "F"])),
    (75, ("W", "F"), ("R", "C")),
    (76, ("W", "C"), ("R", "F")),
    (77, ("W", "I"), ("3", ["C", "D", "F", "G", "H"])),
    (78, ("R", "E"), ("R", "I")),
    (79, ("W", "A"), ("3", ["C", "E", "F", "H", "I"])),
    (80, ("W", "L"), ("3", ["E", "H", "I", "J", "K"])),
    (81, ("W", "D"), ("3", ["B", "E", "F", "I", "J"])),
    (82, ("W", "G"), ("3", ["A", "E", "H", "I", "J"])),
    (83, ("R", "K"), ("R", "L")),
    (84, ("W", "H"), ("R", "J")),
    (85, ("W", "B"), ("3", ["E", "F", "G", "I", "J"])),
    (86, ("W", "J"), ("R", "H")),
    (87, ("W", "K"), ("3", ["D", "E", "I", "J", "L"])),
    (88, ("R", "D"), ("R", "G")),
]
R32_MAP = {mno: (s1, s2) for mno, s1, s2 in BRACKET}

# Display (top-to-bottom) order per round + which two feeder matches each later
# match consumes, arranged so paired matches nest correctly.
ROUNDS = [
    ("Round of 32",
     [74, 77, 73, 75, 83, 84, 81, 82, 76, 78, 79, 80, 86, 88, 85, 87], None),
    ("Round of 16", [89, 90, 93, 94, 91, 92, 95, 96],
     {89: (74, 77), 90: (73, 75), 91: (76, 78), 92: (79, 80),
      93: (83, 84), 94: (81, 82), 95: (86, 88), 96: (85, 87)}),
    ("Quarter-finals", [97, 98, 99, 100],
     {97: (89, 90), 98: (93, 94), 99: (91, 92), 100: (95, 96)}),
    ("Semi-finals", [101, 102], {101: (97, 98), 102: (99, 100)}),
    ("Final", [104], {104: (101, 102)}),
]

_THIRD_SLOTS = [(mno, set(s2[1])) for mno, s1, s2 in BRACKET if s2[0] == "3"]

# group winner -> the R32 match where it faces a third (e.g. winner E -> match 74)
_WINNER_MATCH = {s1[1]: mno for mno, s1, s2 in BRACKET if s2[0] == "3"}

# FIFA's official Annex-C allocation of thirds (495 combinations), loaded lazily.
_ANNEXC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "annexc.json")
_ANNEXC: Optional[dict] = None


def _annexc() -> dict:
    global _ANNEXC
    if _ANNEXC is None:
        try:
            with open(_ANNEXC_PATH) as fh:
                _ANNEXC = json.load(fh)
        except (OSError, ValueError):
            _ANNEXC = {"table": {}, "col_order": ["A", "B", "D", "E", "G", "I", "K", "L"]}
    return _ANNEXC


def locked_third_winners(certain_in, contested) -> dict:
    """{third_group: winner_group} for thirds whose Annex-C opponent is already fixed.

    A third can be slotted before all 8 thirds are known if the group winner it
    faces is the SAME in every still-possible set of 8 qualifying thirds. We test
    that over a superset of the feasible sets (all ways to fill the open slots from
    `contested`), so the result is conservative — it never locks a slot that could
    still move, but may stay silent a little longer than strictly necessary.

    `certain_in`: groups whose third is mathematically qualified.
    `contested`:  groups whose third might still qualify (fill the remaining slots).
    """
    ac = _annexc()
    table, col = ac["table"], ac["col_order"]
    certain = sorted(certain_in)
    need = 8 - len(certain)
    if need < 0:
        return {}
    faces: dict[str, set] = {g: set() for g in certain}
    seen_any = False
    for extra in itertools.combinations(sorted(contested), need):
        row = table.get("".join(sorted(set(certain) | set(extra))))
        if row is None:
            continue
        seen_any = True
        assign = {third_grp: winner for winner, third_grp in zip(col, row)}
        for g in certain:
            faces[g].add(assign.get(g))
    if not seen_any:
        return {}
    return {g: next(iter(w)) for g, w in faces.items()
            if len(w) == 1 and None not in w}


# ---------------------------------------------------------------------------
# team strength (higher = stronger) for the forward play-out
# ---------------------------------------------------------------------------
def make_strength(meta: dict, weighting: str = "fifa",
                  odds: Optional[dict] = None) -> Callable[[str], float]:
    fifa = (meta or {}).get("fifa_ranking", {})
    strength = (odds or {}).get("outrights_strength") or {}

    def s(team: str) -> float:
        if weighting == "odds" and team in strength:
            return strength[team]
        rank = fifa.get(team)
        if rank:
            return 1.0 / math.log(rank + 1.5)       # higher for lower rank number
        return 1e-6

    return s


def advance_prob(home: str, away: str, strength: Callable[[str], float]) -> float:
    """Bradley–Terry probability that `home` advances (knockout, no draw)."""
    sh, sa = strength(home), strength(away)
    return sh / (sh + sa) if (sh + sa) > 0 else 0.5


# ---------------------------------------------------------------------------
# seeding
# ---------------------------------------------------------------------------
def _assign_thirds(third_teams: list[tuple[str, str]]) -> dict:
    """Assign qualified thirds [(team, group), ...] to the 8 third-slots, returning
    {match_no: team}.

    Uses FIFA's official Annex-C table when a full, distinct set of 8 third-place
    groups is known (the real tournament case); otherwise falls back to a legal
    bipartite matching for partial/early brackets."""
    groups = [g for _, g in third_teams]
    ac = _annexc()
    key = "".join(sorted(groups))
    if len(groups) == 8 and len(set(groups)) == 8 and key in ac["table"]:
        team_of = {g: t for t, g in third_teams}
        return {_WINNER_MATCH[winner]: team_of[third_grp]
                for winner, third_grp in zip(ac["col_order"], ac["table"][key])}
    return _match_thirds(third_teams)


def _match_thirds(third_teams: list[tuple[str, str]]) -> dict:
    """Bipartite-match qualified thirds to the 8 third-slots, respecting each slot's
    allowed-group set. Always legal; used as a fallback when the exact Annex-C
    combination isn't applicable (fewer than 8 thirds known)."""
    slot_of: dict[int, int] = {}        # match_no -> index into third_teams

    def augment(ti: int, seen: set) -> bool:
        for mno, allowed in _THIRD_SLOTS:
            if third_teams[ti][1] in allowed and mno not in seen:
                seen.add(mno)
                if mno not in slot_of or augment(slot_of[mno], seen):
                    slot_of[mno] = ti
                    return True
        return False

    for ti in range(len(third_teams)):
        augment(ti, set())
    return {mno: third_teams[ti][0] for mno, ti in slot_of.items()}


def _seed_standings(matches, meta) -> dict:
    proj = project(matches, meta)
    winner = {g: rows[0].team for g, rows in proj.group_order.items() if rows}
    runner = {g: rows[1].team for g, rows in proj.group_order.items() if len(rows) > 1}
    q = set(proj.qualified_thirds)
    thirds = [(r.team, r.group) for r in proj.thirds_ranked if r.team in q]
    return {"winner": winner, "runner": runner, "thirds": thirds}


def _seed_from_probs(matches, meta, probs) -> dict:
    """Most-likely seeding from a monte_carlo `probs` dict
    {team: {win_group, top2, qualify}}."""
    winner, runner, third_rows = {}, {}, []
    for g in all_groups(matches):
        teams = teams_in_group(g, matches)
        order = sorted(teams, key=lambda t: (probs[t]["win_group"], probs[t]["top2"],
                                             probs[t]["qualify"]), reverse=True)
        if order:
            winner[g] = order[0]
        if len(order) > 1:
            runner[g] = order[1]
        if len(order) > 2:
            third_rows.append((order[2], g))
    third_rows.sort(key=lambda tg: probs[tg[0]]["qualify"], reverse=True)
    return {"winner": winner, "runner": runner, "thirds": third_rows[:8]}


# ---------------------------------------------------------------------------
# play-out
# ---------------------------------------------------------------------------
def _resolve_slot(slot, winner, runner, third_slot, mno):
    typ, val = slot
    if typ == "W":
        return winner.get(val)
    if typ == "R":
        return runner.get(val)
    return third_slot.get(mno)              # a third-slot is keyed by its match no


def index_knockout(ko_matches) -> dict:
    """{frozenset({home, away}): Match} for knockout fixtures whose teams are known.
    Lets the play-out look up a real result/fixture by the two teams in a tie."""
    idx = {}
    for m in ko_matches or []:
        if m.home and m.away and "TBD" not in (m.home, m.away):
            idx[frozenset((m.home, m.away))] = m
    return idx


def odds_favorites(odds) -> dict:
    """{frozenset({a, b}): favourite} from per-match 1X2 probabilities (the draw is
    irrelevant in a knockout, so the favourite is whoever's more likely to win)."""
    out = {}
    for key, p in ((odds or {}).get("matches") or {}).items():
        if " vs " not in key:
            continue
        home, away = key.split(" vs ", 1)
        out[frozenset((home, away))] = home if p.get("H", 0) >= p.get("A", 0) else away
    return out


def play_out(seed: dict, strength: Callable[[str], float],
             ko_results=None, ko_odds=None) -> dict:
    """Advance one team out of every tie to a champion.

    Each tie is resolved by priority: a real played result (`ko_results`, keyed by
    team pair) → the per-match betting favourite (`ko_odds`) → the stronger team by
    `strength` (FIFA ranking or outright odds). Returns {match_no: {"a","b","winner",
    "match"}} for every match in every round ("match" is the real fixture if one
    exists — for showing a score/live state), plus "champion"."""
    third_slot = _assign_thirds(seed["thirds"])
    w, r = seed["winner"], seed["runner"]
    ko_results = ko_results or {}
    ko_odds = ko_odds or {}
    results: dict[int, dict] = {}

    def decide(a, b):
        if not (a and b):
            return a or b, None
        km = ko_results.get(frozenset((a, b)))
        if km is not None and km.winner:                 # actual played result
            return km.winner, km
        fav = ko_odds.get(frozenset((a, b)))             # per-match betting favourite
        if not fav:                                      # fall back to strength model
            fav = a if strength(a) >= strength(b) else b
        return fav, km                  # km may be a live/scheduled fixture (no winner)

    def record(mno, a, b):
        win, km = decide(a, b)
        results[mno] = {"a": a, "b": b, "winner": win, "match": km}

    for mno, (s1, s2) in R32_MAP.items():
        record(mno, _resolve_slot(s1, w, r, third_slot, mno),
               _resolve_slot(s2, w, r, third_slot, mno))

    for _title, order, feed in ROUNDS:
        if feed is None:
            continue
        for mno in order:
            fa, fb = feed[mno]
            record(mno, results[fa]["winner"], results[fb]["winner"])

    return {"results": results, "third_slot": third_slot,
            "winner": w, "runner": r, "champion": results[104]["winner"]}


def bracket_view(matches, meta, mode: str = "standings",
                 probs=None, odds=None, knockout=None) -> dict:
    """One-call entry point for the UI.

    mode: "standings" | "fifa" | "odds". For the two simulation modes pass the
    corresponding monte_carlo `probs`; "odds" also uses `odds` for play-out strength.
    `knockout` is the list of real knockout fixtures/results, which override
    predictions where games have been played (and supply live scores).
    """
    if mode == "standings":
        seed = _seed_standings(matches, meta)
        weighting = "fifa"
    else:
        if probs is None:
            raise ValueError("sim modes require `probs` from monte_carlo")
        seed = _seed_from_probs(matches, meta, probs)
        weighting = mode                      # "fifa" or "odds"
    strength = make_strength(meta, weighting, odds)
    ko_results = index_knockout(knockout)
    ko_odds = odds_favorites(odds) if (mode == "odds" and odds) else {}
    out = play_out(seed, strength, ko_results, ko_odds)
    out["mode"] = mode
    return out
