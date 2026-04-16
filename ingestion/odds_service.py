"""
APEX OMEGA — ingestion/odds_service.py
Fetch odds from The Odds API (Bet365 + Pinnacle).
Supports: h2h (1X2), totals (Over/Under), btts, asian_handicap.
"""
import requests
import logging
import time
from typing import Optional
from core.config import ODDS_API_KEY, ODDS_API_BASE, ODDS_BOOKMAKERS

log = logging.getLogger("apex.odds")

_cache: dict = {}
_CACHE_TTL = 300

MARKET_MAP = {
    "h2h":             "1X2",
    "totals":          "Over/Under",
    "btts":            "BTTS",
    "asian_handicap":  "Asian Handicap",
    "draw_no_bet":     "Draw No Bet",
}

SPORT_KEY = "soccer"  # used for all leagues in Odds API


def _cached(key, ttl=_CACHE_TTL):
    if key in _cache:
        v, ts = _cache[key]
        if time.time() - ts < ttl:
            return v
    return None


def _store(key, val):
    _cache[key] = (val, time.time())
    return val


def get_odds_for_event(
    sport_key: str,
    event_id: Optional[str] = None,
    team_home: Optional[str] = None,
    team_away: Optional[str] = None,
    markets: list = None
) -> dict:
    """
    Fetch odds for a specific event. Returns dict with all requested markets.
    Falls back to team name search if event_id is None.
    """
    if markets is None:
        markets = ["h2h", "totals", "btts"]

    result = {
        "odds_1x2":     None,
        "odds_ou25":    None,
        "odds_btts":    None,
        "odds_ou35":    None,
        "odds_ah":      None,
        "bookmaker":    None,
        "odds_age_sec": 9999,
    }

    if event_id:
        result.update(_fetch_event_odds(sport_key, event_id, markets))
    elif team_home and team_away:
        result.update(_search_team_odds(sport_key, team_home, team_away, markets))

    return result


def _fetch_event_odds(sport_key: str, event_id: str, markets: list) -> dict:
    ckey = f"odds_event_{event_id}_{'_'.join(markets)}"
    cached = _cached(ckey)
    if cached:
        return cached

    markets_str = ",".join(markets)
    bookmakers_str = ",".join(ODDS_BOOKMAKERS)

    try:
        resp = requests.get(
            f"{ODDS_API_BASE}/sports/{sport_key}/events/{event_id}/odds",
            params={
                "apiKey":     ODDS_API_KEY,
                "regions":    "eu",
                "markets":    markets_str,
                "bookmakers": bookmakers_str,
                "oddsFormat": "decimal",
            },
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            parsed = _parse_event(data)
            _store(ckey, parsed)
            return parsed
        log.warning(f"Odds API event {event_id}: HTTP {resp.status_code}")
    except Exception as e:
        log.error(f"Odds fetch error: {e}")
    return {}


def _search_team_odds(sport_key: str, team_home: str, team_away: str, markets: list) -> dict:
    """Get all upcoming events for the sport and find the matching fixture."""
    from ingestion.normalizer import normalize_team

    ckey = f"odds_search_{sport_key}_{'_'.join(markets)}"
    all_events = _cached(ckey, 600)

    if all_events is None:
        try:
            markets_str = ",".join(markets)
            bookmakers_str = ",".join(ODDS_BOOKMAKERS)
            resp = requests.get(
                f"{ODDS_API_BASE}/sports/{sport_key}/odds",
                params={
                    "apiKey":     ODDS_API_KEY,
                    "regions":    "eu",
                    "markets":    markets_str,
                    "bookmakers": bookmakers_str,
                    "oddsFormat": "decimal",
                },
                timeout=15
            )
            if resp.status_code == 200:
                all_events = resp.json()
                _store(ckey, all_events)
            else:
                log.warning(f"Odds search: HTTP {resp.status_code}")
                return {}
        except Exception as e:
            log.error(f"Odds search error: {e}")
            return {}

    # Find matching event
    nh = normalize_team(team_home)
    na = normalize_team(team_away)

    for event in (all_events or []):
        eh = normalize_team(event.get("home_team", ""))
        ea = normalize_team(event.get("away_team", ""))
        if (nh in eh or eh in nh) and (na in ea or ea in na):
            return _parse_event(event)

    log.debug(f"No odds match: {team_home} vs {team_away}")
    return {}


def _parse_event(event: dict) -> dict:
    """Extract best odds from all bookmakers, preferring Pinnacle > Bet365 > others."""
    result = {
        "odds_1x2":     None,
        "odds_ou25":    None,
        "odds_ou35":    None,
        "odds_btts":    None,
        "odds_ah":      None,
        "bookmaker":    None,
        "odds_age_sec": 9999,
    }

    bookmakers = event.get("bookmakers", [])
    if not bookmakers:
        return result

    # Priority: Pinnacle first, then Bet365, then any
    priority = ["Pinnacle", "Bet365"] + [b["title"] for b in bookmakers]
    seen = set()
    sorted_bm = []
    for p in priority:
        for bm in bookmakers:
            if bm["title"] == p and p not in seen:
                sorted_bm.append(bm)
                seen.add(p)

    for bm in sorted_bm:
        for market in bm.get("markets", []):
            key = market["key"]
            outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}

            if key == "h2h" and result["odds_1x2"] is None:
                home_team = event.get("home_team", "")
                away_team = event.get("away_team", "")
                result["odds_1x2"] = {
                    "home": outcomes.get(home_team),
                    "draw": outcomes.get("Draw"),
                    "away": outcomes.get(away_team),
                }
                result["bookmaker"] = bm["title"]

            elif key == "totals":
                # Over 2.5
                for o in market.get("outcomes", []):
                    if o["name"] == "Over" and abs(o.get("point", 0) - 2.5) < 0.01:
                        if result["odds_ou25"] is None:
                            result["odds_ou25"] = {
                                "over":  o["price"],
                                "under": None
                            }
                    if o["name"] == "Under" and abs(o.get("point", 0) - 2.5) < 0.01:
                        if result["odds_ou25"] and result["odds_ou25"]["under"] is None:
                            result["odds_ou25"]["under"] = o["price"]
                    # Over 3.5
                    if o["name"] == "Over" and abs(o.get("point", 0) - 3.5) < 0.01:
                        if result["odds_ou35"] is None:
                            result["odds_ou35"] = {"over": o["price"], "under": None}
                    if o["name"] == "Under" and abs(o.get("point", 0) - 3.5) < 0.01:
                        if result["odds_ou35"] and result["odds_ou35"]["under"] is None:
                            result["odds_ou35"]["under"] = o["price"]

            elif key == "btts" and result["odds_btts"] is None:
                result["odds_btts"] = {
                    "yes": outcomes.get("Yes"),
                    "no":  outcomes.get("No"),
                }

    return result


def get_sports_list() -> list:
    """List available soccer sports keys from Odds API."""
    try:
        resp = requests.get(
            f"{ODDS_API_BASE}/sports",
            params={"apiKey": ODDS_API_KEY},
            timeout=10
        )
        if resp.status_code == 200:
            return [s for s in resp.json() if "soccer" in s.get("key", "")]
    except Exception as e:
        log.error(f"Sports list error: {e}")
    return []
