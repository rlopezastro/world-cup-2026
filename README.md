# World Cup 2026 — Scenario Tool

A small Python tool that answers, for any team in the group stage:

- **Are they through? Eliminated? Still alive?** (`status`)
- **What do they need from their next game?** (`needs`)
- **What if this exact result happens?** (`scenario`)
- **What are their qualification odds?** (`sim`)
- **How much does one game actually matter?** (`importance`)

It models the full **2026 format**: 12 groups of 4 → top 2 of every group + the
**8 best third-placed teams** advance to the Round of 32. It uses the **2026
tiebreaker rules**, which changed this tournament:

| Group ranking (when level on points) | Best-8 third-place ranking |
|---|---|
| 1. Head-to-head points | 1. Points |
| 2. Head-to-head goal difference | 2. Goal difference |
| 3. Head-to-head goals scored | 3. Goals scored |
| 4. Overall goal difference | 4. Fair-play / conduct |
| 5. Overall goals scored | 5. FIFA ranking |
| 6. Fair-play / conduct | |
| 7. FIFA ranking | |

(Head-to-head now outranks overall goal difference; drawing of lots is gone.)
Head-to-head is applied recursively per FIFA's reapplication rule.

## Quick start (offline sample data)

```bash
cd world-cup-2026
python3 make_sample.py                 # writes sample_data.json + meta.json
python3 -m wc2026 table                # all groups + the third-place race
python3 -m wc2026 status Croatia
python3 -m wc2026 needs Cameroon
python3 -m wc2026 scenario "Croatia 2-0 Cameroon" --team Croatia
python3 -m wc2026 sim --group A --n 4000
python3 -m wc2026 importance Croatia "Croatia vs Cameroon"
```

No dependencies — standard library only (Python 3.10+).

## Jupyter notebook

`WorldCup2026.ipynb` is an interactive front-end (standings, status, needs,
scenarios, odds, game-importance, a one-team `dashboard()`, and a point-and-click
GUI).

Open it in VS Code and select the **"Python (worldcup)"** kernel — a dedicated
conda env with pandas + matplotlib + ipywidgets for pretty tables, charts, and
the interactive panel. Run the **Setup** section once, then any section below it.
(It also runs in plain-text mode under any kernel that can import `wc2026`.)

**Section 9 is a GUI** (ipywidgets): pick a team from a dropdown, toggle between
Dashboard / Status / Needs / Odds / Importance, and drag a slider for the
simulation count — it updates live, no cell re-running.

To recreate the env if needed:

```bash
conda create -y -n worldcup python=3.12 pandas matplotlib ipywidgets ipykernel
conda run -n worldcup python -m ipykernel install --user --name worldcup \
    --display-name "Python (worldcup)"
```

Regenerate the notebook itself with `python3 build_notebook.py`.

## Streamlit web app

`app.py` is a browser app with the same engine: sidebar team picker + data
freshness + a "fetch live data" button, and tabs for **Standings**, **Team**
(status & what-they-need), **Scenario**, **Odds** (leaderboard + per-team), and
**Importance** (game-swing). Launch it from the `worldcup` env:

```bash
conda run -n worldcup streamlit run app.py
# then open the Local URL it prints (default http://localhost:8501)
```

(`streamlit` is in the `worldcup` env; `pip install streamlit` if you recreate
the env.)

## Live results

Free data comes from [football-data.org](https://www.football-data.org), whose
free tier includes the World Cup.

1. Get a free key: https://www.football-data.org/client/register
2. `export FOOTBALL_DATA_TOKEN=your_key`
3. `python3 -m wc2026 fetch`  → saves to `cache.json`, used automatically afterwards.

The free tier is rate-limited (10 req/min, slightly delayed scores), which is
plenty for this tool.

## Commands

| Command | What it tells you |
|---|---|
| `table [GROUP]` | Standings with correct tiebreakers; ✅ marks who's qualifying, plus the cross-group third-place table |
| `status TEAM` | Clinched group / clinched top-2 / eliminated / alive, computed by **exact enumeration** of remaining group results |
| `needs TEAM` | For the team's next game: what a win / draw / loss **guarantees** vs. leaves open |
| `scenario "A 2-1 B" [...] [--team T]` | Apply hypothetical result(s) and recompute who's in |
| `sim [--team T] [--group G] [--n N]` | Monte Carlo qualification probabilities |
| `importance TEAM "A vs B"` | Qualification-odds swing across that game's three outcomes — the "how big is this game" number |

## What's exact vs. estimated

- **Group placement** (win group / top 2 / out of the group) is computed
  *exactly* by enumerating remaining scorelines in that group.
- **Third-place qualification** depends on all 12 groups, so its odds come from
  **Monte Carlo simulation** (`sim` / `importance`). Scores are simulated with a
  Poisson model lightly biased by FIFA ranking (in `meta.json`).

## Files

- `wc2026/data.py` — fetch / cache / load + normalize
- `wc2026/tiebreakers.py` — standings, 2026 tiebreakers, tournament projection
- `wc2026/analysis.py` — status, needs, scenarios, Monte Carlo, game importance
- `wc2026/cli.py` — command-line interface
- `meta.json` — optional FIFA rankings & conduct scores for deep tiebreakers
