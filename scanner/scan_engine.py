"""
APEX OMEGA — scanner/scan_engine.py
Central orchestration engine.
Used by BOTH CLI and Telegram — single source of truth.

Optimisé pour API-Football free (100 req/jour):
  - Une seule passe de fixtures (pas une par league)
  - Form/H2H fetché seulement si team_ids valides
  - Fallback league_avg quand form indisponible
"""
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from core.config import get_league_cfg, BANKROLL
from core.database import get_conn
from ingestion.fixtures_service import (
    get_fixtures_by_date_range, get_fixture_by_teams,
    get_team_form, get_h2h
)
from ingestion.odds_service import get_odds_for_event
from ingestion.xg_service import (
    get_team_xg, compute_goals_proxy_xg, get_league_average_xg
)
from trust.trust_matrix import compute_trust
from models.dixon_coles import run_model
from decisions.verdict_engine import build_verdict

log = logging.getLogger("apex.scanner")


def run_scan(
    hours_ahead: int = 24,
    league_ids: list = None,
    mode: str = "safe",
    bankroll: float = BANKROLL,
) -> dict:
    """Full scan of upcoming fixtures."""
    t0 = time.time()
    log.info(f"Starting scan | hours_ahead={hours_ahead} | mode={mode}")

    fixtures = get_fixtures_by_date_range(hours_ahead=hours_ahead, league_ids=league_ids)
    log.info(f"Fetched {len(fixtures)} fixtures")

    results = {
        "scanned": 0, "signals": [], "no_bets": [],
        "rejects": [], "errors": [],
        "run_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode, "hours": hours_ahead,
    }

    for fix in fixtures:
        try:
            verdict = analyse_fixture(fix, mode=mode, bankroll=bankroll)
            results["scanned"] += 1
            if verdict["status"] == "SIGNAL":
                results["signals"].append(verdict)
            elif verdict["status"] == "NO_BET":
                results["no_bets"].append(verdict)
            else:
                results["rejects"].append(verdict)
        except Exception as e:
            log.error(f"Error: {fix.get('team_home','?')} vs {fix.get('team_away','?')}: {e}")
            results["errors"].append({
                "fixture": f"{fix.get('team_home','?')} vs {fix.get('team_away','?')}",
                "error": str(e)
            })

    elapsed = round(time.time() - t0, 2)
    results["duration_sec"] = elapsed
    _log_scan_run(results)
    log.info(f"Scan done: {results['scanned']} scanned | "
             f"{len(results['signals'])} signals | {elapsed}s")
    return results


def analyse_fixture(
    fixture: dict,
    mode: str = "safe",
    bankroll: float = BANKROLL,
) -> dict:
    """Analyse a single fixture — full pipeline with fallbacks."""
    league_id  = fixture["league_id"]
    league_cfg = get_league_cfg(league_id)
    season     = fixture.get("season") or datetime.now().year

    # ── 1. xG (FootyStats → league_avg) ──────────────────────────
    xg_home = get_team_xg(fixture["team_home"], league_cfg.get("fs_id"), season)
    xg_away = get_team_xg(fixture["team_away"], league_cfg.get("fs_id"), season)

    # ── 2. Form + H2H (only if valid team IDs available) ─────────
    home_id = fixture.get("team_home_id", 0)
    away_id = fixture.get("team_away_id", 0)

    form_home = get_team_form(home_id, last_n=5) if home_id else []
    form_away = get_team_form(away_id, last_n=5) if away_id else []
    h2h       = get_h2h(home_id, away_id, last_n=5) if (home_id and away_id) else []

    # ── 3. xG fallback cascade ───────────────────────────────────
    #   FootyStats > Goals Proxy > League Average
    if xg_home["source"] == "none":
        if form_home:
            xg_home = compute_goals_proxy_xg(form_home, league_cfg["home_adv"], is_home=True)
        else:
            xg_home = get_league_average_xg(league_id, is_home=True)
            log.debug(f"Using league_avg xG for {fixture['team_home']}")

    if xg_away["source"] == "none":
        if form_away:
            xg_away = compute_goals_proxy_xg(form_away, league_cfg["home_adv"], is_home=False)
        else:
            xg_away = get_league_average_xg(league_id, is_home=False)
            log.debug(f"Using league_avg xG for {fixture['team_away']}")

    # ── 4. Odds (odds-api.io, graceful 401) ──────────────────────
    odds_data = get_odds_for_event(
        sport_key="football",
        team_home=fixture["team_home"],
        team_away=fixture["team_away"],
        league_id=fixture.get("league_id"),
    )

    # ── 5. Trust Matrix ───────────────────────────────────────────
    trust_result = compute_trust(
        fixture, xg_home, xg_away, odds_data,
        lineups_available=False,
        form_home=form_home, form_away=form_away, h2h=h2h
    )

    # ── 6. Model ─────────────────────────────────────────────────
    hxg = _resolve_hxg(xg_home, league_cfg)
    axg = _resolve_axg(xg_away, league_cfg)
    model_result = run_model(hxg, axg, rho=league_cfg["rho"])

    # ── 7. Verdict ───────────────────────────────────────────────
    return build_verdict(
        fixture, model_result, trust_result, odds_data,
        xg_home, xg_away, form_home, form_away, h2h,
        mode=mode, bankroll=bankroll
    )


def analyse_by_teams(
    team_home: str,
    team_away: str,
    match_date: Optional[str] = None,
    league_id: Optional[int] = None,
    mode: str = "safe",
    bankroll: float = BANKROLL,
) -> dict:
    """Analyse a match given by team names."""
    fixture = get_fixture_by_teams(team_home, team_away, match_date, league_id)

    if not fixture:
        log.warning(f"No fixture found: {team_home} vs {team_away}")
        fixture = {
            "fixture_id":   0,
            "league_id":    league_id or 0,
            "league_name":  "Unknown League",
            "team_home":    team_home,
            "team_home_id": 0,
            "team_away":    team_away,
            "team_away_id": 0,
            "date_str":     match_date or datetime.now(timezone.utc).isoformat(),
            "timestamp":    0,
            "season":       datetime.now().year,
            "status":       "NS",
            "venue":        "Unknown",
        }

    return analyse_fixture(fixture, mode=mode, bankroll=bankroll)


def _resolve_hxg(xg: dict, cfg: dict) -> float:
    """Best available home attack xG."""
    if xg.get("xg_home_att"):    return xg["xg_home_att"]
    if xg.get("xg_scored"):      return xg["xg_scored"] * cfg.get("home_adv", 1.10)
    if xg.get("avg_goals_scored"): return xg["avg_goals_scored"] * cfg.get("home_adv", 1.10)
    return 1.25  # absolute fallback


def _resolve_axg(xg: dict, cfg: dict) -> float:
    """Best available away attack xG."""
    if xg.get("xg_away_att"):    return xg["xg_away_att"]
    if xg.get("xg_scored"):      return xg["xg_scored"] / cfg.get("home_adv", 1.10)
    if xg.get("avg_goals_scored"): return xg["avg_goals_scored"] / cfg.get("home_adv", 1.10)
    return 1.05  # absolute fallback


def _log_scan_run(results: dict) -> None:
    try:
        conn = get_conn()
        conn.execute("""
            INSERT INTO scan_runs
              (run_at, mode, hours_ahead, matches_scanned,
               signals_emitted, rejects, duration_sec)
            VALUES (?,?,?,?,?,?,?)
        """, (
            results["run_at"], results["mode"], results["hours"],
            results["scanned"], len(results["signals"]),
            len(results["rejects"]), results.get("duration_sec", 0)
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        log.error(f"Failed to log scan run: {e}")
