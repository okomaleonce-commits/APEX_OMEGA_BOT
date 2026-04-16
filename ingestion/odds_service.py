"""
APEX OMEGA — ingestion/odds_service.py
Fetch odds from The Odds API (Bet365 + Pinnacle).
Gracefully degrades to model-only mode when key is missing/invalid.
"""
import requests
import logging
import time
from typing import Optional
from core.config import ODDS_API_KEY, ODDS_API_BASE, ODDS_BOOKMAKERS

log = logging.getLogger("apex.odds")

_cache: dict = {}
_CACHE_TTL   = 300
_API_STATUS  = {"ok": None, "error": None}   # cached connectivity status


def _cached(key, ttl=_CACHE_TTL):
    if key in _cache:
        v, ts = _cache[key]
        if time.time() - ts < ttl:
            return v
    return None


def _store(key, val):
    _cache[key] = (val, time.time())
    return val


def check_odds_api_status() -> dict:
    """Ping Odds API /sports and return connectivity status."""
    if not ODDS_API_KEY:
        return {"ok": False, "error": "ODDS_API_KEY not set in environment variables"}
    try:
        resp = requests.get(
            f"{ODDS_API_BASE}/sports",
            params={"apiKey": ODDS_API_KEY},
            timeout=8
        )
        if resp.status_code == 200:
            sports = resp.json()
            soccer = [s for s in sports if "soccer" in s.get("key","")]
            remaining = resp.headers.get("x-requests-remaining", "?")
            used      = resp.headers.get("x-requests-used", "?")
            return {
                "ok": True,
                "soccer_markets": len(soccer),
                "requests_remaining": remaining,
                "requests_used": used,
                "bookmakers": ODDS_BOOKMAKERS,
            }
        else:
            try:
                body = resp.json()
                msg  = body.get("message", str(body))
            except Exception:
                msg = resp.text[:200]
            hint = ""
            if resp.status_code == 401:
                hint = "Cle invalide ou expiree. Verifier ODDS_API_KEY sur the-odds-api.com"
            elif resp.status_code == 429:
                hint = "Quota mensuel epuise. Verifier votre plan sur the-odds-api.com"
            return {
                "ok": False,
                "http_status": resp.status_code,
                "error": msg,
                "hint": hint,
                "key_preview": f"{ODDS_API_KEY[:6]}...{ODDS_API_KEY[-4:]}" if len(ODDS_API_KEY) > 10 else "TOO_SHORT",
            }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_odds_for_event(
    sport_key: str,
    event_id: Optional[str]   = None,
    team_home: Optional[str]  = None,
    team_away: Optional[str]  = None,
    markets: list             = None,
) -> dict:
    """
    Fetch odds for a specific event.
    Returns empty odds dict (not an error) if API unavailable —
    pipeline continues in model-only mode.
    """
    empty = _empty_odds()

    if not ODDS_API_KEY:
        log.debug("ODDS_API_KEY not set — model-only mode")
        return empty

    if markets is None:
        markets = ["h2h", "totals", "btts"]

    if team_home and team_away:
        return _search_team_odds(sport_key, team_home, team_away, markets)
    return empty


def _search_team_odds(sport_key: str, team_home: str, team_away: str, markets: list) -> dict:
    from ingestion.normalizer import normalize_team

    ckey       = f"odds_{sport_key}_{'_'.join(sorted(markets))}"
    all_events = _cached(ckey, 600)

    if all_events is None:
        try:
            resp = requests.get(
                f"{ODDS_API_BASE}/sports/{sport_key}/odds",
                params={
                    "apiKey":     ODDS_API_KEY,
                    "regions":    "eu",
                    "markets":    ",".join(markets),
                    "bookmakers": ",".join(ODDS_BOOKMAKERS),
                    "oddsFormat": "decimal",
                },
                timeout=15
            )
            if resp.status_code == 200:
                all_events = resp.json()
                _store(ckey, all_events)
                log.debug(f"Odds API: {len(all_events)} events fetched")
            elif resp.status_code == 401:
                try:
                    body = resp.json()
                    msg  = body.get("message","invalid key")
                except Exception:
                    msg = "invalid key"
                log.warning(f"Odds API 401: {msg} — check ODDS_API_KEY in Render env vars")
                return _empty_odds()
            elif resp.status_code == 422:
                # sport_key not found — try fallback
                log.debug(f"Odds API 422 for sport_key={sport_key} — trying soccer_epl fallback")
                return _empty_odds()
            else:
                log.warning(f"Odds search: HTTP {resp.status_code}")
                return _empty_odds()
        except Exception as e:
            log.error(f"Odds fetch error: {e}")
            return _empty_odds()

    # Find matching event
    nh = normalize_team(team_home)
    na = normalize_team(team_away)
    for event in (all_events or []):
        eh = normalize_team(event.get("home_team",""))
        ea = normalize_team(event.get("away_team",""))
        if (nh in eh or eh in nh) and (na in ea or ea in na):
            return _parse_event(event)

    log.debug(f"No odds match: {team_home} vs {team_away}")
    return _empty_odds()


def _parse_event(event: dict) -> dict:
    result = _empty_odds()
    bookmakers = event.get("bookmakers", [])
    if not bookmakers:
        return result

    # Priority: Pinnacle > Bet365 > others
    priority = ["Pinnacle", "Bet365"] + [b["title"] for b in bookmakers]
    seen, sorted_bm = set(), []
    for p in priority:
        for bm in bookmakers:
            if bm["title"] == p and p not in seen:
                sorted_bm.append(bm)
                seen.add(p)

    home_team = event.get("home_team","")
    away_team = event.get("away_team","")

    for bm in sorted_bm:
        for market in bm.get("markets",[]):
            key      = market["key"]
            outcomes = {o["name"]: o["price"] for o in market.get("outcomes",[])}

            if key == "h2h" and result["odds_1x2"] is None:
                result["odds_1x2"] = {
                    "home": outcomes.get(home_team),
                    "draw": outcomes.get("Draw"),
                    "away": outcomes.get(away_team),
                }
                result["bookmaker"] = bm["title"]

            elif key == "totals":
                for o in market.get("outcomes",[]):
                    pt = o.get("point", 0)
                    if abs(pt - 2.5) < 0.01:
                        if result["odds_ou25"] is None:
                            result["odds_ou25"] = {"over": None, "under": None}
                        if o["name"] == "Over":
                            result["odds_ou25"]["over"]  = o["price"]
                        else:
                            result["odds_ou25"]["under"] = o["price"]
                    elif abs(pt - 3.5) < 0.01:
                        if result["odds_ou35"] is None:
                            result["odds_ou35"] = {"over": None, "under": None}
                        if o["name"] == "Over":
                            result["odds_ou35"]["over"]  = o["price"]
                        else:
                            result["odds_ou35"]["under"] = o["price"]

            elif key == "btts" and result["odds_btts"] is None:
                result["odds_btts"] = {
                    "yes": outcomes.get("Yes"),
                    "no":  outcomes.get("No"),
                }

    return result


def _empty_odds() -> dict:
    return {
        "odds_1x2":     None,
        "odds_ou25":    None,
        "odds_ou35":    None,
        "odds_btts":    None,
        "odds_ah":      None,
        "bookmaker":    None,
        "odds_age_sec": 9999,
    }
