"""
APEX OMEGA — ingestion/fixtures_service.py
Fetch fixtures from API-Football (api-sports.io or RapidAPI).
Supports both direct and RapidAPI header formats.
"""
import requests
import logging
import time
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from core.config import API_FOOTBALL_KEY, APIF_BASE, LEAGUES

log = logging.getLogger("apex.fixtures")

_cache: dict = {}
_CACHE_TTL = 300

# ── API-Football supports two access modes ───────────────────────────
# Mode A (direct): x-apisports-key
# Mode B (RapidAPI): x-rapidapi-key + x-rapidapi-host
RAPIDAPI_HOST = os.getenv("RAPIDAPI_HOST", "v3.football.api-sports.io")
USE_RAPIDAPI   = os.getenv("USE_RAPIDAPI", "false").lower() == "true"


def _headers() -> dict:
    if not API_FOOTBALL_KEY:
        return {}
    if USE_RAPIDAPI:
        return {
            "x-rapidapi-key":  API_FOOTBALL_KEY,
            "x-rapidapi-host": RAPIDAPI_HOST,
        }
    # Default: direct api-sports.io
    return {"x-apisports-key": API_FOOTBALL_KEY}


def _cached(key: str, ttl: int = _CACHE_TTL):
    if key in _cache:
        val, ts = _cache[key]
        if time.time() - ts < ttl:
            return val
    return None


def _store(key: str, val):
    _cache[key] = (val, time.time())
    return val


def check_api_status() -> dict:
    """
    Ping API-Football /status endpoint.
    Returns dict with account info or error details.
    Used by /diagnose command.
    """
    if not API_FOOTBALL_KEY:
        return {"ok": False, "error": "API_FOOTBALL_KEY is empty — set it in Render env vars"}
    try:
        resp = requests.get(
            f"{APIF_BASE}/status",
            headers=_headers(),
            timeout=10
        )
        body = resp.json() if resp.headers.get("content-type","").startswith("application/json") else {}
        if resp.status_code == 200:
            account = body.get("response", {}).get("account", {})
            sub     = body.get("response", {}).get("subscription", {})
            reqs    = body.get("response", {}).get("requests", {})
            return {
                "ok": True,
                "plan": sub.get("plan", "?"),
                "email": account.get("email", "?"),
                "requests_used": reqs.get("current", "?"),
                "requests_limit": reqs.get("limit_day", "?"),
                "header_mode": "rapidapi" if USE_RAPIDAPI else "direct",
            }
        else:
            err_msg = body.get("message") or body.get("errors") or f"HTTP {resp.status_code}"
            return {
                "ok": False,
                "http_status": resp.status_code,
                "error": str(err_msg),
                "header_mode": "rapidapi" if USE_RAPIDAPI else "direct",
                "key_preview": f"{API_FOOTBALL_KEY[:6]}...{API_FOOTBALL_KEY[-4:]}" if len(API_FOOTBALL_KEY) > 10 else "TOO_SHORT",
                "hint": _403_hint(resp.status_code, body),
            }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _403_hint(status: int, body: dict) -> str:
    if status == 403:
        return ("Key rejected. Causes: (1) key not set in Render env, "
                "(2) wrong header — try USE_RAPIDAPI=true if key is from RapidAPI, "
                "(3) free plan exceeded daily quota")
    if status == 401:
        return "Key invalid or expired"
    if status == 429:
        return "Rate limit reached — wait 1 min or upgrade plan"
    return ""


def get_fixtures_by_date_range(
    hours_ahead: int = 24,
    league_ids: Optional[list] = None
) -> list:
    now      = datetime.now(timezone.utc)
    end      = now + timedelta(hours=hours_ahead)
    date_from = now.strftime("%Y-%m-%d")
    date_to   = end.strftime("%Y-%m-%d")

    if not API_FOOTBALL_KEY:
        log.error("API_FOOTBALL_KEY not set — cannot fetch fixtures")
        return []

    target_leagues = league_ids if league_ids else list(LEAGUES.keys())
    all_fixtures   = []

    for league_id in target_leagues:
        ckey   = f"fix_{league_id}_{date_from}_{date_to}"
        cached = _cached(ckey)
        if cached is not None:
            all_fixtures.extend(cached)
            continue

        try:
            resp = requests.get(
                f"{APIF_BASE}/fixtures",
                headers=_headers(),
                params={
                    "league": league_id,
                    "from":   date_from,
                    "to":     date_to,
                    "season": now.year,
                },
                timeout=10
            )

            if resp.status_code == 200:
                data     = resp.json().get("response", [])
                filtered = []
                for fix in data:
                    ts       = fix["fixture"]["timestamp"]
                    match_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    if now <= match_dt <= end:
                        filtered.append(_normalise_fixture(fix, league_id))
                _store(ckey, filtered)
                all_fixtures.extend(filtered)
                log.debug(f"League {league_id}: {len(filtered)} fixtures")

            elif resp.status_code == 403:
                try:
                    body = resp.json()
                    msg  = body.get("message") or body.get("errors") or "no details"
                except Exception:
                    msg = resp.text[:200]
                log.warning(f"API-Football league {league_id}: 403 — {msg}")

            else:
                log.warning(f"API-Football league {league_id}: HTTP {resp.status_code}")

        except Exception as e:
            log.error(f"Fixture fetch error league {league_id}: {e}")

    return all_fixtures


def get_fixture_by_teams(
    team_home: str,
    team_away: str,
    match_date: Optional[str] = None,
    league_id: Optional[int]  = None,
) -> Optional[dict]:
    from ingestion.normalizer import normalize_team

    fixtures = get_fixtures_by_date_range(hours_ahead=72, league_ids=[league_id] if league_id else None)
    nh = normalize_team(team_home)
    na = normalize_team(team_away)

    for fix in fixtures:
        fh = normalize_team(fix["team_home"])
        fa = normalize_team(fix["team_away"])
        if (nh in fh or fh in nh) and (na in fa or fa in na):
            if match_date and fix["date_str"][:10] != match_date[:10]:
                continue
            return fix
    return None


def get_team_form(team_id: int, last_n: int = 5) -> list:
    if not team_id or not API_FOOTBALL_KEY:
        return []
    ckey   = f"form_{team_id}_{last_n}"
    cached = _cached(ckey, 600)
    if cached is not None:
        return cached
    try:
        resp = requests.get(
            f"{APIF_BASE}/fixtures",
            headers=_headers(),
            params={"team": team_id, "last": last_n, "status": "FT"},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json().get("response", [])
            form = []
            for fix in data:
                hg      = fix["goals"]["home"] or 0
                ag      = fix["goals"]["away"] or 0
                home_id = fix["teams"]["home"]["id"]
                if home_id == team_id:
                    r = "W" if hg > ag else ("D" if hg == ag else "L")
                    form.append({"result": r, "gf": hg, "ga": ag})
                else:
                    r = "W" if ag > hg else ("D" if ag == hg else "L")
                    form.append({"result": r, "gf": ag, "ga": hg})
            _store(ckey, form)
            return form
    except Exception as e:
        log.error(f"Form fetch error team {team_id}: {e}")
    return []


def get_h2h(team_home_id: int, team_away_id: int, last_n: int = 5) -> list:
    if not team_home_id or not team_away_id or not API_FOOTBALL_KEY:
        return []
    ckey   = f"h2h_{team_home_id}_{team_away_id}"
    cached = _cached(ckey, 3600)
    if cached is not None:
        return cached
    try:
        resp = requests.get(
            f"{APIF_BASE}/fixtures/headtohead",
            headers=_headers(),
            params={"h2h": f"{team_home_id}-{team_away_id}", "last": last_n},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json().get("response", [])
            h2h  = []
            for fix in data:
                hg = fix["goals"]["home"] or 0
                ag = fix["goals"]["away"] or 0
                h2h.append({
                    "date":       fix["fixture"]["date"][:10],
                    "home":       fix["teams"]["home"]["name"],
                    "away":       fix["teams"]["away"]["name"],
                    "score":      f"{hg}-{ag}",
                    "home_goals": hg,
                    "away_goals": ag,
                    "btts":       hg > 0 and ag > 0,
                    "total":      hg + ag,
                })
            _store(ckey, h2h)
            return h2h
    except Exception as e:
        log.error(f"H2H fetch error: {e}")
    return []


def _normalise_fixture(raw: dict, league_id: int) -> dict:
    fix    = raw["fixture"]
    home   = raw["teams"]["home"]
    away   = raw["teams"]["away"]
    league = raw["league"]
    goals  = raw.get("goals", {})
    return {
        "fixture_id":   fix["id"],
        "league_id":    league_id,
        "league_name":  league.get("name", ""),
        "season":       league.get("season"),
        "round":        league.get("round", ""),
        "date_str":     fix.get("date", ""),
        "timestamp":    fix.get("timestamp", 0),
        "venue":        (fix.get("venue") or {}).get("name", "Unknown"),
        "status":       (fix.get("status") or {}).get("short", "NS"),
        "team_home":    home["name"],
        "team_home_id": home["id"],
        "team_away":    away["name"],
        "team_away_id": away["id"],
        "goals_home":   goals.get("home"),
        "goals_away":   goals.get("away"),
        "fetched_at":   datetime.now(timezone.utc).isoformat(),
    }
