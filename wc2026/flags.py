"""Map national-team names (and nationalities) to flag emoji.

Used for display only. Keys are matched case-insensitively; a handful of common
aliases (FIFA vs. football-data.org vs. everyday spellings) are included.
"""

from __future__ import annotations

_FLAGS = {
    # 2026 field + common qualifiers
    "algeria": "🇩🇿",
    "argentina": "🇦🇷", "australia": "🇦🇺", "austria": "🇦🇹", "belgium": "🇧🇪",
    "bolivia": "🇧🇴", "bosnia-herzegovina": "🇧🇦", "brazil": "🇧🇷",
    "cameroon": "🇨🇲", "canada": "🇨🇦", "cape verde islands": "🇨🇻",
    "colombia": "🇨🇴", "congo dr": "🇨🇩", "costa rica": "🇨🇷", "croatia": "🇭🇷",
    "curaçao": "🇨🇼", "curacao": "🇨🇼", "czechia": "🇨🇿", "denmark": "🇩🇰",
    "ecuador": "🇪🇨", "egypt": "🇪🇬", "england": "🏴\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f",
    "france": "🇫🇷", "germany": "🇩🇪", "ghana": "🇬🇭", "greece": "🇬🇷",
    "haiti": "🇭🇹", "honduras": "🇭🇳", "iran": "🇮🇷", "iraq": "🇮🇶",
    "italy": "🇮🇹", "ivory coast": "🇨🇮", "jamaica": "🇯🇲", "japan": "🇯🇵",
    "jordan": "🇯🇴", "mexico": "🇲🇽", "morocco": "🇲🇦", "netherlands": "🇳🇱",
    "new zealand": "🇳🇿", "nigeria": "🇳🇬", "norway": "🇳🇴", "panama": "🇵🇦",
    "paraguay": "🇵🇾", "peru": "🇵🇪", "poland": "🇵🇱", "portugal": "🇵🇹",
    "qatar": "🇶🇦", "saudi arabia": "🇸🇦",
    "scotland": "🏴\U000e0067\U000e0062\U000e0073\U000e0063\U000e0074\U000e007f",
    "senegal": "🇸🇳", "serbia": "🇷🇸", "south africa": "🇿🇦",
    "south korea": "🇰🇷", "spain": "🇪🇸", "sweden": "🇸🇪", "switzerland": "🇨🇭",
    "tunisia": "🇹🇳", "turkey": "🇹🇷", "ukraine": "🇺🇦", "united states": "🇺🇸",
    "uruguay": "🇺🇾", "uzbekistan": "🇺🇿",
    "wales": "🏴\U000e0067\U000e0062\U000e0077\U000e006c\U000e0073\U000e007f",
}

# alternate spellings/nationalities -> canonical key above
_ALIASES = {
    "korea republic": "south korea", "republic of korea": "south korea",
    "korea, republic of": "south korea", "usa": "united states",
    "united states of america": "united states", "côte d'ivoire": "ivory coast",
    "cote d'ivoire": "ivory coast", "türkiye": "turkey", "turkiye": "turkey",
    "czech republic": "czechia", "cape verde": "cape verde islands",
    "cabo verde": "cape verde islands", "dr congo": "congo dr",
    "democratic republic of congo": "congo dr", "drc": "congo dr",
    "bosnia and herzegovina": "bosnia-herzegovina", "iran (islamic republic of)": "iran",
}


def flag(name: str | None) -> str:
    """Return the flag emoji for a team/nationality, or '' if unknown."""
    if not name:
        return ""
    key = name.strip().lower()
    key = _ALIASES.get(key, key)
    return _FLAGS.get(key, "")


def label(name: str | None) -> str:
    """'🇺🇸 United States' (falls back to just the name)."""
    f = flag(name)
    return f"{f} {name}" if f else (name or "")
