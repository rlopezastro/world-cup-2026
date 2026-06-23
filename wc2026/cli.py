"""Command-line interface for the World Cup 2026 scenario tool."""

from __future__ import annotations

import argparse
import os
import re
import sys

from . import data
from .tiebreakers import all_groups, group_rows, project, teams_in_group, find_group
from . import analysis, knockout
from . import odds as oddsmod

HERE = os.path.dirname(__file__)
SAMPLE = os.path.join(os.path.dirname(HERE), "sample_data.json")
DEFAULT_CACHE = os.path.join(os.path.dirname(HERE), "cache.json")
DEFAULT_ODDS = os.path.join(os.path.dirname(HERE), "betting_odds.json")
SECRETS_F = os.path.join(os.path.expanduser("~"), ".config", "wc2026", "secrets.json")


def _secret(name):
    """A saved API key from the shared secrets file (same one the app writes)."""
    try:
        import json as _json
        with open(SECRETS_F) as fh:
            return _json.load(fh).get(name, "")
    except (OSError, ValueError):
        return ""


def _load_odds(args):
    """Load betting odds (normalised) from --odds or the default file."""
    return oddsmod.load_odds(getattr(args, "odds", None) or DEFAULT_ODDS)


def _weighting(args):
    """('fifa'|'odds', odds_dict) honouring --weighting and odds availability."""
    w = getattr(args, "weighting", "fifa")
    if w == "odds":
        od = _load_odds(args)
        if not (od.get("matches") or od.get("outrights_strength")):
            print("  (no betting odds found — falling back to FIFA weighting; "
                  "run `fetch-odds` or add betting_odds.json)")
            return "fifa", None
        return "odds", od
    return "fifa", None


# ---------------------------------------------------------------------------
# loading / resolving
# ---------------------------------------------------------------------------
def _load(args):
    if args.data:
        path = args.data
    elif os.path.exists(DEFAULT_CACHE):
        path = DEFAULT_CACHE
    else:
        path = SAMPLE
    matches = data.load_file(path)
    meta = data.load_meta(args.meta) if args.meta else data.load_meta(
        os.path.join(os.path.dirname(HERE), "meta.json"))
    return matches, meta, path


def _resolve_team(query: str, matches) -> str:
    names = {t for g in all_groups(matches) for t in teams_in_group(g, matches)}
    q = query.lower()
    exact = [n for n in names if n.lower() == q]
    if exact:
        return exact[0]
    hits = sorted(n for n in names if q in n.lower())
    if len(hits) == 1:
        return hits[0]
    if not hits:
        sys.exit(f"No team matches '{query}'.")
    sys.exit(f"'{query}' is ambiguous: {', '.join(hits)}")


def _bar(p: float, width: int = 20) -> str:
    filled = round(p * width)
    return "█" * filled + "·" * (width - filled)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_fetch(args):
    token = args.token or os.environ.get("FOOTBALL_DATA_TOKEN") or _secret("football_data")
    if not token:
        sys.exit("Need an API token: --token, FOOTBALL_DATA_TOKEN env var, or a saved key.\n"
                 "Get a free key at https://www.football-data.org/client/register")
    matches = data.fetch_live(token)
    data.save_file(DEFAULT_CACHE, matches)
    played = sum(1 for m in matches if m.played)
    print(f"Fetched {len(matches)} group matches ({played} played) -> {DEFAULT_CACHE}")


def _ago(dt, now):
    """Human 'x ago' / 'in x' for a datetime relative to now."""
    if dt is None:
        return "unknown"
    secs = (now - dt).total_seconds()
    future = secs < 0
    secs = abs(secs)
    if secs < 90:
        s = f"{int(secs)} sec"
    elif secs < 5400:
        s = f"{round(secs / 60)} min"
    elif secs < 172800:
        s = f"{round(secs / 3600)} hr"
    else:
        s = f"{round(secs / 86400)} days"
    return f"in {s}" if future else f"{s} ago"


def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "—"


def cmd_freshness(args):
    matches, _, path = _load(args)
    f = data.source_freshness(matches)
    now = f["now"]
    print(f"\nData file: {os.path.basename(path)}")
    if not f["has_timestamps"]:
        print("  This file has no source timestamps (it predates timestamping,\n"
              "  or it's the bundled sample). Run `fetch` to record them.")
        return
    asof = f["source_as_of"]
    print(f"  Results last updated by the source: {_fmt(asof)}  ({_ago(asof, now)})")
    c = f["counts"]
    print(f"  Matches: {c['finished']} finished, {c['live']} in progress, "
          f"{c['scheduled']} upcoming  ({c['total']} total)")
    lf = f["latest_finished"]
    if lf:
        ko = data.parse_dt(lf.kickoff)
        score = f"{lf.home} {lf.home_goals}-{lf.away_goals} {lf.away}"
        print(f"  Most recent finished game: {score}")
        print(f"     (kicked off {_fmt(ko)}, {_ago(ko, now)})")
    for m in f["live_matches"]:
        print(f"  ▶ IN PROGRESS: {m.home} vs {m.away}")
    nm = f["next_match"]
    if nm:
        ko = data.parse_dt(nm.kickoff)
        print(f"  Next kickoff: {nm.home} vs {nm.away}  ({_fmt(ko)}, {_ago(ko, now)})")
    print("\n  Note: the free tier serves slightly delayed scores, so the source\n"
          "  timestamp can lag the live match by a few minutes.")


def cmd_table(args):
    matches, meta, path = _load(args)
    groups = [args.group.upper()] if args.group else all_groups(matches)
    proj = project(matches, meta)
    qualified_thirds = set(proj.qualified_thirds)
    for g in groups:
        rows = group_rows(g, matches, meta)
        print(f"\nGroup {g}")
        print(f"  {'#':<2}{'Team':<22}{'P':>2}{'W':>3}{'D':>3}{'L':>3}"
              f"{'GF':>4}{'GA':>4}{'GD':>4}{'Pts':>5}")
        for i, r in enumerate(rows, 1):
            mark = ""
            if i <= 2:
                mark = "  ✅"
            elif i == 3:
                mark = "  ✅(3rd)" if r.team in qualified_thirds else "  …3rd"
            print(f"  {i:<2}{r.team:<22}{r.played:>2}{r.won:>3}{r.drawn:>3}"
                  f"{r.lost:>3}{r.gf:>4}{r.ga:>4}{r.gd:>+4}{r.points:>5}{mark}")
    if not args.group:
        print("\nBest third-placed teams (top 8 qualify):")
        for i, r in enumerate(proj.thirds_ranked, 1):
            tag = "✅" if i <= 8 else "❌"
            print(f"  {i:>2}. {tag} Group {r.group:<2} {r.team:<22} "
                  f"{r.points} pts, GD {r.gd:+d}, {r.gf} GF")
    print(f"\n(data: {os.path.basename(path)})")


def cmd_status(args):
    matches, meta, _ = _load(args)
    team = _resolve_team(args.team, matches)
    s = analysis.team_status(team, matches, meta)
    print(f"\n{team}  (Group {s['group']})")
    print(f"  Currently: {_ord(s['current_position'])}, "
          f"{s['current_points']} pts, GD {s['current_gd']:+d}, "
          f"{s['team_games_left']} game(s) left")
    print(f"  Possible final group positions: "
          f"{', '.join(_ord(p) for p in s['possible_positions'])}")
    print(f"\n  >> {s['headline']}")
    if s["level"] == "alive-third" and s.get("current_third_rank"):
        verdict = "would QUALIFY" if s["current_projection_qualified"] else "would be OUT"
        print(f"     On today's results it is the #{s['current_third_rank']} "
              f"third-placed team -> {verdict}.")
        print("     Run `sim` for qualification odds across the third-place race.")
    if not s["exact"]:
        print("     (note: many games left — result enumeration is approximate.)")


def cmd_needs(args):
    matches, meta, _ = _load(args)
    team = _resolve_team(args.team, matches)
    r = analysis.what_they_need(team, matches, meta)
    if r.get("no_more_games"):
        print(f"{team} has finished its group games. Use `status` / `sim`.")
        return
    print(f"\n{team} — next game: {r['fixture']}")
    labels = {"W": "If they WIN ", "D": "If they DRAW", "L": "If they LOSE"}
    for res in ("W", "D", "L"):
        if res not in r["summary"]:
            continue
        g = r["summary"][res]["guaranteed"]
        b = r["summary"][res]["best"]
        guar = analysis._POS_MEANING[g]
        if g == b:
            print(f"  {labels[res]}: guaranteed to {guar}.")
        else:
            best = analysis._POS_MEANING[b]
            print(f"  {labels[res]}: at worst {guar}; at best {best} "
                  f"(depends on other games).")
    if not r["exact"]:
        print("  (note: many games left — enumeration is approximate.)")


def _parse_score(spec: str):
    m = re.match(r"^(.*?)\s+(\d+)\s*-\s*(\d+)\s+(.*)$", spec.strip())
    if not m:
        sys.exit(f"Bad result '{spec}'. Use:  \"Team A 2-1 Team B\"")
    t1, g1, g2, t2 = m.groups()
    return (t1.strip(), int(g1), int(g2), t2.strip())


def cmd_scenario(args):
    matches, meta, _ = _load(args)
    overrides = [_parse_score(s) for s in args.results]
    new = analysis.apply_overrides(matches, overrides)
    print("Applied hypothetical result(s):")
    for t1, g1, g2, t2 in overrides:
        print(f"  {t1} {g1}-{g2} {t2}")
    proj = project(new, meta)
    if args.team:
        team = _resolve_team(args.team, new)
        s = analysis.team_status(team, new, meta)
        print(f"\nEffect on {team}:")
        print(f"  >> {s['headline']}")
        verdict = "IN ✅" if team in proj.qualified() else "OUT ❌"
        print(f"  Projected (if all other remaining games went as-is/unplayed): {verdict}")
        g = s["group"]
        print(f"\nProjected Group {g}:")
        for i, row in enumerate(proj.group_order[g], 1):
            print(f"  {i}. {row.team:<22} {row.points} pts, GD {row.gd:+d}")
    else:
        print("\nProjected qualifiers (group winners, runners-up, best-8 thirds):")
        print("  Winners:    " + ", ".join(proj.winners))
        print("  Runners-up: " + ", ".join(proj.runners_up))
        print("  Best thirds:" + ", ".join(proj.qualified_thirds))


def cmd_fetch_odds(args):
    key = args.odds_key or os.environ.get("ODDS_API_KEY") or _secret("odds_api")
    if not key:
        sys.exit("Need an Odds API key: --odds-key, ODDS_API_KEY env var, or a saved key.\n"
                 "Get a free key at https://the-odds-api.com (500 req/month).")
    matches, _, _ = _load(args)
    teams = sorted({t for g in all_groups(matches) for t in teams_in_group(g, matches)})
    fetched = oddsmod.fetch_odds(key, teams)
    unmatched = fetched.pop("unmatched", [])
    out = args.odds or DEFAULT_ODDS
    oddsmod.save_odds(out, fetched)
    print(f"Fetched {len(fetched.get('matches', {}))} match + "
          f"{len(fetched.get('outrights', {}))} outright prices -> {out}")
    if unmatched:
        print(f"  ⚠️  unmatched provider names (add to odds.NAME_ALIASES): "
              f"{', '.join(unmatched)}")


def cmd_bracket(args):
    matches, meta, _ = _load(args)
    mode = args.mode
    if mode == "standings":
        view = knockout.bracket_view(matches, meta, mode="standings")
    else:
        w, od = ("odds", _load_odds(args)) if mode == "odds" else ("fifa", None)
        if mode == "odds" and not (od.get("matches") or od.get("outrights_strength")):
            print("  (no betting odds found — using FIFA sim instead)")
            mode, w, od = "fifa", "fifa", None
        probs = analysis.monte_carlo(matches, meta, n=args.n, weighting=w, odds=od)
        view = knockout.bracket_view(matches, meta, mode=mode, probs=probs, odds=od)
    res = view["results"]
    print(f"\nKnockout bracket — mode: {mode}")
    for title, order, _feed in knockout.ROUNDS:
        print(f"\n{title}:")
        for mno in order:
            d = res.get(mno, {})
            a, b, wn = d.get("a"), d.get("b"), d.get("winner")
            mark_a = " ✓" if a == wn else ""
            mark_b = " ✓" if b == wn else ""
            print(f"  M{mno}: {a or 'TBD'}{mark_a}  vs  {b or 'TBD'}{mark_b}")
    print(f"\n🏆 Projected champion: {view['champion']}")


def cmd_sim(args):
    matches, meta, _ = _load(args)
    weighting, od = _weighting(args)
    probs = analysis.monte_carlo(matches, meta, n=args.n, weighting=weighting, odds=od)
    tag = "betting-odds" if weighting == "odds" else "FIFA-ranking"
    if args.team:
        team = _resolve_team(args.team, matches)
        p = probs[team]
        print(f"\n{team} — qualification odds ({args.n} {tag} simulations):")
        print(f"  Win group:   {p['win_group']*100:5.1f}%  {_bar(p['win_group'])}")
        print(f"  Top 2:       {p['top2']*100:5.1f}%  {_bar(p['top2'])}")
        print(f"  Reach R32:   {p['qualify']*100:5.1f}%  {_bar(p['qualify'])}")
        return
    group = args.group.upper() if args.group else None
    rows = []
    for t, p in probs.items():
        if group and find_group(t, matches) != group:
            continue
        rows.append((t, p["qualify"]))
    rows.sort(key=lambda x: -x[1])
    print(f"\nReach Round of 32 — probability ({args.n} {tag} sims):")
    for t, q in rows[: args.top]:
        print(f"  {q*100:5.1f}%  {_bar(q)}  {t}")


def cmd_importance(args):
    matches, meta, _ = _load(args)
    team = _resolve_team(args.team, matches)
    if " vs " not in args.fixture.lower():
        sys.exit('Fixture must look like:  "Team A vs Team B"')
    h, a = re.split(r"\s+vs\s+", args.fixture, flags=re.I)
    weighting, od = _weighting(args)
    res = analysis.game_importance(team, matches, meta, (h.strip(), a.strip()),
                                   n=args.n, weighting=weighting, odds=od)
    print(f"\nHow much does \"{res['fixture']}\" matter for {team}?")
    print(f"  ({args.n} sims; the other remaining games are simulated)")
    for label, q in res["by_result"].items():
        print(f"   {label:<28} -> reach R32 {q*100:5.1f}%  {_bar(q)}")
    print(f"\n  Swing in {team}'s qualification odds: {res['swing']*100:.1f} "
          f"percentage points.")


def _ord(n: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(n, f"{n}th")


# ---------------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="wc2026",
        description="2026 World Cup group-stage scenario tool "
                    "(clinch / eliminate / qualify, with 2026 tiebreakers).")
    p.add_argument("--data", help="path to a matches JSON file (default: cache or sample)")
    p.add_argument("--meta", help="path to meta.json (fifa_ranking / conduct)")
    p.add_argument("--token", help="football-data.org API token (for `fetch`)")
    p.add_argument("--odds", help="path to betting_odds.json (default: repo root)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("fetch", help="pull live results from football-data.org").set_defaults(func=cmd_fetch)

    fo = sub.add_parser("fetch-odds", help="pull betting odds from The Odds API")
    fo.add_argument("--odds-key", help="The Odds API key (or ODDS_API_KEY env var)")
    fo.set_defaults(func=cmd_fetch_odds)

    sub.add_parser("freshness", help="show how recent the source data is").set_defaults(func=cmd_freshness)

    t = sub.add_parser("table", help="show group standings")
    t.add_argument("group", nargs="?", help="single group letter, e.g. A")
    t.set_defaults(func=cmd_table)

    st = sub.add_parser("status", help="clinch/eliminate status for a team")
    st.add_argument("team")
    st.set_defaults(func=cmd_status)

    nd = sub.add_parser("needs", help="what a team needs from its next game")
    nd.add_argument("team")
    nd.set_defaults(func=cmd_needs)

    sc = sub.add_parser("scenario", help="apply hypothetical result(s) and see the effect")
    sc.add_argument("results", nargs="+", help='e.g. "Argentina 2-1 Brazil"')
    sc.add_argument("--team", help="focus the report on this team")
    sc.set_defaults(func=cmd_scenario)

    sm = sub.add_parser("sim", help="Monte Carlo qualification probabilities")
    sm.add_argument("--n", type=int, default=3000, help="number of simulations")
    sm.add_argument("--team", help="one team's odds")
    sm.add_argument("--group", help="restrict the leaderboard to one group")
    sm.add_argument("--top", type=int, default=20, help="how many teams to list")
    sm.add_argument("--weighting", choices=["fifa", "odds"], default="fifa",
                    help="strength model: FIFA ranking (default) or betting odds")
    sm.set_defaults(func=cmd_sim)

    im = sub.add_parser("importance", help="how much a single game swings a team's odds")
    im.add_argument("team")
    im.add_argument("fixture", help='e.g. "Mexico vs Croatia"')
    im.add_argument("--n", type=int, default=2000)
    im.add_argument("--weighting", choices=["fifa", "odds"], default="fifa",
                    help="strength model: FIFA ranking (default) or betting odds")
    im.set_defaults(func=cmd_importance)

    bk = sub.add_parser("bracket", help="seed + play out the knockout bracket")
    bk.add_argument("--mode", choices=["standings", "fifa", "odds"],
                    default="standings", help="how to populate the 32 slots")
    bk.add_argument("--n", type=int, default=3000, help="sims for the 'fifa'/'odds' modes")
    bk.set_defaults(func=cmd_bracket)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
