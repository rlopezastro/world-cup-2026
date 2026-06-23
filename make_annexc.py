"""Parse FIFA's Annex-C round-of-32 third-place allocation table into a lookup.

The exact 495-combination table (which group's third-placed team faces which group
winner, depending on *which* eight groups send a third through) is published by FIFA
and transcribed on Wikipedia. We parse the raw wikitext once into a compact dict so
the knockout play-out can place the thirds exactly as the official draw would, instead
of any-legal-matching.

    python make_annexc.py        # downloads + writes wc2026/annexc.json

Source: en.wikipedia.org Template:2026 FIFA World Cup third-place table
"""

from __future__ import annotations

import json
import os
import re
import urllib.request

SRC = ("https://en.wikipedia.org/w/index.php?"
       "title=Template:2026_FIFA_World_Cup_third-place_table&action=raw")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wc2026", "annexc.json")

# The 8 group winners that face a third-placed team, in the table's column order.
COL_ORDER = ["A", "B", "D", "E", "G", "I", "K", "L"]

# Sanity check: each winner's slot only ever draws a third from these groups
# (mirrors knockout.BRACKET; a third can never come from the winner's own group).
ALLOWED = {
    "A": set("CEFHI"), "B": set("EFGIJ"), "D": set("BEFIJ"), "E": set("ABCDF"),
    "G": set("AEHIJ"), "I": set("CDFGH"), "K": set("DEIJL"), "L": set("EHIJK"),
}

ROW_RE = re.compile(r'!\s*scope="row"\s*\|\s*(\d+)(.*?)(?=!\s*scope="row"|\Z)',
                    re.DOTALL)


def main() -> None:
    print(f"Downloading Annex-C table from Wikipedia …")
    req = urllib.request.Request(SRC, headers={"User-Agent": "wc2026-tool/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")

    # keep only the table body (drop the legend/header preamble), preserving the
    # leading "!" of the first data row so the row regex can match it
    raw = raw[re.search(r'!\s*scope="row"', raw).start():]

    table: dict[str, str] = {}
    for m in ROW_RE.finditer(raw):
        num, body = m.group(1), m.group(2)
        groups = re.findall(r"'''([A-L])'''", body)        # qualifying groups (8)
        thirds = re.findall(r"\b3([A-L])\b", body)          # assignments (8)
        if len(groups) != 8 or len(thirds) != 8:
            raise SystemExit(f"row {num}: parsed {len(groups)} groups / "
                             f"{len(thirds)} thirds (expected 8/8)")

        # consistency: the set of assigned thirds == the set of qualifying groups
        if set(groups) != set(thirds):
            raise SystemExit(f"row {num}: qualifying {sorted(groups)} != "
                             f"assigned {sorted(thirds)}")

        # legality: each assignment respects that winner-slot's allowed groups
        for winner, third in zip(COL_ORDER, thirds):
            if third not in ALLOWED[winner]:
                raise SystemExit(f"row {num}: 1{winner} vs 3{third} is illegal")

        key = "".join(sorted(groups))           # e.g. "EFGHIJKL"
        value = "".join(thirds)                 # thirds in COL_ORDER, e.g. "EJIFHGLK"
        if key in table and table[key] != value:
            raise SystemExit(f"row {num}: duplicate key {key} with different value")
        table[key] = value

    if len(table) != 495:
        raise SystemExit(f"expected 495 combinations, parsed {len(table)}")

    out = {
        "source": SRC,
        "note": ("Annex-C round-of-32 third-place allocation. key = sorted letters of "
                 "the 8 groups whose third qualifies; value = third-place group letters "
                 "facing winners in COL_ORDER " + "".join(COL_ORDER) + "."),
        "col_order": COL_ORDER,
        "table": table,
    }
    with open(OUT, "w") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"Wrote {len(table)} combinations -> {OUT}")


if __name__ == "__main__":
    main()
