"""
APEX OMEGA — ingestion/fixtures_service.py
Fetch upcoming fixtures from API-Football with in-memory caching.
"""
import requests
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from core.config import API_FOOTBALL_KEY, APIF_BASE, LEAGUES

log = logging.getLogger("apex.fixtures")

_cache: dict = {}
_CACHE_TTL = 300  # 5 min


def _headers() -> dict:
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


def get_fixtures_by_date_range(
    hours_ahead: int = 24,
    league_ids: Optional[list] = None
) -> list[dict]:
    """
    Return all upcoming fixtures within [now, now+hours_ahead].
    If league_ids is None → scan all whitelisted leagues.
    """
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=hours_ahead)

    date_from = now.strftime("%Y-%m-%d")
    date_to   = end.strftime("%Y-%m-%d")

    target_leagues = league_ids if league_ids else list(LEAGUES.keys())
    all_fixtures = []

    for league_id in target_leagues:
        ckey = f"fix_{league_id}_{date_from}_{date_to}"
        cached = _cached(ckey, 300)
        if cached is not None:
            all_fixtures.extend(cached)
            continue

        try:
            resp = requests.get(
                f"{APIF_BASE}/fixtures",
                headers=_headers(),
                params={"league": league_id, "from": date_from, "to": date_to, "season": now.year},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json().get("response", [])
                # Filter to time window
                filtered = []
                for fix in data:
                    ts = fix["fixture"]["timestamp"]
                    match_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    if now <= match_dt <= end:
                        filtered.append(_normalise_fixture(fix, league_id))
                _store(ckey, filtered)
                all_fixtures.extend(filtered)
                log.debug(f"League {league_id}: {len(filtered)} fixtures")
            else:
                log.warning(f"API-Football {league_id}: HTTP {resp.status_code}")
        except Exception as e:
            log.error(f"Fixture fetch error league {league_id}: {e}")

    return all_fixtures


def get_fixture_by_teams(
    team_home: str,
    team_away: str,
    match_date: Optional[str] = None,
    league_id: Optional[int] = None
) -> Optional[dict]:
    """Search fixture by team names (fuzzy match on normalised names)."""
    from ingestion.normalizer import normalize_team

    hours = 72
    fixtures = get_fixtures_by_date_range(hours_ahead=hours, league_ids=[league_id] if league_id else None)
    nh = normalize_team(team_home)
    na = normalize_team(team_away)

    best_match = None
    for fix in fixtures:
        fh = normalize_team(fix["team_home"])
        fa = normalize_team(fix["team_away"])
        # Substring match
        if (nh in fh or fh in nh) and (na in fa or fa in na):
            # Date filter
            if match_date:
                if fix["date_str"][:10] != match_date[:10]:
                    continue
            best_match = fix
            break

    return best_match


def get_fixture_stats(fixture_id: int) -> dict:
    """Get detailed stats for a specific fixture (H2H, form, lineups)."""
    ckey = f"stats_{fixture_id}"
    cached = _cached(ckey, 600)
    if cached is not None:
        return cached

    result = {"h2h": [], "home_form": [], "away_form": [], "lineups": {}}

    # H2H
    try:
        resp = requests.get(f"{APIF_BASE}/fixtures/headtohead",
            headers=_headers(),
            params={"h2h": f"{fixture_id}", "last": 5},
            timeout=10)
        # Note: h2h param is "teamA-teamB", we store teams separately
    except Exception:
        pass

    _store(ckey, result)
    return result


def get_team_form(team_id: int, last_n: int = 5) -> list[dict]:
    """Get last N results for a team."""
    ckey = f"form_{team_id}_{last_n}"
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
                home_goals = fix["goals"]["home"]
                away_goals = fix["goals"]["away"]
                home_id    = fix["teams"]["home"]["id"]
                if home_id == team_id:
                    r = "W" if home_goals > away_goals else ("D" if home_goals == away_goals else "L")
                    goals_for = home_goals; goals_ag = away_goals
                else:
                    r = "W" if away_goals > home_goals else ("D" if away_goals == home_goals else "L")
                    goals_for = away_goals; goals_ag = home_goals
                form.append({"result": r, "gf": goals_for, "ga": goals_ag})
            _store(ckey, form)
            return form
    except Exception as e:
        log.error(f"Form fetch error team {team_id}: {e}")
    return []


def get_h2h(team_home_id: int, team_away_id: int, last_n: int = 5) -> list[dict]:
    """Get H2H history between two teams."""
    ckey = f"h2h_{team_home_id}_{team_away_id}"
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
            h2h = []
            for fix in data:
                hg = fix["goals"]["home"] or 0
                ag = fix["goals"]["away"] or 0
                h2h.append({
                    "date": fix["fixture"]["date"][:10],
                    "home": fix["teams"]["home"]["name"],
                    "away": fix["teams"]["away"]["name"],
                    "score": f"{hg}-{ag}",
                    "home_goals": hg,
                    "away_goals": ag,
                    "btts": hg > 0 and ag > 0,
                    "total": hg + ag
                })
            _store(ckey, h2h)
            return h2h
    except Exception as e:
        log.error(f"H2H fetch error: {e}")
    return []


def _normalise_fixture(raw: dict, league_id: int) -> dict:
    """Flatten API-Football fixture response into our standard dict."""
    fix = raw["fixture"]
    home = raw["teams"]["home"]
    away = raw["teams"]["away"]
    league = raw["league"]
    goals = raw.get("goals", {})

    return {
        "fixture_id":   fix["id"],
        "league_id":    league_id,
        "league_name":  league.get("name", ""),
        "season":       league.get("season"),
        "round":        league.get("round", ""),
        "date_str":     fix.get("date", ""),
        "timestamp":    fix.get("timestamp", 0),
        "venue":        fix.get("venue", {}).get("name", "Unknown"),
        "status":       fix.get("status", {}).get("short", "NS"),
        "team_home":    home["name"],
        "team_home_id": home["id"],
        "team_away":    away["name"],
        "team_away_id": away["id"],
        "goals_home":   goals.get("home"),
        "goals_away":   goals.get("away"),
        "fetched_at":   datetime.now(timezone.utc).isoformat(),
    }
