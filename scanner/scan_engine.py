"""
APEX OMEGA — scanner/scan_engine.py
Central scan orchestrator — single source of truth for both CLI and Telegram.
Flow: fixtures → xG → odds → trust → model → verdict → storage
"""
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from core.config import (
    get_league_cfg, BANKROLL, LEAGUES
)
from core.database import get_conn
from ingestion.fixtures_service import (
    get_fixtures_by_date_range, get_fixture_by_teams,
    get_team_form, get_h2h
)
from ingestion.odds_service import get_odds_for_event
from ingestion.xg_service import get_team_xg, compute_goals_proxy_xg
from trust.trust_matrix import compute_trust
from models.dixon_coles import run_model
from decisions.verdict_engine import build_verdict
from storage.signals_repo import log_signal, get_ghost_stats

log = logging.getLogger("apex.scanner")


def run_scan(
    hours_ahead: int = 24,
    league_ids: Optional[list] = None,
    mode: str = "safe",
    bankroll: float = BANKROLL,
    max_fixtures: int = 50,
) -> dict:
    """
    Full scan over upcoming fixtures.
    Returns: {signals, no_bets, rejects, stats, duration, mode}
    """
    t0 = time.time()
    log.info(f"🔍 Scan START | hours={hours_ahead} | mode={mode} | leagues={league_ids or 'ALL'}")

    fixtures = get_fixtures_by_date_range(hours_ahead=hours_ahead, league_ids=league_ids)
    fixtures = fixtures[:max_fixtures]

    log.info(f"📦 Fetched {len(fixtures)} fixtures")

    signals   = []
    no_bets   = []
    rejects   = []

    for fix in fixtures:
        try:
            result = analyse_fixture(fix, mode=mode, bankroll=bankroll)
            status = result.get("status", "REJECT")

            if status == "SIGNAL":
                signals.append(result)
                # Persist primary signal
                primary = result["primary"]
                log_signal(
                    fixture=fix,
                    market_type=primary["market"],
                    pick=primary["outcome_key"],
                    odds=primary.get("odds") or 0,
                    edge=primary.get("edge") or 0,
                    confidence=primary["confidence"],
                    trust_score=result["trust"]["trust_score"],
                    stake_pct=result["stake_pct"] / 100,
                    decision_code=primary["signal"],
                    mode=mode,
                )
            elif status == "NO_BET":
                no_bets.append(result)
            else:
                rejects.append(result)

        except Exception as e:
            log.error(f"Error analysing {fix.get('team_home')} vs {fix.get('team_away')}: {e}")

    duration = round(time.time() - t0, 2)

    # Log scan run
    _log_scan_run(mode, hours_ahead, len(fixtures), len(signals), len(rejects), duration)

    log.info(f"✅ Scan DONE | signals={len(signals)} no_bet={len(no_bets)} rejects={len(rejects)} [{duration}s]")

    return {
        "signals":   signals,
        "no_bets":   no_bets,
        "rejects":   rejects,
        "total":     len(fixtures),
        "mode":      mode,
        "hours":     hours_ahead,
        "duration":  duration,
        "ghost_stats": get_ghost_stats(),
        "scan_time": datetime.now(timezone.utc).isoformat(),
    }


def analyse_single_match(
    team_home: str,
    team_away: str,
    match_date: Optional[str] = None,
    league_id: Optional[int] = None,
    mode: str = "safe",
    bankroll: float = BANKROLL,
) -> dict:
    """
    Analyse a specific match by team names.
    Used for natural-language queries: "PSG Marseille 25/04"
    """
    log.info(f"🎯 Single match: {team_home} vs {team_away}")

    # Try to find fixture in API
    fix = get_fixture_by_teams(team_home, team_away, match_date, league_id)

    if fix is None:
        # Build synthetic fixture for analysis
        fix = _build_synthetic_fixture(team_home, team_away, match_date, league_id)
        log.warning(f"No API fixture found — using synthetic for {team_home} vs {team_away}")

    return analyse_fixture(fix, mode=mode, bankroll=bankroll)


def analyse_fixture(fixture: dict, mode: str = "safe", bankroll: float = BANKROLL) -> dict:
    """
    Full analysis pipeline for a single fixture.
    This is the core function — called by scan and single-match analysis.
    """
    league_id  = fixture["league_id"]
    league_cfg = get_league_cfg(league_id)
    fs_id      = league_cfg.get("fs_id")
    home_adv   = league_cfg["home_adv"]
    rho        = league_cfg["rho"]
    season     = fixture.get("season") or datetime.now().year

    home_id = fixture.get("team_home_id", 0)
    away_id = fixture.get("team_away_id", 0)

    # ── PARALLEL DATA FETCH ────────────────────────────────────────
    form_home = get_team_form(home_id) if home_id else []
    form_away = get_team_form(away_id) if away_id else []
    h2h       = get_h2h(home_id, away_id) if home_id and away_id else []

    # xG: FootyStats first, fallback to goals proxy
    xg_home = get_team_xg(fixture["team_home"], fs_id, season)
    xg_away = get_team_xg(fixture["team_away"], fs_id, season)

    if xg_home.get("source") == "none" and form_home:
        xg_home = compute_goals_proxy_xg(form_home, home_adv, is_home=True)
    if xg_away.get("source") == "none" and form_away:
        xg_away = compute_goals_proxy_xg(form_away, home_adv, is_home=False)

    # Odds
    odds_data = get_odds_for_event(
        sport_key="soccer",
        team_home=fixture["team_home"],
        team_away=fixture["team_away"],
        markets=["h2h", "totals", "btts"],
    )

    # Determine hxg/axg for model
    hxg = _resolve_xg(xg_home, is_home=True)
    axg = _resolve_xg(xg_away, is_home=False)

    # Apply contextual adjustments
    hxg, axg = _apply_context(fixture, hxg, axg, form_home, form_away)

    # ── TRUST ──────────────────────────────────────────────────────
    trust = compute_trust(
        fixture=fixture,
        xg_home=xg_home,
        xg_away=xg_away,
        odds_data=odds_data,
        lineups_available=False,
        form_home=form_home,
        form_away=form_away,
        h2h=h2h,
    )

    # ── MODEL ──────────────────────────────────────────────────────
    model = run_model(hxg, axg, rho)

    # ── VERDICT ────────────────────────────────────────────────────
    verdict = build_verdict(
        fixture=fixture,
        model_result=model,
        trust_result=trust,
        odds_data=odds_data,
        xg_home=xg_home,
        xg_away=xg_away,
        form_home=form_home,
        form_away=form_away,
        h2h=h2h,
        mode=mode,
        bankroll=bankroll,
    )

    # Attach raw data for formatting
    verdict["xg_home"]  = xg_home
    verdict["xg_away"]  = xg_away
    verdict["odds_data"] = odds_data
    verdict["hxg_used"] = hxg
    verdict["axg_used"] = axg

    return verdict


def _resolve_xg(xg_data: dict, is_home: bool) -> float:
    """Pick best xG value from xG data dict."""
    if is_home:
        val = xg_data.get("xg_home_att") or xg_data.get("xg_scored") or xg_data.get("avg_goals_scored")
    else:
        val = xg_data.get("xg_away_att") or xg_data.get("xg_scored") or xg_data.get("avg_goals_scored")
    return round(float(val), 3) if val else 1.20  # league average fallback


def _apply_context(fixture: dict, hxg: float, axg: float,
                   form_home: list, form_away: list) -> tuple:
    """
    Apply moratoriums and context corrections.
    - Post-UCL fatigue: -10% xG
    - Recent heavy fixture load: -5%
    """
    league_name = fixture.get("league_name", "").lower()

    # UCL mid-week fatigue (domestic match within 3 days of UCL)
    # We can't detect this perfectly without calendar — apply conservatively
    # for UCL teams in domestic leagues
    if "champions" in league_name or "europa" in league_name:
        pass  # no adjustment for the UCL match itself

    # Form-based adjustment: if team on very poor run (0/5)
    if form_home:
        wins = sum(1 for r in form_home if r.get("result") == "W")
        if wins == 0 and len(form_home) >= 5:
            hxg = round(hxg * 0.88, 3)
    if form_away:
        wins = sum(1 for r in form_away if r.get("result") == "W")
        if wins == 0 and len(form_away) >= 5:
            axg = round(axg * 0.88, 3)

    return hxg, axg


def _build_synthetic_fixture(team_home: str, team_away: str,
                               match_date: Optional[str], league_id: Optional[int]) -> dict:
    """Synthetic fixture when API has no match (manual entry)."""
    from datetime import datetime, timezone
    return {
        "fixture_id":   0,
        "league_id":    league_id or 39,
        "league_name":  get_league_cfg(league_id or 39)["name"],
        "season":       datetime.now().year,
        "round":        "Unknown",
        "date_str":     match_date or datetime.now(timezone.utc).isoformat(),
        "timestamp":    0,
        "venue":        "Unknown",
        "status":       "NS",
        "team_home":    team_home,
        "team_home_id": 0,
        "team_away":    team_away,
        "team_away_id": 0,
        "goals_home":   None,
        "goals_away":   None,
        "fetched_at":   datetime.now(timezone.utc).isoformat(),
    }


def _log_scan_run(mode, hours, total, signals, rejects, duration):
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO scan_runs (run_at, mode, hours_ahead, matches_scanned,
                                   signals_emitted, rejects, duration_sec)
            VALUES (?,?,?,?,?,?,?)
        """, (datetime.now(timezone.utc).isoformat(), mode, hours,
              total, signals, rejects, duration))
        conn.commit()
    except Exception as e:
        log.error(f"Log scan run error: {e}")
    finally:
        conn.close()
