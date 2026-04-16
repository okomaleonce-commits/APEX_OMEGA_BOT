"""
APEX OMEGA — decisions/verdict_engine.py
Produces structured verdict for a fixture:
  - Trust gate
  - Ghost signal filter
  - Edge computation per market
  - Confidence score /50
  - Kelly sizing
  - Decision code
  - Full market table
"""
import logging
from typing import Optional
from core.config import (
    TRUST_REJECT_THRESHOLD, TRUST_THIN_DATA_MIN,
    CONFIDENCE_MIN_BET, CONFIDENCE_MIN_SIGNAL,
    ODD_MIN, ODD_MAX_BET, ODD_MAX_SIGNAL, ODD_MIN_DRAW, EDGE_MIN_DRAW,
    KELLY_FRACTION, MAX_STAKE_PCT, BANKROLL, SAFE_MODE_EDGE_BOOST,
    AGGRESSIVE_EDGE_DISCOUNT, STAKE_ELITE, STAKE_DOMESTIC, STAKE_STAR_BIAS,
    EDGE_ELITE_KO_MIN, EDGE_DOMESTIC_MIN, EDGE_STAR_BIAS_MIN,
    get_league_cfg
)
from models.dixon_coles import compute_edge, kelly_fraction, run_model
from storage.signals_repo import check_ghost_filter

log = logging.getLogger("apex.verdict")

TIER_EDGE_BONUS = {"P0": 0.015, "N1": 0.010, "N2": 0.005, "N3": 0.002}
TIER_CONF_BONUS = {"P0": 15, "N1": 10, "N2": 5, "N3": 2}


def build_verdict(
    fixture: dict,
    model_result: dict,
    trust_result: dict,
    odds_data: dict,
    xg_home: dict,
    xg_away: dict,
    form_home: list,
    form_away: list,
    h2h: list,
    mode: str = "safe",
    bankroll: float = BANKROLL,
) -> dict:
    """
    Full verdict pipeline. Returns a complete verdict dict ready for formatting.
    """
    league_cfg = get_league_cfg(fixture["league_id"])
    tier       = league_cfg["tier"]
    base_edge  = league_cfg["edge_min"]

    # Adjust edge threshold by mode
    if mode == "safe":
        base_edge += SAFE_MODE_EDGE_BOOST
    elif mode == "aggressive":
        base_edge = max(0.01, base_edge - AGGRESSIVE_EDGE_DISCOUNT)

    trust_score = trust_result["trust_score"]
    dcs         = trust_result["dcs"]

    # ── GATE 0: Trust ───────────────────────────────────────────────
    if trust_score < TRUST_REJECT_THRESHOLD:
        return _reject(fixture, trust_result, model_result,
                       f"TRUST_FAIL: score {trust_score} < {TRUST_REJECT_THRESHOLD}")

    # ── GATE 1: DCS ─────────────────────────────────────────────────
    if dcs < 0.58:
        return _reject(fixture, trust_result, model_result,
                       f"DCS_FAIL: {dcs:.2f} < 0.58")

    thin_data = trust_score < TRUST_THIN_DATA_MIN

    # ── GATE 2: THIN DATA route blocks bet ─────────────────────────
    if thin_data and tier not in ("P0", "N1"):
        return _reject(fixture, trust_result, model_result,
                       f"THIN_DATA: trust {trust_score} < 70 for {tier} league")

    probs     = model_result["prob_1x2"]
    odds_1x2  = odds_data.get("odds_1x2") or {}

    # ── COMPUTE ALL MARKETS ────────────────────────────────────────
    markets = _compute_all_markets(
        fixture, model_result, odds_data, probs, tier, base_edge, dcs, mode
    )

    # ── FILTER MARKETABLE SIGNALS ───────────────────────────────────
    valid_markets = [m for m in markets if m["signal"] != "NO_BET"]
    if not valid_markets:
        return _no_bet(fixture, trust_result, model_result, markets,
                       "No market meets edge threshold", mode)

    # ── GHOST FILTER ────────────────────────────────────────────────
    for m in valid_markets:
        ghost = check_ghost_filter(
            fixture["league_id"], fixture["team_home"],
            fixture["team_away"], m["market"], m["edge"]
        )
        m["ghost"] = ghost
        if ghost["blocked"]:
            m["signal"] = "NO_BET"
            m["reject_reason"] = ghost["reason"]

    # Re-filter after ghost
    final_markets = [m for m in valid_markets if m["signal"] != "NO_BET"]

    if not final_markets:
        return _no_bet(fixture, trust_result, model_result, markets,
                       "All signals blocked by Ghost Filter", mode)

    # ── BEST SIGNAL (primary verdict) ──────────────────────────────
    primary = max(final_markets, key=lambda m: m["confidence"])

    # ── KELLY STAKE ────────────────────────────────────────────────
    kelly_raw   = kelly_fraction(primary["model_prob"], primary.get("odds", 0) or 0)
    kelly_frac  = round(kelly_raw * KELLY_FRACTION, 4)
    stake_pct   = min(kelly_frac, MAX_STAKE_PCT)
    stake_units = round(bankroll * stake_pct, 2)

    # Route-based stake range
    route = _classify_route(fixture, probs, odds_1x2, tier)
    if route == "ELITE_KO":
        stake_pct = min(stake_pct, STAKE_ELITE[1])
    elif route == "STAR_BIAS":
        stake_pct = min(stake_pct, STAKE_STAR_BIAS[1])
    else:
        stake_pct = min(stake_pct, STAKE_DOMESTIC[1])

    stake_units = round(bankroll * stake_pct, 2)

    return {
        "status":         "SIGNAL",
        "fixture":        fixture,
        "league_cfg":     league_cfg,
        "trust":          trust_result,
        "model":          model_result,
        "primary":        primary,
        "all_markets":    markets,
        "valid_markets":  final_markets,
        "route":          route,
        "mode":           mode,
        "kelly_raw":      round(kelly_raw * 100, 2),
        "kelly_frac_pct": round(kelly_frac * 100, 2),
        "stake_pct":      round(stake_pct * 100, 2),
        "stake_units":    stake_units,
        "bankroll":       bankroll,
        "h2h":            h2h,
        "form_home":      form_home,
        "form_away":      form_away,
    }


def _compute_all_markets(
    fixture: dict,
    model: dict,
    odds_data: dict,
    probs_1x2: dict,
    tier: str,
    base_edge: float,
    dcs: float,
    mode: str,
) -> list:
    """Compute edge, confidence, signal for all markets."""
    markets = []
    odds_1x2 = odds_data.get("odds_1x2") or {}
    odds_ou25 = odds_data.get("odds_ou25") or {}
    odds_ou35 = odds_data.get("odds_ou35") or {}
    odds_btts = odds_data.get("odds_btts") or {}

    # ── 1X2 MARKETS ───────────────────────────────────────────────
    for outcome, prob_key, odds_key in [
        ("Home Win", "home", "home"),
        ("Draw",     "draw", "draw"),
        ("Away Win", "away", "away"),
    ]:
        p     = probs_1x2.get(prob_key, 0)
        odd   = odds_1x2.get(odds_key)
        edge  = compute_edge(p, odd)
        min_e = (base_edge + 0.08) if prob_key == "draw" else base_edge
        markets.append(_make_market(
            fixture, f"1X2 — {outcome}", prob_key, p, odd, edge,
            min_e, tier, dcs, "draw" if prob_key == "draw" else None
        ))

    # ── DOUBLE CHANCE ─────────────────────────────────────────────
    dc_probs = model["prob_dc"]
    for dc_key, label in [("1X", "1X (Home/Draw)"), ("X2", "X2 (Draw/Away)"), ("12", "12 (Home/Away)")]:
        p = dc_probs.get(dc_key, 0)
        if p >= 0.68:
            fair_odd = round(1 / p, 2) if p > 0 else 0
            markets.append(_make_market(
                fixture, f"Double Chance — {label}", dc_key, p, fair_odd,
                None, base_edge - 0.01, tier, dcs, "dc"
            ))

    # ── OVER/UNDER 2.5 ────────────────────────────────────────────
    ou25 = model["prob_ou25"]
    for side, odd_key in [("Over 2.5", "over"), ("Under 2.5", "under")]:
        p   = ou25.get(odd_key, 0)
        odd = odds_ou25.get(odd_key)
        edge = compute_edge(p, odd)
        markets.append(_make_market(
            fixture, f"Goals — {side}", odd_key, p, odd, edge,
            base_edge, tier, dcs, "ou"
        ))

    # ── OVER/UNDER 3.5 ────────────────────────────────────────────
    ou35 = model["prob_ou35"]
    for side, odd_key in [("Over 3.5", "over"), ("Under 3.5", "under")]:
        p   = ou35.get(odd_key, 0)
        odd = odds_ou35.get(odd_key)
        edge = compute_edge(p, odd)
        markets.append(_make_market(
            fixture, f"Goals — {side}", odd_key + "_35", p, odd, edge,
            base_edge + 0.01, tier, dcs, "ou35"
        ))

    # ── BTTS ──────────────────────────────────────────────────────
    btts = model["prob_btts"]
    for side, odd_key in [("BTTS Yes", "yes"), ("BTTS No", "no")]:
        p   = btts.get(odd_key, 0)
        odd = odds_btts.get(odd_key)
        edge = compute_edge(p, odd)
        markets.append(_make_market(
            fixture, f"BTTS — {side}", odd_key + "_btts", p, odd, edge,
            base_edge, tier, dcs, "btts"
        ))

    return markets


def _make_market(
    fixture: dict,
    label: str,
    outcome_key: str,
    model_prob: float,
    odd: Optional[float],
    edge: Optional[float],
    edge_min: float,
    tier: str,
    dcs: float,
    market_type: str,
) -> dict:
    """Build a single market entry with signal decision."""
    conf = _confidence_score(edge, tier, dcs, model_prob)
    signal = "NO_BET"
    reject_reason = []

    # Odd checks
    if odd and odd < ODD_MIN:
        reject_reason.append(f"odd {odd} < min {ODD_MIN}")
    elif odd and odd > ODD_MAX_BET and conf >= CONFIDENCE_MIN_BET:
        signal = "SIGNAL"  # signal only, no bet
    elif edge is None or edge < edge_min:
        reject_reason.append(f"edge {edge or 0:.3f} < min {edge_min:.3f}")
    elif conf < CONFIDENCE_MIN_BET:
        reject_reason.append(f"conf {conf} < {CONFIDENCE_MIN_BET}")
    elif market_type == "draw" and edge < EDGE_MIN_DRAW:
        reject_reason.append(f"draw edge {edge:.3f} < {EDGE_MIN_DRAW}")
    else:
        if odd and odd <= ODD_MAX_BET:
            signal = "BET"
        else:
            signal = "SIGNAL"

    return {
        "market":       label,
        "outcome_key":  outcome_key,
        "market_type":  market_type or "generic",
        "model_prob":   round(model_prob, 4),
        "implied_prob": round(1 / odd, 4) if odd and odd > 1 else None,
        "odds":         odd,
        "edge":         edge,
        "confidence":   conf,
        "signal":       signal,
        "reject_reason": "; ".join(reject_reason) if reject_reason else None,
        "ghost":        None,  # filled later
    }


def _confidence_score(edge: Optional[float], tier: str, dcs: float, prob: float) -> int:
    """APEX confidence score /50."""
    score = 0
    e = edge or 0
    if e >= 0.10:  score += 15
    elif e >= 0.07: score += 10
    elif e >= 0.04: score += 5

    score += TIER_CONF_BONUS.get(tier, 0)

    if dcs >= 0.80: score += 15
    elif dcs >= 0.60: score += 10
    elif dcs >= 0.40: score += 5

    if prob >= 0.65: score += 5
    elif prob >= 0.55: score += 2

    return min(50, score)


def _classify_route(fixture: dict, probs: dict, odds_1x2: dict, tier: str) -> str:
    """Classify match route for staking."""
    league_name = fixture.get("league_name", "").lower()
    is_ko = any(x in league_name for x in ["champions", "europa", "conference", "cup", "copa"])

    if tier == "P0" or is_ko:
        return "ELITE_KO"
    # Star bias: heavy favourite with public attention
    max_prob = max(probs.values())
    if max_prob > 0.70 and odds_1x2.get("home", 99) < 1.45:
        return "STAR_BIAS"
    return "DOMESTIC"


def _reject(fixture, trust_result, model_result, reason: str) -> dict:
    return {
        "status":    "REJECT",
        "fixture":   fixture,
        "trust":     trust_result,
        "model":     model_result,
        "reason":    reason,
        "all_markets": [],
        "valid_markets": [],
    }


def _no_bet(fixture, trust_result, model_result, markets, reason: str, mode: str) -> dict:
    return {
        "status":       "NO_BET",
        "fixture":      fixture,
        "trust":        trust_result,
        "model":        model_result,
        "all_markets":  markets,
        "valid_markets": [],
        "reason":       reason,
        "mode":         mode,
    }
