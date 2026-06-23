"""Static FIFA Men's World Ranking snapshot for the 2026 finalists.

Looked up once and stored (the football-data.org API does not provide rankings).
Used for: the last-resort group tiebreaker, and to weight the Monte-Carlo
simulation by team strength. Keyed by the team names the data feed uses.
"""

SNAPSHOT = "June 2026"

RANKINGS = {
    "Argentina": 1, "France": 2, "Spain": 3, "England": 4, "Brazil": 5,
    "Morocco": 6, "Netherlands": 7, "Germany": 8, "Portugal": 9, "Belgium": 10,
    "Mexico": 11, "Colombia": 12, "United States": 13, "Croatia": 15, "Japan": 16,
    "Senegal": 17, "Uruguay": 18, "Switzerland": 19, "Austria": 21, "Iran": 22,
    "South Korea": 23, "Australia": 25, "Norway": 26, "Canada": 27, "Egypt": 28,
    "Algeria": 29, "Ecuador": 30, "Ivory Coast": 31, "Turkey": 32, "Sweden": 36,
    "Paraguay": 37, "Panama": 40, "Scotland": 41, "Congo DR": 43, "Czechia": 44,
    "Tunisia": 45, "Uzbekistan": 50, "Qatar": 56, "Iraq": 57, "South Africa": 60,
    "Saudi Arabia": 61, "Jordan": 63, "Bosnia-Herzegovina": 64,
    "Cape Verde Islands": 67, "Ghana": 73, "Curaçao": 82, "Haiti": 83,
    "New Zealand": 85,
}


def rank(name):
    """FIFA ranking position for a team, or None if unknown."""
    return RANKINGS.get(name)
