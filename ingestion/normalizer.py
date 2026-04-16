"""
APEX OMEGA — ingestion/normalizer.py
Normalise team names for cross-source matching.
"""
import re
import unicodedata

# Common replacements / abbreviations
_REPLACEMENTS = {
    "manchester united": "man utd",
    "manchester city": "man city",
    "atletico": "atletico",
    "atlético": "atletico",
    "internazionale": "inter milan",
    "inter milan": "inter",
    "paris saint-germain": "psg",
    "paris saint germain": "psg",
    "borussia dortmund": "dortmund",
    "borussia mönchengladbach": "gladbach",
    "bayer 04 leverkusen": "leverkusen",
    "bayer leverkusen": "leverkusen",
    "rb leipzig": "leipzig",
    "red bull leipzig": "leipzig",
    "as roma": "roma",
    "ss lazio": "lazio",
    "ac milan": "milan",
    "fc barcelona": "barcelona",
    "real madrid cf": "real madrid",
    "cf": "", "fc": "", "sc": "", "afc": "", "fk": "",
    "united": "utd",
}


def normalize_team(name: str) -> str:
    """Lower-case, strip accents, remove common suffixes for matching."""
    if not name:
        return ""

    # Unicode normalise
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = name.lower().strip()

    # Remove punctuation except spaces/dashes
    name = re.sub(r"[^\w\s-]", "", name)

    # Apply replacements
    for old, new in _REPLACEMENTS.items():
        name = name.replace(old, new)

    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    return name


def fuzzy_team_match(query: str, candidates: list[str], threshold: float = 0.6) -> tuple[str, float]:
    """Simple Jaccard similarity match."""
    nq = set(normalize_team(query).split())
    best_score = 0.0
    best_name  = ""

    for c in candidates:
        nc = set(normalize_team(c).split())
        if not nq or not nc:
            continue
        inter = len(nq & nc)
        union = len(nq | nc)
        score = inter / union if union > 0 else 0
        if score > best_score:
            best_score = score
            best_name  = c

    return best_name, best_score
