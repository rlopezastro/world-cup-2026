"""Generate a realistic mid-tournament sample_data.json + meta.json so the tool
runs offline. Groups A-C have matchday 3 still to play (interesting clinch /
needs questions); groups D-L are complete (a full third-place table)."""

import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))

GROUPS = {
    "A": ["Mexico", "Croatia", "Cameroon", "Saudi Arabia"],
    "B": ["Canada", "Belgium", "Morocco", "Uzbekistan"],
    "C": ["USA", "Senegal", "Scotland", "Jordan"],
    "D": ["Argentina", "Norway", "Egypt", "Panama"],
    "E": ["France", "Japan", "Ivory Coast", "New Zealand"],
    "F": ["England", "Colombia", "Tunisia", "Curacao"],
    "G": ["Brazil", "Switzerland", "South Korea", "Haiti"],
    "H": ["Spain", "Uruguay", "Ghana", "Qatar"],
    "I": ["Portugal", "Mexico B", "Algeria", "Jordan B"],
    "J": ["Germany", "Ecuador", "Australia", "Cape Verde"],
    "K": ["Netherlands", "Paraguay", "Iran", "Honduras"],
    "L": ["Italy", "Austria", "Nigeria", "Bolivia"],
}

# rough FIFA-ranking-ish strength (lower = stronger); only used to bias scores
RANK = {}
for gi, (g, teams) in enumerate(GROUPS.items()):
    for ti, t in enumerate(teams):
        RANK[t] = 1 + gi * 4 + ti * 3   # seeds stronger than 4th teams

# round-robin order within a group (team indices)
SCHEDULE = [(0, 1), (2, 3), (0, 2), (1, 3), (0, 3), (1, 2)]  # md1, md1, md2, md2, md3, md3

rng = random.Random(2026)


def sample_goals(strong_gap):
    # strong_gap > 0 means home stronger
    lam_h = max(0.3, 1.35 + 0.012 * strong_gap)
    lam_a = max(0.3, 1.35 - 0.012 * strong_gap)
    def pois(lam):
        L, k, p = pow(2.718281828, -lam), 0, 1.0
        while True:
            k += 1
            p *= rng.random()
            if p <= L:
                return k - 1
    return pois(lam_h), pois(lam_a)


matches = []
for g, teams in GROUPS.items():
    incomplete = g in ("A", "B", "C")
    for idx, (i, j) in enumerate(SCHEDULE):
        h, a = teams[i], teams[j]
        is_md3 = idx >= 4
        if incomplete and is_md3:
            hg = ag = None
        else:
            gap = RANK[a] - RANK[h]
            hg, ag = sample_goals(gap)
        matches.append({"group": g, "home": h, "away": a,
                        "home_goals": hg, "away_goals": ag})

with open(os.path.join(HERE, "sample_data.json"), "w") as fh:
    json.dump({"matches": matches}, fh, indent=2)

with open(os.path.join(HERE, "meta.json"), "w") as fh:
    json.dump({"fifa_ranking": RANK, "conduct": {}}, fh, indent=2)

print(f"Wrote sample_data.json ({len(matches)} matches) and meta.json")
