"""
APEX OMEGA — ingestion/xg_service.py
Fetch xG, BTTS potential, Over/Under potential from FootyStats API.
Falls back to goals-proxy calculation if FootyStats unavailable.
"""
import requests
import logging
import time
from typing import Optional
from core.config import FOOTYSTATS_KEY, FOOTYSTATS_BASE

log = logging.getLogger("apex.xg")

_cache: dict = {}
_CACHE_TTL = 3600  # 1 hour


def _cached(key, ttl=_CACHE_TTL):
    if key in _cache:
        v, ts = _cache[key]
        if time.time() - ts < ttl:
            return v
    return None


def _store(key, val):
    _cache[key] = (val, time.time())
    return val


def _headers() -> dict:
    return {}  # FootyStats uses key in params


def get_team_xg(team_name: str, league_fs_id: Optional[int], season: int = 2024) -> dict:
    """
    Fetch team attacking/defensive xG from FootyStats.
    Returns dict with xg_home_att, xg_away_def, btts_pct, over25_pct, etc.
    """
    result = _empty_xg()

    if not FOOTYSTATS_KEY or not league_fs_id:
        log.debug(f"FootyStats unavailable for {team_name} (no key or league ID)")
        return result

    ckey = f"xg_{league_fs_id}_{season}"
    league_data = _cached(ckey)

    if league_data is None:
        try:
            resp = requests.get(
                f"{FOOTYSTATS_BASE}/league-teams",
                params={"key": FOOTYSTATS_KEY, "league_id": league_fs_id, "season": season},
                timeout=12
            )
            if resp.status_code == 200:
                league_data = resp.json().get("data", [])
                _store(ckey, league_data)
            else:
                log.warning(f"FootyStats league {league_fs_id}: HTTP {resp.status_code}")
                return result
        except Exception as e:
            log.error(f"FootyStats error: {e}")
            return result

    # Find team in league data
    from ingestion.normalizer import normalize_team
    nt = normalize_team(team_name)

    team_data = None
    for t in (league_data or []):
        if normalize_team(t.get("cleanName", t.get("name", ""))) == nt:
            team_data = t
            break
        # Partial match
        n = normalize_team(t.get("cleanName", t.get("name", "")))
        if nt in n or n in nt:
            team_data = t

    if not team_data:
        log.debug(f"Team not found in FootyStats: {team_name}")
        return result

    stats = team_data.get("stats", {})

    # Parse xG
    result["xg_scored"]    = _safe_float(stats.get("xg_for_avg_overall"))
    result["xg_conceded"]  = _safe_float(stats.get("xg_against_avg_overall"))
    result["xg_home_att"]  = _safe_float(stats.get("xg_for_avg_home"))
    result["xg_away_att"]  = _safe_float(stats.get("xg_for_avg_away"))
    result["xg_home_def"]  = _safe_float(stats.get("xg_against_avg_home"))
    result["xg_away_def"]  = _safe_float(stats.get("xg_against_avg_away"))

    # BTTS / Over rates
    result["btts_pct"]     = _safe_pct(stats.get("btts_percentage"))
    result["over25_pct"]   = _safe_pct(stats.get("over25_percentage"))
    result["over35_pct"]   = _safe_pct(stats.get("over35_percentage"))
    result["under25_pct"]  = 100 - result["over25_pct"] if result["over25_pct"] else None

    # Goals
    result["avg_goals_scored"]   = _safe_float(stats.get("goals_scored_avg"))
    result["avg_goals_conceded"] = _safe_float(stats.get("goals_conceded_avg"))
    result["matches_played"]     = _safe_int(stats.get("matchesPlayed"))
    result["source"]             = "footystats"

    return result


def compute_goals_proxy_xg(
    form_results: list[dict],
    league_home_adv: float,
    is_home: bool
) -> dict:
    """
    Fallback: compute proxy xG from last N match results.
    form_results: list of {"gf": int, "ga": int, "result": str}
    """
    if not form_results:
        return _empty_xg()

    n = len(form_results)
    avg_scored   = sum(r.get("gf", 0) for r in form_results) / n
    avg_conceded = sum(r.get("ga", 0) for r in form_results) / n

    # Apply home advantage coefficient
    if is_home:
        avg_scored   = avg_scored   * league_home_adv
        avg_conceded = avg_conceded / league_home_adv

    # Estimate BTTS / Over25 from recent data
    btts_count  = sum(1 for r in form_results if r.get("gf", 0) > 0 and r.get("ga", 0) > 0)
    over25_count = sum(1 for r in form_results if (r.get("gf", 0) + r.get("ga", 0)) > 2)

    result = _empty_xg()
    result["xg_scored"]   = round(avg_scored, 3)
    result["xg_conceded"] = round(avg_conceded, 3)
    result["btts_pct"]    = round(btts_count / n * 100, 1)
    result["over25_pct"]  = round(over25_count / n * 100, 1)
    result["source"]      = "goals_proxy"
    return result


def _empty_xg() -> dict:
    return {
        "xg_scored": None, "xg_conceded": None,
        "xg_home_att": None, "xg_away_att": None,
        "xg_home_def": None, "xg_away_def": None,
        "btts_pct": None, "over25_pct": None,
        "over35_pct": None, "under25_pct": None,
        "avg_goals_scored": None, "avg_goals_conceded": None,
        "matches_played": 0, "source": "none"
    }


def _safe_float(v) -> Optional[float]:
    try:
        return round(float(v), 3) if v is not None else None
    except (ValueError, TypeError):
        return None


def _safe_pct(v) -> Optional[float]:
    try:
        f = float(v)
        return round(f if f <= 1.0 else f, 1) if v is not None else None
    except (ValueError, TypeError):
        return None


def _safe_int(v) -> int:
    try:
        return int(v) if v is not None else 0
    except (ValueError, TypeError):
        return 0
