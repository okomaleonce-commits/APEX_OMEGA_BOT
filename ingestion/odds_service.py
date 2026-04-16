"""
APEX OMEGA — ingestion/odds_service.py
Intégration REST directe odds-api.io (v3).
Base URL : https://api.odds-api.io/v3/
Auth     : ?apiKey=KEY (query param)

Endpoints utilisés :
  GET /events?sport=football&status=upcoming   → liste des matchs
  GET /odds?eventId=X&bookmakers=Bet365,...    → cotes par match
  GET /sports                                  → healthcheck (pas d'auth)

Le MCP Server odds-api.io est un process Node.js pour Claude Desktop.
Il est impossible de l'embedder dans un bot Python sur Render.
On utilise l'API REST directement — identique en fonctionnalité.
"""
import requests
import logging
import time
from typing import Optional
from core.config import ODDS_API_KEY, ODDS_BOOKMAKERS

log = logging.getLogger("apex.odds")

# ── Correct base URL for odds-api.io ─────────────────────────────────
ODDSIO_BASE = "https://api.odds-api.io/v3"

# ── League slug map (odds-api.io slug format) ─────────────────────────
LEAGUE_SLUGS = {
    39:  "england-premier-league",
    140: "spain-la-liga",
    78:  "germany-bundesliga",
    135: "italy-serie-a",
    61:  "france-ligue-1",
    2:   "uefa-champions-league",
    3:   "uefa-europa-league",
    848: "uefa-conference-league",
    94:  "portugal-primeira-liga",
    88:  "netherlands-eredivisie",
    45:  "england-fa-cup",
    137: "italy-coppa-italia",
    144: "belgium-jupiler-pro-league",
    207: "turkey-super-lig",
    128: "argentina-liga-profesional",
    71:  "brazil-serie-b",
}

_cache: dict = {}
_CACHE_TTL   = 300  # 5 min


def _cached(key, ttl=_CACHE_TTL):
    if key in _cache:
        v, ts = _cache[key]
        if time.time() - ts < ttl:
            return v
    return None


def _store(key, val):
    _cache[key] = (val, time.time())
    return val


def _params(extra: dict = None) -> dict:
    """Build request params including apiKey."""
    p = {"apiKey": ODDS_API_KEY}
    if extra:
        p.update(extra)
    return p


def check_odds_api_status() -> dict:
    """
    Test connectivity to odds-api.io.
    /sports does NOT require auth — tests base URL.
    Then tests auth with /events.
    """
    if not ODDS_API_KEY:
        return {
            "ok": False,
            "error": "ODDS_API_KEY non definie dans les variables d'environnement Render",
            "hint": "Ajoute ODDS_API_KEY dans Dashboard → Environment sur Render.com"
        }

    # 1. Test base URL (no auth needed)
    try:
        resp = requests.get(f"{ODDSIO_BASE}/sports", timeout=8)
        if resp.status_code != 200:
            return {"ok": False, "error": f"Base URL inaccessible: HTTP {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "error": f"Connexion impossible: {e}"}

    # 2. Test auth
    try:
        resp = requests.get(
            f"{ODDSIO_BASE}/events",
            params={"apiKey": ODDS_API_KEY, "sport": "football", "limit": 1},
            timeout=8
        )
        if resp.status_code == 200:
            remaining = resp.headers.get("x-ratelimit-remaining", "?")
            used      = resp.headers.get("x-ratelimit-used", "?")
            return {
                "ok": True,
                "service": "odds-api.io",
                "requests_remaining": remaining,
                "requests_used": used,
                "bookmakers": ODDS_BOOKMAKERS,
                "key_preview": f"{ODDS_API_KEY[:6]}...{ODDS_API_KEY[-4:]}" if len(ODDS_API_KEY) > 10 else "?",
            }
        elif resp.status_code == 401:
            try: msg = resp.json().get("message","invalid key")
            except: msg = "invalid key"
            return {
                "ok": False,
                "http_status": 401,
                "error": msg,
                "hint": "Cle rejetee par odds-api.io — verifier ODDS_API_KEY dans Render env vars",
                "key_preview": f"{ODDS_API_KEY[:6]}...{ODDS_API_KEY[-4:]}" if len(ODDS_API_KEY) > 10 else "TOO_SHORT",
            }
        else:
            return {"ok": False, "http_status": resp.status_code, "error": resp.text[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_odds_for_event(
    sport_key: str = "football",
    event_id: Optional[str]  = None,
    team_home: Optional[str] = None,
    team_away: Optional[str] = None,
    markets: list            = None,
    league_id: Optional[int] = None,
) -> dict:
    """
    Fetch odds for a match from odds-api.io.
    Returns empty_odds() gracefully if API unavailable.
    """
    if not ODDS_API_KEY:
        log.debug("ODDS_API_KEY absent — mode model-only")
        return _empty_odds()

    # Search by event_id if known
    if event_id:
        return _fetch_by_event_id(str(event_id))

    # Search by team names
    if team_home and team_away:
        return _search_by_teams(team_home, team_away, league_id)

    return _empty_odds()


def get_events_upcoming(league_id: Optional[int] = None, limit: int = 50) -> list:
    """
    Fetch upcoming football events from odds-api.io.
    Optional league filter via league slug.
    """
    if not ODDS_API_KEY:
        return []

    ckey = f"events_{league_id}_{limit}"
    cached = _cached(ckey, 600)
    if cached is not None:
        return cached

    params = {"sport": "football", "status": "upcoming", "limit": limit}
    if league_id and league_id in LEAGUE_SLUGS:
        params["league"] = LEAGUE_SLUGS[league_id]

    try:
        resp = requests.get(f"{ODDSIO_BASE}/events", params=_params(params), timeout=12)
        if resp.status_code == 200:
            events = resp.json()
            _store(ckey, events)
            return events
        elif resp.status_code == 401:
            log.warning("odds-api.io 401 — verifier ODDS_API_KEY dans Render env vars")
        else:
            log.warning(f"odds-api.io events: HTTP {resp.status_code}")
    except Exception as e:
        log.error(f"odds-api.io events error: {e}")
    return []


def _fetch_by_event_id(event_id: str) -> dict:
    ckey = f"odds_eid_{event_id}"
    cached = _cached(ckey)
    if cached:
        return cached

    try:
        resp = requests.get(
            f"{ODDSIO_BASE}/odds",
            params=_params({
                "eventId":   event_id,
                "bookmakers": ",".join(ODDS_BOOKMAKERS),
            }),
            timeout=10
        )
        if resp.status_code == 200:
            parsed = _parse_odds_response(resp.json())
            _store(ckey, parsed)
            return parsed
        elif resp.status_code == 401:
            log.warning("odds-api.io 401 — ODDS_API_KEY invalide")
        else:
            log.warning(f"odds-api.io odds eventId={event_id}: HTTP {resp.status_code}")
    except Exception as e:
        log.error(f"odds-api.io fetch_by_id error: {e}")
    return _empty_odds()


def _search_by_teams(team_home: str, team_away: str, league_id: Optional[int]) -> dict:
    """Find event by team names then fetch odds."""
    from ingestion.normalizer import normalize_team

    # Get all upcoming events (cached 10 min)
    ckey = f"all_events_{league_id}"
    events = _cached(ckey, 600)
    if events is None:
        events = get_events_upcoming(league_id=league_id, limit=100)
        _store(ckey, events)

    nh = normalize_team(team_home)
    na = normalize_team(team_away)

    matched_id = None
    for ev in (events or []):
        eh = normalize_team(ev.get("home",""))
        ea = normalize_team(ev.get("away",""))
        if (nh in eh or eh in nh) and (na in ea or ea in na):
            matched_id = ev.get("id")
            break

    if not matched_id:
        log.debug(f"No odds-api.io match for: {team_home} vs {team_away}")
        return _empty_odds()

    return _fetch_by_event_id(str(matched_id))


def _parse_odds_response(data: dict) -> dict:
    """
    Parse odds-api.io /odds response into APEX standard format.
    
    Response structure:
    {
      "id": 123,
      "home": "Arsenal",
      "away": "Chelsea",
      "bookmakers": {
        "Bet365": [
          {"name": "ML", "odds": [{"home": "2.10", "draw": "3.40", "away": "3.20"}]},
          {"name": "BTTS", "odds": [{"yes": "1.75", "no": "2.05"}]},
          {"name": "Over/Under", "odds": [{"over": "1.85", "line": "2.5", "under": "1.95"}]}
        ]
      }
    }
    """
    result = _empty_odds()
    if not data or "bookmakers" not in data:
        return result

    bookmakers = data["bookmakers"]
    home_team  = data.get("home","")
    away_team  = data.get("away","")

    # Priority: Pinnacle > Bet365 > others
    priority  = ["Pinnacle","Bet365"] + list(bookmakers.keys())
    seen, ordered = set(), []
    for p in priority:
        if p in bookmakers and p not in seen:
            ordered.append(p)
            seen.add(p)

    for bm_name in ordered:
        markets_list = bookmakers[bm_name]
        for market in markets_list:
            name = market.get("name","").upper()
            odds_arr = market.get("odds", [{}])
            o = odds_arr[0] if odds_arr else {}

            # 1X2 / ML
            if name in ("ML","1X2","MATCH WINNER") and result["odds_1x2"] is None:
                h = _to_float(o.get("home") or o.get("1"))
                d = _to_float(o.get("draw") or o.get("x"))
                a = _to_float(o.get("away") or o.get("2"))
                if h and a:
                    result["odds_1x2"] = {"home": h, "draw": d, "away": a}
                    result["bookmaker"] = bm_name

            # Over/Under — supports multiple lines
            elif "OVER" in name or "UNDER" in name or "TOTAL" in name or name in ("O/U","OU"):
                line = _to_float(o.get("line","0"))
                ov   = _to_float(o.get("over"))
                un   = _to_float(o.get("under"))
                if line and ov and un:
                    if abs(line - 2.5) < 0.01 and result["odds_ou25"] is None:
                        result["odds_ou25"] = {"over": ov, "under": un}
                    elif abs(line - 3.5) < 0.01 and result["odds_ou35"] is None:
                        result["odds_ou35"] = {"over": ov, "under": un}

            # BTTS
            elif "BTTS" in name or "BOTH TEAMS" in name or "GG" in name:
                yes = _to_float(o.get("yes") or o.get("gg"))
                no  = _to_float(o.get("no")  or o.get("ng"))
                if yes and result["odds_btts"] is None:
                    result["odds_btts"] = {"yes": yes, "no": no}

    return result


def _to_float(v) -> Optional[float]:
    try:
        return round(float(v), 3) if v is not None else None
    except (ValueError, TypeError):
        return None


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
