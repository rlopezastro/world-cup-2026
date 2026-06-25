"""Scenario analysis on top of the tiebreaker engine.

Group-level questions (clinch group / clinch top-2 / out of group) are answered
*exactly* by enumerating scorelines of the remaining matches in the team's group.
Whole-tournament questions involving the best-8 third-place race are answered with
Monte Carlo simulation, since they depend on every other group too.
"""

from __future__ import annotations

import itertools
import math
import random
from functools import lru_cache
from typing import Optional

from .data import Match
from .tiebreakers import (
    all_groups,
    find_group,
    group_rows,
    project,
    teams_in_group,
)

MAX_GOALS = 5          # scoreline range when enumerating exactly
ENUM_CAP = 3           # exact enumeration if <= this many remaining group matches


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _group_matches(group: str, matches) -> list[Match]:
    return [m for m in matches if m.group == group]


def remaining(matches, group: Optional[str] = None) -> list[Match]:
    return [
        m for m in matches
        if not m.played and (group is None or m.group == group)
    ]


def _result_for(team: str, m: Match) -> str:
    """W / D / L for `team` in a played match."""
    if team == m.home:
        gf, ga = m.home_goals, m.away_goals
    else:
        gf, ga = m.away_goals, m.home_goals
    return "W" if gf > ga else "D" if gf == ga else "L"


def _score_options(exact: bool) -> list[tuple[int, int]]:
    if exact:
        return [(h, a) for h in range(MAX_GOALS + 1) for a in range(MAX_GOALS + 1)]
    return [(1, 0), (0, 0), (0, 1)]   # representative win / draw / loss


def _enumerate_group(team: str, group: str, matches, meta,
                     focus: Optional[Match] = None):
    """Yield (focus_result, final_position_of_team) over all remaining
    scoreline combinations in `group`. focus_result is the result for `team`
    in `focus` (or None if focus has no remaining match)."""
    gmatches = _group_matches(group, matches)
    played = [m for m in gmatches if m.played]
    rem = [m for m in gmatches if not m.played]

    if not rem:
        rows = group_rows(group, gmatches, meta)
        pos = {r.team: i + 1 for i, r in enumerate(rows)}
        return [(None, pos[team])], True

    exact = len(rem) <= ENUM_CAP
    opts = [_score_options(exact) for _ in rem]
    out = []
    for combo in itertools.product(*opts):
        assigned = [
            Match(m.group, m.home, m.away, h, a)
            for m, (h, a) in zip(rem, combo)
        ]
        rows = group_rows(group, played + assigned, meta)
        pos = {r.team: i + 1 for i, r in enumerate(rows)}
        fres = None
        if focus is not None:
            for m, (h, a) in zip(rem, combo):
                if m.home == focus.home and m.away == focus.away:
                    fres = _result_for(team, Match(m.group, m.home, m.away, h, a))
        out.append((fres, pos[team]))
    return out, exact


# ---------------------------------------------------------------------------
# status: clinch / eliminate
# ---------------------------------------------------------------------------
def team_status(team: str, matches, meta: Optional[dict] = None) -> dict:
    meta = meta or {}
    group = find_group(team, matches)
    if group is None:
        return {"error": f"Team '{team}' not found."}

    outcomes, exact = _enumerate_group(team, group, matches, meta)
    positions = {pos for _, pos in outcomes}
    best, worst = min(positions), max(positions)

    # current snapshot
    cur_rows = group_rows(group, matches, meta)
    cur_pos = next(i + 1 for i, r in enumerate(cur_rows) if r.team == team)
    cur_row = cur_rows[cur_pos - 1]

    proj = project(matches, meta)
    proj_qualified = team in proj.qualified()
    third_rank = None
    if any(r.team == team for r in proj.thirds_ranked):
        third_rank = 1 + next(
            i for i, r in enumerate(proj.thirds_ranked) if r.team == team
        )

    # classification (group-exact)
    if positions == {1}:
        headline = "CLINCHED GROUP WINNER 🥇 — through to Round of 32."
        level = "clinched"
    elif worst <= 2:
        headline = "CLINCHED TOP 2 ✅ — through to Round of 32."
        level = "clinched"
    elif best >= 4:
        headline = "ELIMINATED ❌ — cannot finish in the top 3 of the group."
        level = "eliminated"
    elif best <= 2:
        if best == 1:
            headline = "ALIVE — still controls a path to winning the group."
        else:
            headline = "ALIVE — can still finish top 2 (automatic qualification)."
        level = "alive"
    else:  # best == 3, worst >= 3
        headline = ("ALIVE — best case is 3rd; qualification depends on the "
                    "other groups' third-place race.")
        level = "alive-third"

    return {
        "team": team,
        "group": group,
        "current_position": cur_pos,
        "current_points": cur_row.points,
        "current_gd": cur_row.gd,
        "team_games_left": sum(1 for m in matches
                               if team in (m.home, m.away) and not m.played),
        "remaining_in_group": len(remaining(matches, group)),
        "possible_positions": sorted(positions),
        "best_possible": best,
        "worst_possible": worst,
        "headline": headline,
        "level": level,
        "exact": exact,
        "current_projection_qualified": proj_qualified,
        "current_third_rank": third_rank,
    }


# ---------------------------------------------------------------------------
# what do they need
# ---------------------------------------------------------------------------
_POS_MEANING = {
    1: "win the group",
    2: "finish 2nd (auto-qualify)",
    3: "finish 3rd (qualification depends on other groups)",
    4: "finish last (eliminated)",
}


def what_they_need(team: str, matches, meta: Optional[dict] = None) -> dict:
    meta = meta or {}
    group = find_group(team, matches)
    if group is None:
        return {"error": f"Team '{team}' not found."}

    rem = remaining(matches, group)
    next_match = next((m for m in rem if team in (m.home, m.away)), None)
    if next_match is None:
        return {"team": team, "group": group, "no_more_games": True}

    enum = _enumerate_group(team, group, matches, meta, focus=next_match)
    outcomes, exact = enum
    summary = {}
    for res in ("W", "D", "L"):
        ps = [pos for r, pos in outcomes if r == res]
        if ps:
            summary[res] = {"guaranteed": max(ps), "best": min(ps)}

    opponent = next_match.away if team == next_match.home else next_match.home
    return {
        "team": team,
        "group": group,
        "next_opponent": opponent,
        "fixture": f"{next_match.home} vs {next_match.away}",
        "summary": summary,
        "exact": exact,
    }


# ---------------------------------------------------------------------------
# qualification verdicts — EXACT guaranteed-qualified / guaranteed-eliminated
#
# Soundness: we reason in POINTS only. A team's points are fully determined by
# the W/D/L outcome of each remaining game (goals are irrelevant to points), so
# enumerating W/D/L is exhaustive and exact for points. Goal-difference ties are
# handled conservatively — a team that could merely TIE another on points is
# treated as "possibly behind" (for a qualify guarantee) and a rival is only
# "guaranteed ahead" when it has strictly more points. So we never assert a
# guarantee that goal difference could overturn.
# ---------------------------------------------------------------------------
def _group_points_vectors(group, matches):
    """All achievable final points vectors for a group (one dict per W/D/L
    combination of its remaining games)."""
    gmatches = _group_matches(group, matches)
    names = teams_in_group(group, matches)
    base = {t: 0 for t in names}
    rem = []
    for m in gmatches:
        if m.played:
            if m.home_goals > m.away_goals:
                base[m.home] += 3
            elif m.home_goals < m.away_goals:
                base[m.away] += 3
            else:
                base[m.home] += 1
                base[m.away] += 1
        else:
            rem.append(m)
    vectors = []
    for combo in itertools.product("HDA", repeat=len(rem)):
        pts = dict(base)
        for m, res in zip(rem, combo):
            if res == "H":
                pts[m.home] += 3
            elif res == "A":
                pts[m.away] += 3
            else:
                pts[m.home] += 1
                pts[m.away] += 1
        vectors.append(pts)
    return names, vectors


def qualification_status(matches, meta=None, thirds_slots=8):
    """Return {team: {qualified, eliminated, medal, group}} where qualified /
    eliminated are only True when MATHEMATICALLY CERTAIN, and medal marks a
    guaranteed group finish (🥇 winner, 🥈 runner-up, 🥉 third).

    The best-8 third-place race is settled on points, with one refinement: when
    BOTH a team and a rival group are fully played, their third-place teams are
    compared on the full FIFA tiebreaker key (points, GD, GF, conduct, FIFA rank)
    rather than points alone — so a team locks in (or out) as soon as goal
    difference decides a points-tie, not only once points separate everyone.

    Safety (never over-declares) is preserved because a rival's still-playable
    goal difference is treated as unbounded: for qualification we over-state each
    rival's best possible key (±∞ fillers) and require it to reach our WORST key;
    for elimination we under-state each rival's worst key and require it to clear
    our BEST. With unknown GD filled by ∞, both reduce to the old points-only
    bounds; the exact-key comparison only ever kicks in between settled groups."""
    meta = meta or {}
    fifa = meta.get("fifa_ranking", {})
    conduct = meta.get("conduct", {})
    groups = all_groups(matches)
    INF = float("inf")

    def _key(row):
        # same ordering _rank_thirds uses; larger tuple = ranks higher
        return (row.points, row.gd, row.gf,
                conduct.get(row.team, 0), -fifa.get(row.team, 9999))

    # per-group third-place info: points bounds over the remaining-game outcomes,
    # plus the EXACT third-place key once the group is fully played (else None).
    third_pmax, third_pmin, third_key, names_by, bounds = {}, {}, {}, {}, {}
    key_of = {}                       # team -> exact key (only in settled groups)
    for g in groups:
        names, vectors = _group_points_vectors(g, matches)
        names_by[g] = names
        gmatches = _group_matches(g, matches)
        finished = bool(gmatches) and all(m.played for m in gmatches)
        rows = group_rows(g, matches, meta) if finished else None
        pos_of = {}
        if finished:
            for i, r in enumerate(rows, 1):
                key_of[r.team] = _key(r)
                pos_of[r.team] = i        # exact final place (GD/GF already settle ties)
        if len(names) < 3:
            third_pmax[g] = third_pmin[g] = -1
            third_key[g] = None
        else:
            thirds = [sorted(v.values(), reverse=True)[2] for v in vectors]
            third_pmax[g], third_pmin[g] = max(thirds), min(thirds)
            third_key[g] = key_of[rows[2].team] if finished else None
        for t in names:
            max_worst, min_best, can3, pmin, pmax = 0, 99, False, 99, -1
            for v in vectors:
                tp = v[t]
                sa = sum(1 for u in names if u != t and v[u] > tp)   # strictly above
                eq = sum(1 for u in names if u != t and v[u] == tp)  # tied
                best, worst = sa + 1, sa + eq + 1
                max_worst = max(max_worst, worst)
                min_best = min(min_best, best)
                can3 = can3 or (best <= 3 <= worst)
                pmin, pmax = min(pmin, tp), max(pmax, tp)
            if finished:
                # the group is decided — collapse points-tie ambiguity to the
                # actual final place, so a team locked 3rd by GD isn't left looking
                # like it "could still be 2nd or 4th" on points alone.
                p = pos_of[t]
                max_worst = min_best = p
                can3 = (p == 3)
            bounds[t] = dict(group=g, max_worst=max_worst, min_best=min_best,
                             can3=can3, pmin=pmin, pmax=pmax, key=key_of.get(t))

    out = {}
    for g in groups:
        for t in names_by[g]:
            b = bounds[t]
            medal = ("🥇" if b["max_worst"] == 1
                     else "🥈" if b["min_best"] >= 2 and b["max_worst"] <= 2
                     else "🥉" if b["min_best"] >= 3 and b["max_worst"] <= 3 else "")
            qualified = eliminated = False
            via = ""
            if b["max_worst"] <= 2:                       # guaranteed top 2
                qualified, via = True, "top2"
            elif b["min_best"] >= 4:                      # can only be 4th
                eliminated, via = True, "group"
            else:
                if b["max_worst"] <= 3:                   # guaranteed at least 3rd
                    # my worst key as a third (exact if settled, else low sentinel)
                    t_worst = b["key"] or (b["pmin"], -INF, -INF, -INF, -INF)
                    rivals = 0
                    for og in groups:
                        if og == g or third_pmax[og] < 0:
                            continue
                        # rival's best possible key (exact if settled, else ∞ GD)
                        og_best = third_key[og] or (third_pmax[og], INF, INF, INF, INF)
                        if og_best >= t_worst:            # could reach/exceed me
                            rivals += 1
                    if rivals <= thirds_slots - 1:        # ≤7 can pass me → top 8
                        qualified, via = True, "third"
                if not qualified and b["min_best"] >= 3 and b["can3"]:
                    # my best key as a third (exact if settled, else high sentinel)
                    t_best = b["key"] or (b["pmax"], INF, INF, INF, INF)
                    ahead = 0
                    for og in groups:
                        if og == g or third_pmax[og] < 0:
                            continue
                        # rival's worst possible key (exact if settled, else low)
                        og_worst = third_key[og] or (third_pmin[og], -INF, -INF, -INF, -INF)
                        if og_worst > t_best:             # guaranteed above me
                            ahead += 1
                    if ahead >= thirds_slots:             # ≥8 strictly ahead → out
                        eliminated, via = True, "third"
            out[t] = dict(qualified=qualified, eliminated=eliminated,
                          medal=medal, via=via, group=g)
    return out


# ---------------------------------------------------------------------------
# ways through — concrete result combinations that qualify a team (top 2)
# ---------------------------------------------------------------------------
def _res_team(team, m, h, a):
    gf, ga = (h, a) if m.home == team else (a, h)
    return "W" if gf > ga else "D" if gf == ga else "L"


def _res_home(m, h, a):
    return "H" if h > a else "D" if h == a else "A"


def ways_through(team, matches, meta=None, fmt=lambda s: s, max_conditions=6):
    """Human-readable paths to a top-2 (guaranteed-qualification) finish.

    `fmt` formats team names (pass flags.label to add flags). Returns a dict with
    'level' and 'lines' (list of sentence strings)."""
    meta = meta or {}
    group = find_group(team, matches)
    s = team_status(team, matches, meta)
    out = {"team": team, "group": group, "level": s["level"], "lines": []}

    if s["level"] == "clinched":
        out["lines"].append("✅ Already through to the Round of 32.")
        return out
    if s["level"] == "eliminated":
        out["lines"].append("❌ Eliminated — no path to the Round of 32.")
        return out

    gmatches = _group_matches(group, matches)
    played = [m for m in gmatches if m.played]
    own = [m for m in gmatches if not m.played and team in (m.home, m.away)]
    others = [m for m in gmatches if not m.played and team not in (m.home, m.away)]

    if s["level"] == "alive-third":
        out["lines"].append(
            "Your best possible finish is **3rd**. To advance you'd need to (1) "
            "secure 3rd in the group and (2) be among the 8 best third-placed teams "
            "— check the Odds tab for those chances.")
        return out

    exact = len(own) + len(others) <= ENUM_CAP
    own_opts = [_score_options(exact) for _ in own]
    oth_opts = [_score_options(exact) for _ in others]
    other_combos = list(itertools.product(*oth_opts)) if others else [()]

    # table[own_wdl][other_wdl] = set of bools (top-2?) over consistent scorelines
    table: dict = {}
    for oc in itertools.product(*own_opts):
        owdl = tuple(_res_team(team, m, h, a) for m, (h, a) in zip(own, oc))
        oa = [Match(m.group, m.home, m.away, h, a) for m, (h, a) in zip(own, oc)]
        for xc in other_combos:
            xa = [Match(m.group, m.home, m.away, h, a) for m, (h, a) in zip(others, xc)]
            rows = group_rows(group, played + oa + xa, meta)
            pos = next(i + 1 for i, r in enumerate(rows) if r.team == team)
            xwdl = tuple(_res_home(m, h, a) for m, (h, a) in zip(others, xc))
            table.setdefault(owdl, {}).setdefault(xwdl, set()).add(pos <= 2)

    def own_phrase(owdl):
        verb = {"W": "beat", "D": "draw with", "L": "lose to"}
        parts = [f"{verb[r]} {fmt(m.away if m.home == team else m.home)}"
                 for m, r in zip(own, owdl)]
        return " and ".join(parts) if parts else "your remaining games"

    def other_phrase(xwdl):
        parts = []
        for m, r in zip(others, xwdl):
            if r == "H":
                parts.append(f"{fmt(m.home)} beat {fmt(m.away)}")
            elif r == "A":
                parts.append(f"{fmt(m.away)} beat {fmt(m.home)}")
            else:
                parts.append(f"{fmt(m.home)} draw {fmt(m.away)}")
        return " and ".join(parts)

    rank = {"W": 0, "D": 1, "L": 2}
    for owdl in sorted(table, key=lambda t: sum(rank[r] for r in t)):
        xmap = table[owdl]
        guaranteed = [x for x, b in xmap.items() if b == {True}]
        possible = any(True in b for b in xmap.values())
        phrase = own_phrase(owdl)
        phrase = phrase[:1].upper() + phrase[1:]
        if all(b == {True} for b in xmap.values()):
            out["lines"].append(f"✅ **{phrase}** → through (top 2), whatever else happens.")
        elif guaranteed:
            conds = [other_phrase(x) for x in guaranteed if other_phrase(x)]
            shown = "; or ".join(conds[:max_conditions])
            more = "" if len(conds) <= max_conditions else f"  (+{len(conds)-max_conditions} more)"
            tail = f" if {shown}{more}" if shown else ""
            note = ("  *(some cases come down to goal difference)*"
                    if possible and any(b == {True, False} for b in xmap.values()) else "")
            out["lines"].append(f"🟡 **{phrase}** → through{tail}.{note}")
        elif possible:
            out["lines"].append(f"🟡 **{phrase}** → can still sneak top 2, but only on "
                                "goal difference / goals.")
        else:
            out["lines"].append(f"🔴 **{phrase}** → can't finish top 2 (3rd place is the "
                                "best case — see the Odds tab).")
    return out


# ---------------------------------------------------------------------------
# scenarios
# ---------------------------------------------------------------------------
def _find_fixture(matches, q1: str, q2: str) -> Optional[Match]:
    q1, q2 = q1.lower(), q2.lower()
    for m in matches:
        h, a = m.home.lower(), m.away.lower()
        if q1 in h and q2 in a:
            return m, False
        if q1 in a and q2 in h:
            return m, True
    return None


def apply_overrides(matches, overrides) -> list[Match]:
    """overrides: list of (team1, goals1, goals2, team2) tuples (strings/ints).
    Matched to a fixture by substring; scores oriented to home/away."""
    new = [Match(m.group, m.home, m.away, m.home_goals, m.away_goals)
           for m in matches]
    for t1, g1, g2, t2 in overrides:
        found = _find_fixture(new, t1, t2)
        if not found:
            raise ValueError(f"No fixture matching '{t1}' vs '{t2}'.")
        m, flipped = found
        m.home_goals, m.away_goals = (int(g2), int(g1)) if flipped else (int(g1), int(g2))
    return new


# ---------------------------------------------------------------------------
# Monte Carlo
#
# Each unplayed match is turned into a pair of Poisson expected-goals (lambdas).
# Two weighting modes produce those lambdas:
#   "fifa"  — log-rank-ratio of the two teams' FIFA rankings (the original model).
#   "odds"  — fit lambdas to the de-vigged 1X2 betting odds for that match; where a
#             match price is missing (e.g. knockout games), fall back to a strength
#             rating from outright winner odds, then to FIFA.
# Lambdas are built ONCE per simulation run (build_lambda_table), not per draw.
# ---------------------------------------------------------------------------
LAMBDA_BASE = 1.35
LAMBDA_LO, LAMBDA_HI = 0.2, 4.5


def _fifa_lambdas(home: str, away: str, fifa: dict) -> tuple[float, float]:
    """Expected goals scaled by FIFA-ranking strength (log-rank-ratio).

    The gap matters more between top sides, so a #3-vs-#82 mismatch is genuinely
    lopsided: Spain(3) vs Curaçao(82) -> ~3.1 vs ~0.6 expected goals."""
    rh, ra = fifa.get(home), fifa.get(away)
    if rh and ra:
        diff = math.log(ra) - math.log(rh)        # >0 when home is stronger
        lh = LAMBDA_BASE * math.exp(0.25 * diff)
        la = LAMBDA_BASE * math.exp(-0.25 * diff)
        return min(LAMBDA_HI, max(LAMBDA_LO, lh)), min(LAMBDA_HI, max(LAMBDA_LO, la))
    return LAMBDA_BASE, LAMBDA_BASE


def _strength_lambdas(sh: float, sa: float) -> tuple[float, float]:
    """Expected goals from two outright-winner strength ratings (implied
    win-cup probabilities). Used for knockout games and any group game without a
    specific 1X2 price. Same log-ratio shape as the FIFA model."""
    if sh > 0 and sa > 0:
        diff = math.log(sh) - math.log(sa)
        lh = LAMBDA_BASE * math.exp(0.25 * diff)
        la = LAMBDA_BASE * math.exp(-0.25 * diff)
        return min(LAMBDA_HI, max(LAMBDA_LO, lh)), min(LAMBDA_HI, max(LAMBDA_LO, la))
    return LAMBDA_BASE, LAMBDA_BASE


def _outcome_probs(lh: float, la: float, cap: int = 10) -> tuple[float, float, float]:
    """P(home win), P(draw), P(away win) for independent Poisson(lh), Poisson(la)."""
    ph = pd = pa = 0.0
    eh = [math.exp(-lh) * lh ** k / math.factorial(k) for k in range(cap + 1)]
    ea = [math.exp(-la) * la ** k / math.factorial(k) for k in range(cap + 1)]
    for i in range(cap + 1):
        for j in range(cap + 1):
            p = eh[i] * ea[j]
            if i > j:
                ph += p
            elif i == j:
                pd += p
            else:
                pa += p
    return ph, pd, pa


@lru_cache(maxsize=4096)
def _fit_lambdas(ph: float, pd: float, pa: float) -> tuple[float, float]:
    """Find (lambda_home, lambda_away) whose Poisson scoreline reproduces the
    target win/draw/loss probabilities. Coarse grid then a local refinement;
    runs once per fixture (cached on the rounded target), so cost is trivial."""
    best, berr = (LAMBDA_BASE, LAMBDA_BASE), 9e9
    grid = [LAMBDA_LO + i * (LAMBDA_HI - LAMBDA_LO) / 24 for i in range(25)]
    for lh in grid:
        for la in grid:
            qh, qd, qa = _outcome_probs(lh, la)
            err = (qh - ph) ** 2 + (qd - pd) ** 2 + (qa - pa) ** 2
            if err < berr:
                best, berr = (lh, la), err
    # local refine around the best grid point
    bh, ba = best
    step = (LAMBDA_HI - LAMBDA_LO) / 24
    for _ in range(3):
        step /= 3
        for lh in (bh - step, bh, bh + step):
            for la in (ba - step, ba, ba + step):
                lh = min(LAMBDA_HI, max(LAMBDA_LO, lh))
                la = min(LAMBDA_HI, max(LAMBDA_LO, la))
                qh, qd, qa = _outcome_probs(lh, la)
                err = (qh - ph) ** 2 + (qd - pd) ** 2 + (qa - pa) ** 2
                if err < berr:
                    bh, ba, berr = lh, la, err
    return bh, ba


def _lambdas(home: str, away: str, meta: dict,
             weighting: str = "fifa", odds: Optional[dict] = None) -> tuple[float, float]:
    """Dispatch to the active weighting model for one match."""
    if weighting == "odds" and odds:
        key = f"{home} vs {away}"
        mp = (odds.get("matches") or {}).get(key)
        if mp:
            return _fit_lambdas(round(mp["H"], 3), round(mp["D"], 3), round(mp["A"], 3))
        strength = odds.get("outrights_strength") or {}
        sh, sa = strength.get(home), strength.get(away)
        if sh and sa:
            return _strength_lambdas(sh, sa)
    return _fifa_lambdas(home, away, meta.get("fifa_ranking", {}))


def build_lambda_table(matches, meta: dict, weighting: str = "fifa",
                       odds: Optional[dict] = None) -> dict:
    """{(home, away): (lambda_home, lambda_away)} for every unplayed match."""
    return {(m.home, m.away): _lambdas(m.home, m.away, meta, weighting, odds)
            for m in matches if not m.played}


def _poisson(lam: float, rng: random.Random) -> int:
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def _simulate(matches, lam_table, rng) -> list[Match]:
    out = []
    for m in matches:
        if m.played:
            out.append(m)
            continue
        lh, la = lam_table.get((m.home, m.away), (LAMBDA_BASE, LAMBDA_BASE))
        out.append(Match(m.group, m.home, m.away, _poisson(lh, rng), _poisson(la, rng)))
    return out


def monte_carlo(matches, meta: Optional[dict] = None, n: int = 2000,
                seed: int = 12345, fix=None, weighting: str = "fifa",
                odds: Optional[dict] = None) -> dict:
    meta = meta or {}
    rng = random.Random(seed)
    base = apply_overrides(matches, fix) if fix else matches
    lam_table = build_lambda_table(base, meta, weighting, odds)
    teams = [t for g in all_groups(matches) for t in teams_in_group(g, matches)]
    tally = {t: {"win_group": 0, "top2": 0, "qualify": 0} for t in teams}
    for _ in range(n):
        sim = _simulate(base, lam_table, rng)
        proj = project(sim, meta)
        q = proj.qualified()
        top2 = set(proj.winners) | set(proj.runners_up)
        for t in teams:
            if t in proj.winners:
                tally[t]["win_group"] += 1
            if t in top2:
                tally[t]["top2"] += 1
            if t in q:
                tally[t]["qualify"] += 1
    return {t: {k: v / n for k, v in d.items()} for t, d in tally.items()}


# stages tracked by tournament_odds, in order (cumulative: reaching a later stage
# implies reaching every earlier one)
TOURNEY_STAGES = ["r32", "r16", "qf", "sf", "final", "champion"]


def _advance(a, b, strength, rng) -> Optional[str]:
    """Pick a knockout-tie winner at random, weighted by Bradley-Terry strength."""
    from . import knockout
    if a and b:
        return a if rng.random() < knockout.advance_prob(a, b, strength) else b
    return a or b


def _sim_bracket(matches, meta, lam_table, strength, rng):
    """One full tournament playthrough. Returns (r32_pairs, win):
      r32_pairs: {match_no: (a, b)} the Round-of-32 line-ups
      win:       {match_no: winner} every match in every round."""
    from . import knockout
    proj = project(_simulate(matches, lam_table, rng), meta)
    qthirds = set(proj.qualified_thirds)
    w = {g: rows[0].team for g, rows in proj.group_order.items() if rows}
    r = {g: rows[1].team for g, rows in proj.group_order.items() if len(rows) > 1}
    thirds = [(row.team, row.group) for row in proj.thirds_ranked
              if row.team in qthirds]
    third_slot = knockout._assign_thirds(thirds)

    r32: dict[int, tuple] = {}
    win: dict[int, Optional[str]] = {}
    for mno, (s1, s2) in knockout.R32_MAP.items():
        a = knockout._resolve_slot(s1, w, r, third_slot, mno)
        b = knockout._resolve_slot(s2, w, r, third_slot, mno)
        r32[mno] = (a, b)
        win[mno] = _advance(a, b, strength, rng)
    for _title, order, feed in knockout.ROUNDS:
        if feed is None:
            continue
        for mno in order:
            fa, fb = feed[mno]
            win[mno] = _advance(win[fa], win[fb], strength, rng)
    return r32, win


def tournament_odds(matches, meta: Optional[dict] = None, n: int = 2000,
                    seed: int = 12345, weighting: str = "fifa",
                    odds: Optional[dict] = None) -> dict:
    """Full-tournament Monte Carlo: simulate the group stage, seed the Round of 32
    via FIFA's exact Annex-C table, then play every knockout tie probabilistically.

    Returns {team: {stage: probability}} for stage in TOURNEY_STAGES
    (r32 / r16 / qf / sf / final / champion), each cumulative."""
    from . import knockout
    meta = meta or {}
    rng = random.Random(seed)
    lam_table = build_lambda_table(matches, meta, weighting, odds)
    strength = knockout.make_strength(meta, weighting, odds)
    teams = [t for g in all_groups(matches) for t in teams_in_group(g, matches)]
    tally = {t: {s: 0 for s in TOURNEY_STAGES} for t in teams}

    r32_nums = list(knockout.R32_MAP)
    round_nums = {title: order for title, order, _ in knockout.ROUNDS}

    for _ in range(n):
        r32, win = _sim_bracket(matches, meta, lam_table, strength, rng)
        for a, b in r32.values():
            for x in (a, b):
                if x:
                    tally[x]["r32"] += 1            # reached the Round of 32
        for mno in r32_nums:                        # R32 winners reached R16
            if win[mno]:
                tally[win[mno]]["r16"] += 1
        for mno in round_nums["Round of 16"]:       # R16 winners reached QF
            if win[mno]:
                tally[win[mno]]["qf"] += 1
        for mno in round_nums["Quarter-finals"]:    # QF winners reached SF
            if win[mno]:
                tally[win[mno]]["sf"] += 1
        for mno in round_nums["Semi-finals"]:       # SF winners reached the final
            if win[mno]:
                tally[win[mno]]["final"] += 1
        champ = win[round_nums["Final"][0]]
        if champ:
            tally[champ]["champion"] += 1

    return {t: {s: c / n for s, c in d.items()} for t, d in tally.items()}


# round names in bracket order, for team_path
PATH_ROUNDS = ["Round of 32", "Round of 16", "Quarter-finals", "Semi-finals", "Final"]


def team_path(team: str, matches, meta: Optional[dict] = None, n: int = 2000,
              seed: int = 12345, weighting: str = "fifa",
              odds: Optional[dict] = None) -> dict:
    """A team's most-likely 'road to the final' from the same full-tournament sim.

    For each round the team reaches, tally the opponents it faces and how often it
    advances. Returns {"n", "team", "rounds": [
        {round, reach, advance, opp, opp_p, dist}, ...]} where:
      reach   = P(team plays a match in this round)
      advance = P(win that match | reached the round)
      opp     = most-frequent opponent at this round (conditional on reaching)
      opp_p   = P(that opponent | reached); dist = top-3 [(opp, frac)]."""
    from collections import Counter

    from . import knockout
    meta = meta or {}
    rng = random.Random(seed)
    lam_table = build_lambda_table(matches, meta, weighting, odds)
    strength = knockout.make_strength(meta, weighting, odds)

    # match_no -> round name, and feeder -> (parent_match, sibling_feeder)
    match_round = {mno: "Round of 32" for mno in knockout.R32_MAP}
    child_of: dict[int, tuple] = {}
    for title, order, feed in knockout.ROUNDS:
        if feed is None:
            continue
        for parent in order:
            match_round[parent] = title
            fa, fb = feed[parent]
            child_of[fa] = (parent, fb)
            child_of[fb] = (parent, fa)

    reach = {rd: 0 for rd in PATH_ROUNDS}
    advanced = {rd: 0 for rd in PATH_ROUNDS}
    opp = {rd: Counter() for rd in PATH_ROUNDS}

    for _ in range(n):
        r32, win = _sim_bracket(matches, meta, lam_table, strength, rng)
        mno = next((m for m, (a, b) in r32.items() if team in (a, b)), None)
        if mno is None:
            continue                                # team didn't reach the R32
        a, b = r32[mno]
        other, won = (b if a == team else a), win[mno] == team
        while True:
            rd = match_round[mno]
            reach[rd] += 1
            if other:
                opp[rd][other] += 1
            if won:
                advanced[rd] += 1
            if not (won and mno in child_of):
                break
            parent, sib = child_of[mno]
            other, won, mno = win[sib], win[parent] == team, parent

    rounds = []
    for rd in PATH_ROUNDS:
        rc = reach[rd]
        if not rc:
            continue
        top_opp, top_c = (opp[rd].most_common(1)[0] if opp[rd] else (None, 0))
        rounds.append({
            "round": rd, "reach": rc / n, "advance": advanced[rd] / rc,
            "opp": top_opp, "opp_p": top_c / rc,
            "dist": [(o, c / rc) for o, c in opp[rd].most_common(3)],
        })
    return {"n": n, "team": team, "rounds": rounds}


def game_importance(team: str, matches, meta, fixture, n: int = 1500,
                    weighting: str = "fifa", odds: Optional[dict] = None) -> dict:
    """How much a single game swings `team`'s qualification probability."""
    found = _find_fixture(matches, *fixture)
    if not found:
        raise ValueError(f"No fixture matching {fixture}.")
    m, _ = found
    out = {}
    for label, (hg, ag) in (
        (f"{m.home} win", (2, 0)),
        ("draw", (1, 1)),
        (f"{m.away} win", (0, 2)),
    ):
        probs = monte_carlo(matches, meta, n=n, fix=[(m.home, hg, ag, m.away)],
                            weighting=weighting, odds=odds)
        out[label] = probs[team]["qualify"]
    swing = max(out.values()) - min(out.values())
    return {"fixture": f"{m.home} vs {m.away}", "team": team,
            "by_result": out, "swing": swing}
