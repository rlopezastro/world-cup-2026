"""Build the bundled static roster file `squads.json`.

Rosters don't change once squads are submitted, so we keep them as a static file
(no API key, no runtime network call). This script downloads a public, open
FIFA World Cup 2026 squad dataset once (jersey numbers, positions, clubs, caps,
goals, captain) and maps the 3-letter team codes to the spellings the rest of the
app uses (the football-data.org feed).

    python make_squads.py

Source: https://github.com/26worldcup/26worldcup.github.io (MIT; data from Wikipedia)
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone

SRC = ("https://raw.githubusercontent.com/26worldcup/"
       "26worldcup.github.io/main/public/data/squads.json")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "squads.json")

# the source's GK/DF/MF/FW -> the app's GK/DEF/MID/FWD column keys
POS_MAP = {"GK": "GK", "DF": "DEF", "MF": "MID", "FW": "FWD"}

# 3-letter team code -> the exact name the app/feed (football-data.org) uses
CODE_MAP = {
    "ALG": "Algeria", "ARG": "Argentina", "AUS": "Australia", "AUT": "Austria",
    "BEL": "Belgium", "BIH": "Bosnia-Herzegovina", "BRA": "Brazil", "CAN": "Canada",
    "CIV": "Ivory Coast", "COD": "Congo DR", "COL": "Colombia",
    "CPV": "Cape Verde Islands", "CRO": "Croatia", "CUW": "Curaçao", "CZE": "Czechia",
    "ECU": "Ecuador", "EGY": "Egypt", "ENG": "England", "ESP": "Spain", "FRA": "France",
    "GER": "Germany", "GHA": "Ghana", "HAI": "Haiti", "IRN": "Iran", "IRQ": "Iraq",
    "JOR": "Jordan", "JPN": "Japan", "KOR": "South Korea", "KSA": "Saudi Arabia",
    "MAR": "Morocco", "MEX": "Mexico", "NED": "Netherlands", "NOR": "Norway",
    "NZL": "New Zealand", "PAN": "Panama", "PAR": "Paraguay", "POR": "Portugal",
    "QAT": "Qatar", "RSA": "South Africa", "SCO": "Scotland", "SEN": "Senegal",
    "SUI": "Switzerland", "SWE": "Sweden", "TUN": "Tunisia", "TUR": "Turkey",
    "URU": "Uruguay", "USA": "United States", "UZB": "Uzbekistan",
}


def main() -> None:
    print(f"Downloading squads from {SRC} …")
    with urllib.request.urlopen(SRC, timeout=60) as resp:
        raw = json.load(resp)

    unknown = sorted(set(raw) - set(CODE_MAP))
    if unknown:
        raise SystemExit(f"Unmapped team codes (add to CODE_MAP): {unknown}")

    teams: dict[str, list] = {}
    for code, entry in raw.items():
        name = CODE_MAP[code]
        players = []
        for p in entry.get("players", []):
            players.append({
                "number": p.get("no"),
                "name": p.get("name"),
                "position": POS_MAP.get(p.get("pos"), p.get("pos")),
                "club": p.get("club"),
                "caps": p.get("caps") or 0,
                "goals": p.get("goals") or 0,
                "dob": p.get("dob"),
            })
        players.sort(key=lambda x: (x["number"] is None, x["number"] or 0))
        teams[name] = players

    out = {
        "source": SRC,
        "license": "MIT (code) / data from Wikipedia",
        "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "teams": teams,
    }
    with open(OUT, "w") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    sizes = {len(v) for v in teams.values()}
    print(f"Wrote {len(teams)} squads ({sum(len(v) for v in teams.values())} players, "
          f"squad sizes {sorted(sizes)}) -> {OUT}")


if __name__ == "__main__":
    main()
