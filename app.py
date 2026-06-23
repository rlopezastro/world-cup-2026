"""Streamlit front-end for the World Cup 2026 scenario engine.

Run it with:   streamlit run app.py
(use the worldcup env: /path/to/envs/worldcup/bin/streamlit run app.py)
"""

import json
import os
from datetime import datetime, timedelta, timezone

import altair as alt
import pandas as pd
import streamlit as st

from wc2026 import analysis, data, fifa, flags, knockout, odds as oddsmod
from wc2026.tiebreakers import (all_groups, find_group, group_rows, project,
                                teams_in_group)

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache.json")
SAMPLE = os.path.join(HERE, "sample_data.json")
META_F = os.path.join(HERE, "meta.json")
SCORERS_CACHE = os.path.join(HERE, "scorers.json")
SQUADS_F = os.path.join(HERE, "squads.json")
BETTING_F = os.path.join(HERE, "betting_odds.json")
FAR = datetime(2100, 1, 1, tzinfo=timezone.utc)
GREEN_RED = alt.Scale(scheme="redyellowgreen", domain=[0, 100])
GOAL_AXIS = alt.Axis(tickMinStep=1, format="d")   # goals/whole-number axis
PANEL_H = 520                                      # scorer panel height (px)

st.set_page_config(page_title="World Cup 2026 Scenarios", page_icon="🏆",
                   layout="wide")


# ---------------------------------------------------------------------------
# data loading (cached, keyed on the file's mtime so a fetch busts the cache)
# ---------------------------------------------------------------------------
def _data_path():
    return CACHE if os.path.exists(CACHE) else SAMPLE


@st.cache_data(show_spinner=False)
def _load(path, mtime):
    return data.load_file(path), data.load_meta(META_F)


def load():
    path = _data_path()
    return (*_load(path, os.path.getmtime(path)), path)


def betting_sig():
    """Cache-busting fingerprint for the betting odds file (0 when absent)."""
    return os.path.getmtime(BETTING_F) if os.path.exists(BETTING_F) else 0.0


@st.cache_data(show_spinner=False)
def load_odds(sig):
    return oddsmod.load_odds(BETTING_F)


def have_odds(sig=None):
    o = load_odds(betting_sig() if sig is None else sig)
    return bool(o.get("matches") or o.get("outrights_strength"))


LIVE_WINDOW_MIN = 150   # minutes after kickoff a match may plausibly still be in play


def _in_live_window(matches):
    """True if 'now' falls inside any not-yet-final match's plausible in-play window.
    Used to decide whether to poll for live scores (so we never burn requests when no
    game could be on)."""
    now = datetime.now(timezone.utc)
    for m in matches:
        if m.played:
            continue
        ko = data.parse_dt(m.kickoff)
        if ko and ko <= now <= ko + timedelta(minutes=LIVE_WINDOW_MIN):
            return True
    return False


@st.cache_data(ttl=110, show_spinner=False)
def _shared_live_fetch(token):
    """One live-scores fetch shared across all viewer sessions (TTL-deduped), so N
    concurrent viewers still cost ~1 API request per ~2-minute refresh cycle."""
    return [m.to_dict() for m in data.fetch_live(token)]


@st.cache_data(show_spinner="🎲 Running qualification simulations…")
def cached_mc(path, mtime, n, weighting="fifa", odds_sig=0.0):
    matches, meta = _load(path, mtime)
    od = load_odds(odds_sig) if weighting == "odds" else None
    return analysis.monte_carlo(matches, meta, n=n, weighting=weighting, odds=od)


@st.cache_data(show_spinner="🏆 Simulating the whole tournament…")
def cached_tourney(path, mtime, n, weighting="fifa", odds_sig=0.0):
    matches, meta = _load(path, mtime)
    od = load_odds(odds_sig) if weighting == "odds" else None
    return analysis.tournament_odds(matches, meta, n=n, weighting=weighting, odds=od)


@st.cache_data(show_spinner="🛣️ Tracing your team's most likely bracket path…")
def cached_path(path, mtime, team, n, weighting="fifa", odds_sig=0.0):
    matches, meta = _load(path, mtime)
    od = load_odds(odds_sig) if weighting == "odds" else None
    return analysis.team_path(team, matches, meta, n=n, weighting=weighting, odds=od)


@st.cache_data(show_spinner="🎲 Simulating each outcome of this game…")
def cached_importance(path, mtime, team, home, away, n, weighting="fifa", odds_sig=0.0):
    matches, meta = _load(path, mtime)
    od = load_odds(odds_sig) if weighting == "odds" else None
    return analysis.game_importance(team, matches, meta, (home, away), n=n,
                                    weighting=weighting, odds=od)


def build_overview(ms, mt):
    """Per-team MATHEMATICALLY CERTAIN verdicts + locked group winners/runners-up.
    Works on any match list (used live via the cached `overview`, and directly on
    hypothetical scenario results).

    medal: 🥇 guaranteed 1st · 🥈 guaranteed 2nd · 🥉 guaranteed 3rd · '' otherwise
    qualified / eliminated: only when provably certain (incl. the best-8 third race).
    """
    q = analysis.qualification_status(ms, mt)   # rigorous third-place bounds
    team, winner, runner = {}, {}, {}
    for g in all_groups(ms):
        for r in group_rows(g, ms, mt):
            s = analysis.team_status(r.team, ms, mt)   # H2H-aware group placement
            pos = s["possible_positions"]
            medal = ("🥇" if pos == [1] else "🥈" if pos == [2]
                     else "🥉" if pos == [3] else "")
            qi = q[r.team]
            top2 = s["worst_possible"] <= 2
            qualified = top2 or qi["qualified"]
            eliminated = s["level"] == "eliminated" or qi["eliminated"]
            via = "top2" if top2 else ("third" if qi["qualified"] else "")
            team[r.team] = {"medal": medal, "qualified": qualified,
                            "eliminated": eliminated, "via": via}
            if pos == [1]:
                winner[g] = r.team
            elif pos == [2]:
                runner[g] = r.team
    return {"team": team, "winner": winner, "runner": runner}


@st.cache_data(show_spinner="Working out who's safe…")
def overview(path, mtime):
    ms, mt = _load(path, mtime)
    return build_overview(ms, mt)


# The bracket structure + forward simulation live in wc2026/knockout.py.
_BRACKET_CSS = """<style>
.bk{display:flex;overflow-x:auto;padding:6px 0;align-items:stretch}
.bk .col{display:flex;flex-direction:column;flex:1;min-width:148px}
.bk .rhd{font-size:11px;font-weight:bold;color:#888;text-align:center;padding-bottom:6px}
.bk .rnd{flex:1;display:flex;flex-direction:column;justify-content:space-around}
.bk .m{position:relative;border:1px solid rgba(127,127,127,.35);border-radius:7px;
  margin:5px 7px;padding:4px 7px;background:rgba(127,127,127,.07);
  font-size:12px;line-height:1.4}
.bk .mn{font-size:9px;color:#999;margin-bottom:1px}
.bk .t.win{font-weight:bold}
.bk .t.lose{opacity:.5}
.bk .col:not(:last-child) .m::after{content:'';position:absolute;right:-7px;top:50%;
  width:7px;height:1px;background:rgba(127,127,127,.45)}
.bk .col:not(:first-child) .m::before{content:'';position:absolute;left:-7px;top:50%;
  width:7px;height:1px;background:rgba(127,127,127,.45)}
</style>"""


def render_slot(slot, ov):
    """A single R32 slot for the exact ‘locked qualifiers’ view: a name only once
    its seed is mathematically decided, otherwise an italic placeholder."""
    typ, val = slot
    if typ == "W":
        t = ov["winner"].get(val)
        return f"🥇 {flags.label(t)}" if t else f"<i>Winner {val}</i>"
    if typ == "R":
        t = ov["runner"].get(val)
        return f"🥈 {flags.label(t)}" if t else f"<i>Runner-up {val}</i>"
    return f"<i>3rd of {'/'.join(val)}</i>"


def locked_bracket_html(ov):
    """The original exact bracket: only mathematically locked seeds are placed;
    third-place slots and undecided seeds stay as italic placeholders."""
    cols = []
    for title, order, feed in knockout.ROUNDS:
        boxes = []
        for mno in order:
            if feed is None:
                l1, l2 = (render_slot(s, ov) for s in knockout.R32_MAP[mno])
            else:
                a, b = feed[mno]
                l1, l2 = f"<i>Winner M{a}</i>", f"<i>Winner M{b}</i>"
            boxes.append(f"<div class='m'><div class='mn'>M{mno}</div>"
                         f"<div class='t'>{l1}</div><div class='t'>{l2}</div></div>")
        cols.append(f"<div class='col'><div class='rhd'>{title}</div>"
                    f"<div class='rnd'>{''.join(boxes)}</div></div>")
    return _BRACKET_CSS + "<div class='bk'>" + "".join(cols) + "</div>"


def played_bracket_html(view):
    """Render a played-out bracket: each match shows both teams with the projected
    winner bolded (✓) and the loser dimmed."""
    res = view["results"]
    cols = []
    for title, order, _feed in knockout.ROUNDS:
        boxes = []
        for mno in order:
            d = res.get(mno, {})
            wn = d.get("winner")

            def cell(t):
                if not t:
                    return "<div class='t'><i>TBD</i></div>"
                cls = "win" if t == wn else "lose"
                return f"<div class='t {cls}'>{flags.label(t)}{' ✓' if t == wn else ''}</div>"

            boxes.append(f"<div class='m'><div class='mn'>M{mno}</div>"
                         f"{cell(d.get('a'))}{cell(d.get('b'))}</div>")
        cols.append(f"<div class='col'><div class='rhd'>{title}</div>"
                    f"<div class='rnd'>{''.join(boxes)}</div></div>")
    return _BRACKET_CSS + "<div class='bk'>" + "".join(cols) + "</div>"


@st.cache_data(show_spinner=False)
def cached_ways(path, mtime, team):
    ms, mt = _load(path, mtime)
    return analysis.ways_through(team, ms, mt, fmt=flags.label)


@st.cache_data(show_spinner="Loading scorers…")
def cached_scorers(token, limit):
    scorers = data.fetch_scorers(token, limit=limit)
    with open(SCORERS_CACHE, "w") as fh:
        json.dump(scorers, fh)
    return scorers


@st.cache_data(show_spinner=False)
def load_squads():
    """Bundled static 26-man squads (no API key — rosters don't change). Returns
    {team_name: [ {name, position, club, caps, goals}, ... ]}."""
    if not os.path.exists(SQUADS_F):
        return {}
    with open(SQUADS_F) as fh:
        return json.load(fh).get("teams", {})


matches, meta, path = load()
mtime = os.path.getmtime(path)
TEAMS = sorted({t for g in all_groups(matches) for t in teams_in_group(g, matches)})

ORD = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}


def fmt_short(iso):
    dtv = data.parse_dt(iso)
    return dtv.strftime("%b %d, %H:%M") if dtv else "TBD"


def pct(p, certain=False):
    """Format a simulated probability, distinguishing proven from near-certain.
    🔒 marks a mathematically decided outcome; otherwise a would-be 100% is shown
    as '99%+' (near-certain, not proven) and a would-be 0% as '<1%'."""
    if certain:
        return "100% 🔒" if p >= 0.5 else "0% 🔒"
    if p >= 0.995:
        return "99%+"
    if p < 0.005:
        return "<1%"
    return f"{round(p * 100)}%"


# ---------------------------------------------------------------------------
# saved API keys (so you don't paste them every time). Stored per-user, outside
# the project folder, readable only by you (chmod 600) — never committed/shared.
# ---------------------------------------------------------------------------
SECRETS_F = os.path.join(os.path.expanduser("~"), ".config", "wc2026", "secrets.json")


def load_secrets():
    try:
        with open(SECRETS_F) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_secret(name, value):
    d = load_secrets()
    if value:
        d[name] = value
    else:
        d.pop(name, None)
    os.makedirs(os.path.dirname(SECRETS_F), exist_ok=True)
    with open(SECRETS_F, "w") as fh:
        json.dump(d, fh)
    os.chmod(SECRETS_F, 0o600)


def _st_secret(name, default=""):
    """Read from Streamlit secrets (st.secrets / secrets.toml) without erroring when
    no secrets file is present (the usual case when running locally)."""
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def get_key(env_name, secret_name):
    """A stored key: environment variable, then Streamlit secrets, then the saved
    local secrets file."""
    return (os.environ.get(env_name) or _st_secret(secret_name)
            or load_secrets().get(secret_name, ""))


# Read-only public deployment: set WC2026_PUBLISHED=1 (or `published = true` in
# Streamlit secrets) to hide all key inputs / fetch controls and serve the bundled,
# pre-fetched JSON only. Data is refreshed out-of-band by a scheduled job.
PUBLISHED = bool(os.environ.get("WC2026_PUBLISHED") or _st_secret("published", False))


# ---------------------------------------------------------------------------
# sidebar: freshness, refresh, global controls
# ---------------------------------------------------------------------------
st.sidebar.title("🏆 World Cup 2026")
st.sidebar.caption("Group-stage scenarios — 2026 rules (H2H before overall GD, "
                   "top 2 + best-8 thirds reach the Round of 32).")

team = st.sidebar.selectbox("Team", TEAMS, format_func=flags.label,
                            index=TEAMS.index("United States") if "United States" in TEAMS else 0)
n_sims = st.sidebar.slider("Simulations (odds accuracy)", 500, 8000, 3000, 500)

st.sidebar.divider()

fresh = data.source_freshness(matches)
if fresh["source_as_of"]:
    age = (fresh["now"] - fresh["source_as_of"]).total_seconds() / 60
    st.sidebar.success(
        f"Data from {fresh['source_as_of']:%Y-%m-%d %H:%M UTC} ({age:.0f} min ago)\n\n"
        f"{fresh['counts']['finished']} finished · {fresh['counts']['live']} live · "
        f"{fresh['counts']['scheduled']} upcoming")
    for m in fresh["live_matches"]:
        st.sidebar.markdown(f"▶ **live:** {flags.label(m.home)} vs {flags.label(m.away)}")
else:
    st.sidebar.info(f"Using **{os.path.basename(path)}** (no source timestamps).")

def _fetch_matches(tok):
    fetched = data.fetch_live(tok)
    data.save_file(CACHE, fetched)
    try:                                    # refresh scorers alongside scores
        with open(SCORERS_CACHE, "w") as fh:
            json.dump(data.fetch_scorers(tok, limit=100), fh)
    except Exception:
        pass                                # scorers are a nice-to-have, never fatal
    return f"⚽ {len(fetched)} matches"


def _fetch_odds(okey):
    fetched = oddsmod.fetch_odds(okey, TEAMS)
    unmatched = fetched.pop("unmatched", [])
    oddsmod.save_odds(BETTING_F, fetched)
    msg = (f"🎰 {len(fetched.get('matches', {}))} match + "
           f"{len(fetched.get('outrights', {}))} outright prices")
    if unmatched:
        msg += f" (⚠️ unmatched: {', '.join(unmatched)})"
    return msg


if PUBLISHED:
    # public deployment: no key inputs / fetch buttons. Odds come from the scheduled
    # job; live SCORES are polled in-app every 2 min (shared across all viewers via a
    # TTL cache) using a server-side key from st.secrets — only while a game is live.
    token, refresh_secs = "", 120
    live_token = _st_secret("football_data")
    live_mode = bool(live_token) and _in_live_window(matches)
    od = load_odds(betting_sig())
    when = od.get("fetched") or "bundled file"
    if live_mode:
        st.sidebar.success("🔴 **Live** — scores auto-refresh every 2 min.")
    elif live_token:
        st.sidebar.caption(f"📡 Live scores refresh automatically during games.\n\n"
                           f"_Odds as of {when}._")
    else:
        st.sidebar.caption(f"📡 Data refreshes automatically on a schedule.\n\n"
                           f"_Odds as of {when}._")
else:
    fd_saved = get_key("FOOTBALL_DATA_TOKEN", "football_data")
    odds_saved = get_key("ODDS_API_KEY", "odds_api")

    # one-click refresh using whatever keys are stored
    if fd_saved or odds_saved:
        if st.sidebar.button("🔄 Refresh all (saved keys)", width="stretch",
                             help="Pull live scores and betting odds in one go, "
                                  "using your saved keys."):
            msgs, errs = [], []
            for label, key, fn in (("scores", fd_saved, _fetch_matches),
                                   ("odds", odds_saved, _fetch_odds)):
                if not key:
                    continue
                try:
                    msgs.append(fn(key))
                except Exception as e:
                    errs.append(f"{label}: {e}")
            st.cache_data.clear()
            for e in errs:
                st.sidebar.error(e)
            if msgs and not errs:
                st.rerun()
            elif msgs:
                st.sidebar.success("Updated " + " · ".join(msgs))

    with st.sidebar.expander("🔄 Refresh live scores"):
        token = st.text_input("football-data.org token", type="password", value=fd_saved)
        remember_fd = st.checkbox("Remember this key on this machine",
                                  value=bool(load_secrets().get("football_data")), key="rem_fd")
        if st.button("Fetch now", width="stretch"):
            if not token:
                st.warning("Enter your API token first.")
            else:
                save_secret("football_data", token if remember_fd else "")
                try:
                    msg = _fetch_matches(token)
                    st.cache_data.clear()
                    st.success(f"Fetched {msg}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Fetch failed: {e}")

    with st.sidebar.expander("🎰 Betting odds (for odds-weighted mode)"):
        od = load_odds(betting_sig())
        if have_odds():
            nm = len(od.get("matches", {}))
            no = len(od.get("outrights_strength", {}))
            when = od.get("fetched") or "manual file"
            st.success(f"Loaded: {nm} match prices · {no} outright prices\n\n_as of {when}_")
        else:
            st.caption("No odds loaded — odds-weighted mode falls back to FIFA ranking. "
                       "Add a key below to fetch, or drop a `betting_odds.json` next to app.py.")
        okey = st.text_input("The Odds API key", type="password", value=odds_saved,
                             help="Free key from the-odds-api.com (500 req/month).")
        remember_odds = st.checkbox("Remember this key on this machine",
                                    value=bool(load_secrets().get("odds_api")), key="rem_odds")
        if st.button("Fetch odds now", width="stretch"):
            if not okey:
                st.warning("Enter your Odds API key first.")
            else:
                save_secret("odds_api", okey if remember_odds else "")
                try:
                    msg = _fetch_odds(okey)
                    st.cache_data.clear()
                    st.success(f"Fetched {msg}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Odds fetch failed: {e}")

    live_mode = st.sidebar.toggle(
        "🔴 Auto-refresh while live", value=False,
        help="Poll the API on a timer and refresh the whole app when scores change.")
    refresh_secs = 120
    if live_mode:
        refresh_secs = st.sidebar.selectbox(
            "Check interval", [60, 120, 300], index=1,
            format_func=lambda s: f"every {s // 60} min")
        st.sidebar.caption(f"~1 API request every {refresh_secs // 60} min while on.")
    live_token = token or os.environ.get("FOOTBALL_DATA_TOKEN", "")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
_TD = "padding:3px 8px"
NAME_CH = max(len(t) for t in TEAMS) + 2   # uniform Team-column width (longest name)


def html_group(g, matches, meta, ov, selected=None):
    """A compact, width-fitting HTML table for one group (no horizontal scroll)."""
    bh = f"{_TD};text-align:center;font-weight:bold"   # bold stat headers
    head = (f"<tr>"
            f"<th style='{_TD};text-align:left'></th>"
            f"<th style='{_TD};text-align:left;min-width:{NAME_CH}ch'>Team</th>"
            f"<th style='{bh}'>MP</th><th style='{bh}'>W</th>"
            f"<th style='{bh}'>D</th><th style='{bh}'>L</th>"
            f"<th style='{bh};text-align:right'>GD</th>"
            f"<th style='{bh};text-align:right'>Pts</th></tr>")
    trs = []
    for i, r in enumerate(rows := group_rows(g, matches, meta), 1):
        info = ov["team"].get(r.team, {})
        rank = info.get("medal") or str(i)
        name = ("⭐ " if r.team == selected else "") + flags.label(r.team)
        bg = ("background:rgba(21,128,61,0.20)" if info.get("qualified")
              else "background:rgba(200,40,40,0.18)" if info.get("eliminated") else "")
        c = f"{_TD};text-align:center"
        rt = f"{_TD};text-align:right"
        trs.append(
            f"<tr style='{bg}'>"
            f"<td style='{_TD}'>{rank}</td>"
            f"<td style='{_TD};white-space:nowrap;min-width:{NAME_CH}ch'>{name}</td>"
            f"<td style='{c}'>{r.played}</td><td style='{c}'>{r.won}</td>"
            f"<td style='{c}'>{r.drawn}</td><td style='{c}'>{r.lost}</td>"
            f"<td style='{rt}'>{r.gd:+d}</td>"
            f"<td style='{rt}'><b>{r.points}</b></td></tr>")
    return ("<table style='border-collapse:collapse;font-size:15px'>"
            f"{head}{''.join(trs)}</table>")


_STAND_CSS = """<style>
.gwrap{display:flex;flex-wrap:wrap;gap:18px;align-items:flex-start}
.gcard{border:1px solid rgba(127,127,127,.20);border-radius:9px;
  padding:8px 12px 10px;background:rgba(127,127,127,.04)}
.gcard .ghd{font-weight:bold;font-size:13px;color:#888;margin-bottom:3px}
</style>"""


def standings_html(matches, meta, ov, selected=None):
    cards = [f"<div class='gcard'><div class='ghd'>Group {g}</div>"
             f"{html_group(g, matches, meta, ov, selected)}</div>"
             for g in all_groups(matches)]
    return _STAND_CSS + "<div class='gwrap'>" + "".join(cards) + "</div>"


def group_picker(label, key, all_label="All groups"):
    """Selectbox whose options show each group's four flags."""
    def fmt(o):
        if o == all_label:
            return all_label
        return f"Group {o} - " + " ".join(flags.flag(t) or "·"
                                          for t in teams_in_group(o, matches))
    return st.selectbox(label, [all_label] + all_groups(matches),
                        format_func=fmt, key=key)


_CAL_CSS = """<style>
.daywrap{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-start}
.daycard{border:1px solid rgba(127,127,127,.20);border-radius:10px;
  padding:8px 14px 10px;min-width:250px;background:rgba(127,127,127,.04)}
.dayhdr{font-weight:bold;font-size:13px;color:#888;margin-bottom:5px}
.srow{font-size:13px;line-height:1.95;white-space:nowrap}
.stime{color:#999;font-size:11px;display:inline-block;width:38px}
.sgrp{color:#aaa;font-size:10px;margin-left:6px}
</style>"""


def calendar_html(matches, gsel, selected=None):
    """Day-cards: one card per match-day with times, names, and scores."""
    ms = [m for m in matches if gsel == "All groups" or m.group == gsel]
    byday = {}
    for m in ms:
        dt = data.parse_dt(m.kickoff)
        if dt:
            dt = dt.astimezone()  # UTC -> the machine's local timezone
        byday.setdefault(dt.date() if dt else None, []).append((dt, m))
    if not byday:
        return "<i>No scheduled matches.</i>"
    cards = []
    for day in sorted(byday, key=lambda d: (d is None, d)):
        hdr = day.strftime("%a · %b %-d") if day else "Date TBD"
        rows = ""
        for dt, m in sorted(byday[day], key=lambda x: (x[0] is None, x[0] or FAR)):
            time = dt.strftime("%H:%M") if dt else "--:--"
            sh = ("⭐" if selected == m.home else "") + flags.label(m.home)
            sa = flags.label(m.away) + ("⭐" if selected == m.away else "")
            if m.played:
                score = f"<b>{m.home_goals}–{m.away_goals}</b>"
            elif (m.status or "").upper() in ("IN_PLAY", "PAUSED", "LIVE"):
                score = "🔴"
            else:
                score = "<span style='color:#999'>v</span>"
            rows += (f"<div class='srow'><span class='stime'>{time}</span>"
                     f"{sh} &nbsp;{score}&nbsp; {sa}"
                     f"<span class='sgrp'>Grp {m.group}</span></div>")
        cards.append(f"<div class='daycard'><div class='dayhdr'>{hdr}</div>{rows}</div>")
    return _CAL_CSS + "<div class='daywrap'>" + "".join(cards) + "</div>"


@st.fragment
def players_panel(scorers):
    """Title + 'show top' slider + bar chart (flags on labels). Lives in a
    fragment so the slider re-renders only this panel, not the whole app."""
    ht = st.columns([1, 1.5])
    ht[0].markdown("**🏃 Players**")
    n = ht[1].slider("Show top", 5, len(scorers), min(15, len(scorers)),
                     key="sc_n", label_visibility="collapsed",
                     help="How many players to show")
    df = pd.DataFrame([{
        "Player": f"{flags.flag(s.get('team'))} {s.get('player') or ''}".strip(),
        "Team": flags.label(s.get("team")),
        "⚽": s.get("goals", 0), "🅰": s.get("assists", 0),
    } for s in scorers[:n]])
    with st.container(height=PANEL_H):
        b = alt.Chart(df).encode(
            y=alt.Y("Player:N", sort="-x", title=None, axis=alt.Axis(labelOverlap=False)),
            x=alt.X("⚽:Q", title="Goals", axis=GOAL_AXIS))
        bars = b.mark_bar(cornerRadiusEnd=3, color="#2a7").encode(
            tooltip=["Player", "Team", "⚽", "🅰"])
        text = b.mark_text(align="left", dx=3, fontSize=11, color="#aaa").encode(
            text="⚽:Q")
        st.altair_chart((bars + text).properties(height=alt.Step(20)), width="stretch")


def hbar(df, value_col, label_col, x_title, height_step=19):
    base = alt.Chart(df).encode(
        y=alt.Y(f"{label_col}:N", sort="-x", title=None,
                axis=alt.Axis(labelOverlap=False, labelLimit=220, labelFontSize=12)),
        x=alt.X(f"{value_col}:Q", title=x_title, scale=alt.Scale(domain=[0, 100])))
    bars = base.mark_bar(cornerRadiusEnd=3).encode(
        color=alt.Color(f"{value_col}:Q", scale=GREEN_RED, legend=None),
        tooltip=[alt.Tooltip(f"{label_col}:N", title="Team"),
                 alt.Tooltip(f"{value_col}:Q", title="%", format=".1f")])
    text = base.mark_text(align="left", dx=3, color="#555", fontSize=11).encode(
        text=alt.Text(f"{value_col}:Q", format=".0f"))
    return (bars + text).properties(height=alt.Step(height_step))


# ---------------------------------------------------------------------------
# tabs
# ---------------------------------------------------------------------------
@st.fragment(run_every=refresh_secs if live_mode else None)
def _auto_refresh():
    """When live mode is on: re-fetch on a timer, and rerun the whole app only
    when the results actually changed (so we don't re-simulate every tick)."""
    if not live_mode or not live_token:
        return
    try:
        fetched = _shared_live_fetch(live_token)        # list[dict], shared/deduped
    except Exception:
        return
    current = data.load_file(CACHE) if os.path.exists(CACHE) else []
    if fetched != [m.to_dict() for m in current]:
        # write the new scores; the data caches are keyed on the file mtime, so the
        # rerun picks them up automatically (no global cache clear needed)
        data.save_file(CACHE, [data.Match.from_dict(d) for d in fetched])
        st.rerun()


_auto_refresh()

# A nav selector (not st.tabs) so only the SELECTED section's code runs each render.
# st.tabs renders every tab body on every run — which would re-run every simulation
# on each load. With this, the heavy sim tabs compute lazily, only when opened
# (and stay cached afterwards). `nav` persists across reruns via its key, so a live
# score update doesn't bounce you off your current section.
NAV = ["📊 Standings", "🗝️ Knockout", "🎯 Team", "🆚 H2H", "🔮 Scenario",
       "⚖️ Importance", "📈 Odds", "🏆 Title Odds", "⚽ Top Scorers", "📅 Schedule",
       "👕 Rosters", "🌍 FIFA Rank"]
nav = st.radio("Section", NAV, horizontal=True, label_visibility="collapsed", key="nav")

# ---- Standings ----
if nav == "📊 Standings":
    st.subheader("Group standings")
    proj = project(matches, meta)
    ov = overview(path, mtime)
    st.caption("🥇 guaranteed winner · 🥈 guaranteed runner-up · 🥉 guaranteed 3rd · "
               "🟩 qualified for the Round of 32 · 🟥 eliminated · ⭐ your selected team")
    st.markdown(standings_html(matches, meta, ov, selected=team),
                unsafe_allow_html=True)
    st.subheader("Best third-placed teams — top 8 reach the Round of 32")
    tr = pd.DataFrame([
        {"Rank": i, "In?": "✅" if i <= 8 else "❌", "Group": r.group,
         "Team": flags.label(r.team), "Pts": r.points, "GD": r.gd, "GF": r.gf}
        for i, r in enumerate(proj.thirds_ranked, 1)]).set_index("Rank")
    st.dataframe(tr, width="stretch")

# ---- Knockout ----
if nav == "🗝️ Knockout":
    st.subheader("🗝️ Knockout bracket")
    _KO_MODES = {
        "Locked qualifiers only (exact)": "locked",
        "Projected — current standings": "standings",
        "Projected — most likely (FIFA-ranking sim)": "fifa",
        "Projected — most likely (betting-odds sim)": "odds",
    }
    choice = st.selectbox(
        "Populate the bracket from…", list(_KO_MODES),
        help="Default shows only mathematically locked seeds (the real qualifiers so "
             "far), rest left blank. The ‘Projected’ modes fill every slot and advance "
             "the favourite of each tie: from the current table, or from the simulation.")
    ko_mode = _KO_MODES[choice]
    osig = betting_sig()
    if ko_mode == "odds" and not have_odds(osig):
        st.warning("No betting odds loaded — using the FIFA-ranking sim instead. "
                   "Add odds in the sidebar’s **Betting odds** panel.")
        ko_mode = "fifa"

    if ko_mode == "locked":
        ov = overview(path, mtime)
        st.markdown(locked_bracket_html(ov), unsafe_allow_html=True)
        through_tbd = sorted(t for t, info in ov["team"].items()
                             if info["qualified"] and not info["medal"])
        if through_tbd:
            st.success("**Through, seeding not yet locked:** "
                       + ", ".join(flags.label(t) for t in through_tbd))
        st.caption("Exact view: 🥇 a guaranteed group winner and 🥈 a team locked into "
                   "2nd drop into their real slots; *italic* = not yet decided. Third-place "
                   "slots show their candidate groups — the actual assignment follows FIFA’s "
                   "Annex-C table, fixed once every group finishes. Switch the dropdown above "
                   "for a fully projected, played-out bracket.")
    else:
        if ko_mode == "standings":
            view = knockout.bracket_view(matches, meta, mode="standings")
        else:
            kprobs = cached_mc(path, mtime, n_sims, ko_mode, osig)
            view = knockout.bracket_view(matches, meta, mode=ko_mode, probs=kprobs,
                                         odds=load_odds(osig))
        champ = view["champion"]
        if champ:
            st.success(f"🏆 Projected champion: **{flags.label(champ)}**")
        st.markdown(played_bracket_html(view), unsafe_allow_html=True)
        st.caption(
            "✓ = projected to advance (favourite by "
            f"{'betting strength' if ko_mode == 'odds' else 'FIFA ranking'}); the loser is "
            "dimmed. Third-placed teams are placed by FIFA’s official Annex-C table "
            "(all 495 combinations) once the eight qualifying thirds are set; partial "
            "brackets use a legal interim matching.")

# ---- Title Odds ----
_STAGE_COLS = [("r16", "Reach R16"), ("qf", "Reach QF"), ("sf", "Reach SF"),
               ("final", "Reach Final"), ("champion", "Win 🏆")]

if nav == "🏆 Title Odds":
    st.subheader("🏆 Title odds — deep-run probabilities")
    osig = betting_sig()
    twlabel = st.radio(
        "Weighting model", ["FIFA ranking", "Betting odds"], horizontal=True,
        key="title_weighting",
        help="Strength model for both the group-stage draws and the knockout ties.")
    tw = "odds" if twlabel == "Betting odds" else "fifa"
    if tw == "odds" and not have_odds(osig):
        st.warning("No betting odds loaded — using FIFA-ranking strength instead.")
        tw = "fifa"
    tprobs = cached_tourney(path, mtime, n_sims, tw, osig)
    st.caption(
        f"**{'Betting odds' if tw == 'odds' else 'FIFA ranking'}** model · {n_sims:,} "
        "simulations. Each % is the chance of reaching that round or further.")

    # selected team's run
    d = tprobs[team]
    st.markdown(f"#### {flags.label(team)}")
    cols = st.columns(len(_STAGE_COLS))
    for col, (key, lbl) in zip(cols, _STAGE_COLS):
        col.metric(lbl, f"{d[key] * 100:.1f}%")

    # most-likely road to the final
    st.markdown("##### 🛣️ Most likely road to the final")
    tpath = cached_path(path, mtime, team, n_sims, tw, osig)
    if not tpath["rounds"]:
        st.info(f"{flags.label(team)} is not projected to reach the Round of 32 in any "
                "simulation.")
    else:
        prows = [{"Round": r["round"], "Reach": r["reach"] * 100,
                  "Most likely opponent": flags.label(r["opp"]) if r["opp"] else "—",
                  "vs them": r["opp_p"] * 100, "Win round": r["advance"] * 100}
                 for r in tpath["rounds"]]
        st.dataframe(
            pd.DataFrame(prows), width="stretch", hide_index=True,
            column_config={c: st.column_config.NumberColumn(c, format="%.0f%%")
                           for c in ("Reach", "vs them", "Win round")})
        st.caption("**Reach** = chance of playing that round · **Most likely opponent** "
                   "(and **vs them** = chance that's who you face, given you get there) · "
                   "**Win round** = chance of advancing past that round, if reached.")

    # championship contenders
    st.subheader("Who wins it? — championship probability")
    crows = [{"Team": flags.label(t) + (" ⭐" if t == team else ""),
              "pct": tprobs[t]["champion"] * 100} for t in TEAMS]
    cdf = pd.DataFrame([r for r in crows if r["pct"] > 0.05]).sort_values(
        "pct", ascending=False).head(24)
    cbase = alt.Chart(cdf).encode(
        y=alt.Y("Team:N", sort="-x", title=None,
                axis=alt.Axis(labelOverlap=False, labelLimit=220, labelFontSize=12)),
        x=alt.X("pct:Q", title="Win the tournament (%)"))
    cbars = cbase.mark_bar(cornerRadiusEnd=3).encode(
        color=alt.Color("pct:Q", scale=GREEN_RED, legend=None),
        tooltip=[alt.Tooltip("Team:N"), alt.Tooltip("pct:Q", format=".1f")])
    ctext = cbase.mark_text(align="left", dx=3, color="#777", fontSize=11).encode(
        text=alt.Text("pct:Q", format=".1f"))
    st.altair_chart((cbars + ctext).properties(height=alt.Step(19)), width="stretch")
    if len(cdf) < len([r for r in crows if r["pct"] > 0]):
        st.caption("Teams below 0.05% omitted from the chart (see the full table below).")

    # full stage table
    with st.expander(f"📋 Full table — all {len(TEAMS)} teams, every round"):
        trows = []
        for t in sorted(TEAMS, key=lambda x: tprobs[x]["champion"], reverse=True):
            d = tprobs[t]
            trows.append({"Team": flags.label(t),
                          "Reach R32": d["r32"] * 100, "Reach R16": d["r16"] * 100,
                          "Reach QF": d["qf"] * 100, "Reach SF": d["sf"] * 100,
                          "Reach Final": d["final"] * 100, "Win 🏆": d["champion"] * 100})
        tdf = pd.DataFrame(trows)
        st.dataframe(
            tdf, width="stretch", hide_index=True,
            column_config={c: st.column_config.NumberColumn(c, format="%.1f%%")
                           for c in tdf.columns if c != "Team"})

# ---- Team ----
if nav == "🎯 Team":
    s = analysis.team_status(team, matches, meta)
    st.subheader(f"{flags.label(team)} — Group {s['group']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Current position", ORD[s["current_position"]])
    c2.metric("Points", s["current_points"])
    c3.metric("Games left", s["team_games_left"])

    qv = overview(path, mtime)["team"][team]
    if qv["qualified"]:
        if qv["via"] == "third":
            st.success("✅ **Guaranteed to qualify** — mathematically secured as one "
                       "of the 8 best third-placed teams.")
        elif qv["medal"] == "🥇":
            st.success("✅ **Guaranteed to qualify** — will win the group. 🥇")
        else:
            st.success("✅ **Guaranteed to qualify** — guaranteed a top-2 finish.")
    elif qv["eliminated"]:
        st.error("❌ **Eliminated** — cannot reach the Round of 32.")
    else:
        st.info(s["headline"])
    st.caption("Possible final group positions: "
               + ", ".join(ORD[p] for p in s["possible_positions"]))
    if (not qv["qualified"] and not qv["eliminated"]
            and s["level"] == "alive-third" and s.get("current_third_rank")):
        verdict = "would QUALIFY" if s["current_projection_qualified"] else "would be OUT"
        st.caption(f"On today's results it is the #{s['current_third_rank']} "
                   f"third-placed team → {verdict} (not yet mathematically decided).")

    rec_col, need_col = st.columns([3, 2])
    with rec_col:
        st.markdown("##### WC 2026 record")
        tms = sorted((m for m in matches if team in (m.home, m.away)),
                     key=lambda m: data.parse_dt(m.kickoff) or FAR)
        w = d = l = gf = ga = 0
        rows = []
        for m in tms:
            opp = m.away if m.home == team else m.home
            if m.played:
                tg = m.home_goals if m.home == team else m.away_goals
                og = m.away_goals if m.home == team else m.home_goals
                gf += tg; ga += og
                res = "✅ W" if tg > og else ("⚪ D" if tg == og else "🔴 L")
                w += tg > og; d += tg == og; l += tg < og
                rows.append({"Result": res, "Score": f"{tg}–{og}",
                             "Opponent": flags.label(opp), "When": fmt_short(m.kickoff)})
            else:
                rows.append({"Result": "🗓 upcoming", "Score": "–",
                             "Opponent": flags.label(opp), "When": fmt_short(m.kickoff)})
        played = w + d + l
        st.caption(f"Played {played} · **{w}W–{d}D–{l}L** · "
                   f"{gf} scored, {ga} conceded (GD {gf - ga:+d})")
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    with need_col:
        st.markdown("##### Need from next game")
        need = analysis.what_they_need(team, matches, meta)
        if need.get("no_more_games"):
            st.write("Group games finished — see the Odds tab for the third-place race.")
        else:
            st.write(f"**{flags.label(need['fixture'].split(' vs ')[0])} vs "
                     f"{flags.label(need['fixture'].split(' vs ')[1])}**")
            lab = {"W": "Win", "D": "Draw", "L": "Lose"}
            for res in ("W", "D", "L"):
                if res not in need["summary"]:
                    continue
                g = need["summary"][res]["guaranteed"]; b = need["summary"][res]["best"]
                gu = analysis._POS_MEANING[g]
                txt = (f"**{lab[res]}** → guaranteed to {gu}" if g == b
                       else f"**{lab[res]}** → at worst {gu}; at best {analysis._POS_MEANING[b]}")
                st.markdown("- " + txt)

    st.markdown("##### 🧭 Ways through (to a guaranteed top-2 spot)")
    for line in cached_ways(path, mtime, team)["lines"]:
        st.markdown("- " + line)

# ---- Head-to-head ----
if nav == "🆚 H2H":
    st.subheader("🆚 Head-to-head")
    ia = TEAMS.index(team)
    ca, cb = st.columns(2)
    a = ca.selectbox("Team A", TEAMS, format_func=flags.label, index=ia, key="h2h_a")
    b = cb.selectbox("Team B", TEAMS, format_func=flags.label,
                     index=(ia + 1) % len(TEAMS), key="h2h_b")
    if a == b:
        st.info("Pick two different teams.")
    else:
        probs = cached_mc(path, mtime, n_sims)
        ov = overview(path, mtime)
        short = {"clinched": "Through ✅", "eliminated": "Out ❌",
                 "alive": "Alive", "alive-third": "Alive (3rd best case)"}

        def h2h_col(t):
            w = d = l = gf = ga = 0
            for m in matches:
                if not m.played or t not in (m.home, m.away):
                    continue
                tg = m.home_goals if m.home == t else m.away_goals
                og = m.away_goals if m.home == t else m.home_goals
                gf += tg; ga += og; w += tg > og; d += tg == og; l += tg < og
            s = analysis.team_status(t, matches, meta)
            p, inf = probs[t], ov["team"][t]
            return {"Group": s["group"], "Position": ORD[s["current_position"]],
                    "Played": w + d + l, "W-D-L": f"{w}-{d}-{l}",
                    "GF-GA": f"{gf}-{ga}", "GD": f"{gf - ga:+d}",
                    "Pts": s["current_points"],
                    "Win group": pct(p["win_group"], inf["medal"] == "🥇"),
                    "Top 2": pct(p["top2"],
                                 inf["via"] == "top2" or inf["medal"] in ("🥇", "🥈")),
                    "Reach R32": pct(p["qualify"], inf["qualified"] or inf["eliminated"]),
                    "Status": short[s["level"]]}

        order = ["Group", "Position", "Played", "W-D-L", "GF-GA", "GD", "Pts",
                 "Win group", "Top 2", "Reach R32", "Status"]
        A, B = h2h_col(a), h2h_col(b)
        df = pd.DataFrame({"": order, flags.label(a): [str(A[k]) for k in order],
                           flags.label(b): [str(B[k]) for k in order]}).set_index("")
        st.dataframe(df, width="stretch")

        # group meeting (if any)
        if find_group(a, matches) == find_group(b, matches):
            fx = analysis._find_fixture(matches, a, b)
            if fx and fx[0].played:
                m, flip = fx
                ah = m.away_goals if flip else m.home_goals
                bh = m.home_goals if flip else m.away_goals
                st.caption(f"Group meeting: {flags.label(a)} {ah}–{bh} {flags.label(b)}")
            elif fx:
                st.caption(f"They still meet in Group {find_group(a, matches)} "
                           "(not played yet).")
        else:
            st.caption("Different groups — they could only meet in the knockout rounds.")

        # odds comparison chart
        mets = [("Win group", "win_group"), ("Top 2", "top2"), ("Reach R32", "qualify")]
        cdf = pd.DataFrame([{"Metric": lbl, "Team": flags.label(t),
                             "pct": probs[t][k] * 100}
                            for lbl, k in mets for t in (a, b)])
        chart = alt.Chart(cdf).mark_bar().encode(
            x=alt.X("Team:N", title=None, axis=alt.Axis(labels=False)),
            y=alt.Y("pct:Q", title="%", scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("Team:N", legend=alt.Legend(orient="top", title=None)),
            column=alt.Column("Metric:N", title=None, sort=[m[0] for m in mets]),
            tooltip=["Team", "Metric", alt.Tooltip("pct:Q", format=".1f")]
        ).properties(width=130, height=220)
        st.altair_chart(chart)

# ---- Scenario ----
if nav == "🔮 Scenario":
    st.subheader("🔮 Scenario builder")
    st.caption("Pick a matchup, set a hypothetical score, and add it. Stack as "
               "many as you like (you can even rewrite games already played), then "
               "see the projected effect.")
    scn = st.session_state.setdefault("scenario", [])

    pick1, pick2 = st.columns(2)
    a_team = pick1.selectbox("Team", TEAMS, format_func=flags.label,
                             index=TEAMS.index(team), key="scn_a")
    a_group = find_group(a_team, matches)
    opps = [t for t in teams_in_group(a_group, matches) if t != a_team]
    b_team = pick2.selectbox(f"Opponent — Group {a_group}", opps,
                             format_func=flags.label, key="scn_b")

    found = analysis._find_fixture(matches, a_team, b_team)
    if found and found[0].played:
        fm, flip = found
        ah = fm.away_goals if flip else fm.home_goals
        bh = fm.home_goals if flip else fm.away_goals
        st.caption(f"Actual result so far: {flags.label(a_team)} {ah}–{bh} "
                   f"{flags.label(b_team)} — adding a result here overrides it.")

    sc1, sc2, sc3 = st.columns([2, 2, 2])
    ag = sc1.number_input(f"{flags.label(a_team)} goals", 0, 20, 1, key="scn_ag")
    bg = sc2.number_input(f"{flags.label(b_team)} goals", 0, 20, 0, key="scn_bg")
    if sc3.button("➕ Add / update", width="stretch"):
        scn[:] = [r for r in scn if {r[0], r[3]} != {a_team, b_team}]
        scn.append((a_team, int(ag), int(bg), b_team))
        st.rerun()

    if not scn:
        st.info("No hypothetical results yet — add one above.")
    else:
        st.markdown("##### Hypothetical results")
        for idx, (h, hg, agl, aw) in enumerate(scn):
            row = st.columns([8, 1])
            row[0].write(f"{flags.label(h)}  **{hg}–{agl}**  {flags.label(aw)}")
            if row[1].button("✖", key=f"scn_del{idx}"):
                scn.pop(idx); st.rerun()
        if st.button("Clear all"):
            scn.clear(); st.rerun()

        new = analysis.apply_overrides(matches, scn)
        pj = project(new, meta)
        st.divider()
        ss = analysis.team_status(a_team, new, meta)
        verdict = "IN ✅" if a_team in pj.qualified() else "OUT ❌"
        m1, m2 = st.columns([3, 1])
        m1.info(f"**{flags.label(a_team)}** — {ss['headline']}")
        m2.metric("Projected", verdict)
        ov_new = build_overview(new, meta)
        gA = ss["group"]
        st.markdown(f"**Projected Group {gA}** — 🥇 winner · 🥈 runner-up · 🥉 third · "
                    "🟩 qualified · 🟥 eliminated")
        st.markdown(html_group(gA, new, meta, ov_new, selected=a_team),
                    unsafe_allow_html=True)
        with st.expander("Full projected qualifiers"):
            st.write("**Winners:** " + ", ".join(flags.label(t) for t in pj.winners))
            st.write("**Runners-up:** " + ", ".join(flags.label(t) for t in pj.runners_up))
            st.write("**Best thirds:** " + ", ".join(flags.label(t) for t in pj.qualified_thirds))

# ---- Odds ----
if nav == "📈 Odds":
    osig = betting_sig()
    odds_loaded = have_odds(osig)
    wlabel = st.radio(
        "Weighting model", ["FIFA ranking", "Betting odds"], horizontal=True,
        help="How team strength is set in the simulation. ‘Betting odds’ uses "
             "bookmakers' prices for each upcoming game (and tournament-winner odds "
             "where a game's price isn't available).")
    odds_weighting = "odds" if wlabel == "Betting odds" else "fifa"
    if odds_weighting == "odds" and not odds_loaded:
        st.warning("No betting odds loaded — showing FIFA-weighted odds. Add a key or "
                   "a `betting_odds.json` in the sidebar’s **Betting odds** panel.")
        odds_weighting = "fifa"
    probs = cached_mc(path, mtime, n_sims, odds_weighting, osig)
    ov = overview(path, mtime)
    info = ov["team"][team]
    st.caption(f"Model: **{'Betting odds' if odds_weighting == 'odds' else 'FIFA ranking'}** "
               "· exact 🔒 verdicts are unaffected by the weighting.")
    st.subheader(f"{flags.label(team)} — qualification odds")
    p = probs[team]
    c1, c2, c3 = st.columns(3)
    c1.metric("Win group", pct(p["win_group"], info["medal"] == "🥇"))
    c2.metric("Top 2", pct(p["top2"],
                          info["via"] == "top2" or info["medal"] in ("🥇", "🥈")))
    c3.metric("Reach R32", pct(p["qualify"], info["qualified"] or info["eliminated"]))
    st.caption("🔒 = mathematically decided (exact). Other %s are from simulation — "
               "“99%+” means near-certain but not yet proven.")

    st.subheader(f"Reach Round of 32 — all {len(TEAMS)} teams ({n_sims:,} sims)")
    rows = []
    for t in TEAMS:
        ti = ov["team"][t]
        cert = ti["qualified"] or ti["eliminated"]
        # locked teams own the exact endpoints (100 / 0); non-locked teams are clamped
        # strictly inside so a sim-100% ("99%+") team can never tie/outsort a 🔒 100%
        val = (100.0 if ti["qualified"]
               else 0.0 if ti["eliminated"]
               else min(99.9, max(0.1, probs[t]["qualify"] * 100)))
        rows.append({"Team": flags.label(t) + (" 🔒" if cert else ""),
                     "pct": val,
                     "label": pct(probs[t]["qualify"], cert)})
    ldf = pd.DataFrame(rows)
    base = alt.Chart(ldf).encode(
        y=alt.Y("Team:N", sort="-x", title=None,
                axis=alt.Axis(labelOverlap=False, labelLimit=220, labelFontSize=12)),
        x=alt.X("pct:Q", title="Reach Round of 32 (%)", scale=alt.Scale(domain=[0, 100])))
    bars = base.mark_bar(cornerRadiusEnd=3).encode(
        color=alt.Color("pct:Q", scale=GREEN_RED, legend=None),
        tooltip=[alt.Tooltip("Team:N"), alt.Tooltip("pct:Q", format=".1f")])
    text = base.mark_text(align="left", dx=3, color="#777", fontSize=11).encode(
        text="label:N")
    st.altair_chart((bars + text).properties(height=alt.Step(19)), width="stretch")

# ---- Importance ----
if nav == "⚖️ Importance":
    st.subheader("How much does a game matter?")
    rem = analysis.remaining(matches)
    if not rem:
        st.write("No games left to play.")
    else:
        own = [i for i, m in enumerate(rem) if team in (m.home, m.away)]
        labels = [f"{flags.label(m.home)} vs {flags.label(m.away)}" for m in rem]
        idx = st.selectbox("Game", range(len(rem)),
                           format_func=lambda i: labels[i],
                           index=own[0] if own else 0)
        for_team = st.selectbox("Whose fate?", TEAMS, format_func=flags.label,
                                index=TEAMS.index(team))
        iwlabel = st.radio("Weighting model", ["FIFA ranking", "Betting odds"],
                           horizontal=True, key="imp_weighting",
                           help="Strength model for the simulation.")
        odds_weighting = "odds" if iwlabel == "Betting odds" else "fifa"
        if odds_weighting == "odds" and not have_odds():
            odds_weighting = "fifa"
        m = rem[idx]
        res = cached_importance(path, mtime, for_team, m.home, m.away, n_sims,
                                odds_weighting, betting_sig())
        st.caption(f"Weighting: **{'Betting odds' if odds_weighting == 'odds' else 'FIFA ranking'}**"
                   " · exact 🔒 verdicts are unaffected.")
        order = list(res["by_result"])
        cert_for = (overview(path, mtime)["team"][for_team]["qualified"]
                    or overview(path, mtime)["team"][for_team]["eliminated"])
        dfi = pd.DataFrame([{"Result": k, "pct": res["by_result"][k] * 100,
                             "label": pct(res["by_result"][k], cert_for)}
                            for k in order])
        base = alt.Chart(dfi).encode(
            y=alt.Y("Result:N", sort=order, title=None,
                    axis=alt.Axis(labelLimit=240, labelFontSize=13)),
            x=alt.X("pct:Q", title="Reach Round of 32 (%)",
                    scale=alt.Scale(domain=[0, 100])))
        bars = base.mark_bar(cornerRadiusEnd=5, height=34).encode(
            color=alt.Color("pct:Q", scale=GREEN_RED, legend=None),
            tooltip=[alt.Tooltip("Result:N", title="If…"),
                     alt.Tooltip("pct:Q", format=".1f", title="Reach R32 %")])
        value_labels = base.mark_text(align="left", dx=6, fontSize=14,
                                      color="#888").encode(text="label:N")
        st.altair_chart((bars + value_labels).properties(height=170, width=440),
                        width="content")
        vals = list(res["by_result"].values())
        if max(vals) - min(vals) < 0.01:
            state = ("already through ✅" if vals[0] > 0.5
                     else "already eliminated ❌" if vals[0] < 0.01
                     else "unaffected")
            st.info(f"This game doesn't change **{flags.label(for_team)}**'s "
                    f"qualification — they're {state} regardless of the result.")
        st.metric(f"Swing in {flags.label(for_team)}'s qualification odds",
                  f"{res['swing']*100:.0f} pts")

# ---- Scorers ----
if nav == "⚽ Top Scorers":
    st.subheader("⚽ Top scorers")

    # Prefer the cached file (no API call on load); only fetch live the first time
    # there's no cache yet. Use the Fetch buttons to refresh it on demand.
    scorers = None
    if os.path.exists(SCORERS_CACHE):
        with open(SCORERS_CACHE) as fh:
            scorers = json.load(fh)
    elif token:
        try:
            scorers = cached_scorers(token, 100)
        except Exception as e:
            st.error(f"Couldn't load scorers: {e}")

    # total goals per country (from the standings — always available)
    gf = {}
    for g in all_groups(matches):
        for r in group_rows(g, matches, meta):
            gf[r.team] = r.gf
    cdf = pd.DataFrame([{"Team": ("⭐ " if t == team else "") + flags.label(t),
                         "⚽ Goals": v}
                        for t, v in sorted(gf.items(), key=lambda x: -x[1])])

    # --- side-by-side bar charts ---
    left, right = st.columns(2)
    with left:
        if not scorers:
            st.markdown("**🏃 Players**")
            st.info("Add your token in the sidebar to load player scorers."
                    if not PUBLISHED else "Player scorer data isn't available yet.")
        else:
            players_panel(scorers)
    with right:
        st.markdown("**🌍 By country** — total goals scored")
        with st.container(height=PANEL_H):
            b2 = alt.Chart(cdf).encode(
                y=alt.Y("Team:N", sort="-x", title=None,
                        axis=alt.Axis(labelOverlap=False)),
                x=alt.X("⚽ Goals:Q", title="Goals scored", axis=GOAL_AXIS))
            bars2 = b2.mark_bar(cornerRadiusEnd=3, color="#37a").encode(
                tooltip=["Team", "⚽ Goals"])
            text2 = b2.mark_text(align="left", dx=3, fontSize=11, color="#aaa").encode(
                text="⚽ Goals:Q")
            st.altair_chart((bars2 + text2).properties(height=alt.Step(20)),
                            width="stretch")

    # --- full tables, separate from the charts ---
    with st.expander("📋 Full tables"):
        tc = st.columns(2)
        with tc[0]:
            st.markdown("**Players**")
            if scorers:
                fdf = pd.DataFrame([{
                    "Player": s.get("player") or "",
                    "Team": flags.label(s.get("team")),
                    "⚽": s.get("goals", 0), "🅰": s.get("assists", 0),
                    "Pens": s.get("penalties", 0), "Apps": s.get("matches", 0),
                } for s in scorers])
                st.dataframe(fdf, width="stretch", hide_index=True)
            else:
                st.caption("No player data loaded.")
        with tc[1]:
            st.markdown("**By country**")
            st.dataframe(cdf, width="stretch", hide_index=True)

# ---- Rosters ----
_POS = {"GK": "🧤 Goalkeepers", "DEF": "🛡️ Defenders",
        "MID": "⚙️ Midfielders", "FWD": "🎯 Forwards"}
_POS_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}

if nav == "👕 Rosters":
    st.subheader("👕 Squads")

    squads = load_squads()
    if not squads:
        st.info("Squad lists aren't available right now." if PUBLISHED
                else "No squad file found. Run `python make_squads.py` to generate it.")
    else:
        names = sorted(squads)
        # Follow the sidebar team until the user picks a roster team manually:
        # re-sync only when the sidebar selection actually changes.
        if st.session_state.get("_roster_synced_to") != team:
            st.session_state["_roster_synced_to"] = team
            if team in squads:
                st.session_state["roster_team"] = team
        st.session_state.setdefault("roster_team",
                                    team if team in squads else names[0])
        rteam = st.selectbox("Team", names, format_func=flags.label,
                             key="roster_team")
        players = squads[rteam]
        st.markdown(f"#### {flags.label(rteam)} — {len(players)} players")

        cols = st.columns(4)
        for col, (pos, lbl) in zip(cols, _POS.items()):
            grp = sorted((p for p in players if p.get("position") == pos),
                         key=lambda x: (x.get("number") is None, x.get("number") or 0))
            with col:
                st.markdown(
                    f"<div style='font-weight:700;font-size:14px;text-transform:uppercase;"
                    f"letter-spacing:.07em;color:#4aa3c4;"
                    f"border-bottom:2px solid rgba(127,127,127,.30);"
                    f"padding-bottom:4px;margin-bottom:8px'>{lbl} · {len(grp)}</div>",
                    unsafe_allow_html=True)
                for p in grp:
                    no = p.get("number")
                    prefix = f"<b>{no}</b> - " if no else ""
                    st.markdown(
                        f"{prefix}{p.get('name')}<br>"
                        f"<span style='color:#888;font-size:11px'>"
                        f"{p.get('club') or ''} · {p.get('caps') or 0} caps · "
                        f"{p.get('goals') or 0}⚽</span>",
                        unsafe_allow_html=True)

        with st.expander("📋 Full squad table"):
            rdf = pd.DataFrame([{
                "#": p.get("number"),
                "Pos": p.get("position"),
                "Player": p.get("name") or "",
                "Club": p.get("club") or "",
                "Caps": p.get("caps") or 0,
                "⚽": p.get("goals") or 0,
            } for p in sorted(players, key=lambda x: (_POS_ORDER.get(x.get("position"), 9),
                                                      x.get("number") or 0))])
            st.dataframe(rdf, width="stretch", hide_index=True)

# ---- Schedule ----
if nav == "📅 Schedule":
    st.subheader("📅 Schedule & results")
    top = st.columns([1.3, 2])
    view = top[0].radio("View", ["List", "Calendar"], horizontal=True,
                        key="sched_view", label_visibility="collapsed")
    with top[1]:
        gsel = group_picker("Group", "sched_group")

    flt = st.columns([2, 1])
    tsel = flt[0].selectbox("Find a team", ["All teams"] + TEAMS,
                            format_func=lambda t: t if t == "All teams"
                            else flags.label(t), key="sched_team")
    only_upcoming = flt[1].checkbox("Upcoming only", key="sched_up")

    def _sched_match(m):
        if gsel != "All groups" and m.group != gsel:
            return False
        if tsel != "All teams" and tsel not in (m.home, m.away):
            return False
        if only_upcoming and m.played:
            return False
        return True

    fmatches = [m for m in matches if _sched_match(m)]

    if tsel != "All teams":
        st.markdown(f"#### {flags.label(tsel)} — {len(fmatches)} "
                    f"{'upcoming ' if only_upcoming else ''}match"
                    f"{'es' if len(fmatches) != 1 else ''}")

    tzlabel = datetime.now().astimezone().tzname() or "local"
    if view == "Calendar":
        st.markdown(calendar_html(fmatches, "All groups", selected=team),
                    unsafe_allow_html=True)
        st.caption(f"Dates in {tzlabel} (your local time) · ⭐ your team · "
                   "`v` upcoming · `•` live.")
    else:
        ms = sorted(fmatches, key=lambda m: data.parse_dt(m.kickoff) or FAR)
        st.caption(f"Kickoff times in {tzlabel} (your local time).")
        current_day, shown = None, 0
        for m in ms:
            dt = data.parse_dt(m.kickoff)
            if dt:
                dt = dt.astimezone()
            day = dt.strftime("%A, %b %-d") if dt else "Date TBD"
            if day != current_day:
                st.markdown(f"**{day}**")
                current_day = day
            time = dt.strftime("%H:%M") if dt else "--:--"
            status = (m.status or "").upper()
            if m.played:
                mid = f"**{m.home_goals}–{m.away_goals}**"
            elif status in ("IN_PLAY", "PAUSED", "LIVE"):
                mid = "🔴 **LIVE**"
            else:
                mid = "vs"
            hs = ("⭐" if m.home == team else "") + flags.label(m.home)
            aw = flags.label(m.away) + ("⭐" if m.away == team else "")
            st.markdown(
                f"<span style='color:#888'>{time} · Grp {m.group}</span> &nbsp; "
                f"{hs} &nbsp;{mid}&nbsp; {aw}", unsafe_allow_html=True)
            shown += 1
        if not shown:
            st.info("No matches to show for this filter.")

# ---- FIFA ranking ----
if nav == "🌍 FIFA Rank":
    st.subheader("🌍 FIFA World Ranking")
    st.caption(f"Snapshot: {fifa.SNAPSHOT} — a fixed reference, not updated live. "
               "Used as the final group tiebreaker and to weight the simulations.")
    gsel = group_picker("Group", "fifa_group")
    teams = [t for t in TEAMS if gsel == "All groups" or find_group(t, matches) == gsel]
    rows = sorted(((fifa.rank(t), t) for t in teams),
                  key=lambda x: (x[0] is None, x[0] or 999))
    df = pd.DataFrame([{"FIFA Rank": (r if r else "—"),
                        "Team": ("⭐ " if t == team else "") + flags.label(t),
                        "Group": find_group(t, matches)} for r, t in rows])
    # size the table to its content so the page scrolls, not the widget
    st.dataframe(df, width=750, height=(len(df) + 1) * 35 + 8, hide_index=True)
