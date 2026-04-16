"""
APEX OMEGA — trust/trust_matrix.py
7-factor Trust Matrix: scores a fixture 0-100.
Below 50 → hard REJECT. Below 70 → THIN_DATA route.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from core.config import TRUST_MAX_DATA_AGE_MIN

log = logging.getLogger("apex.trust")


def compute_trust(
    fixture: dict,
    xg_home: dict,
    xg_away: dict,
    odds_data: dict,
    lineups_available: bool = False,
    form_home: list = None,
    form_away: list = None,
    h2h: list = None,
) -> dict:
    """
    Returns:
        trust_score (0-100), sub_scores dict, trust_label, trust_flags list
    """
    form_home = form_home or []
    form_away = form_away or []
    h2h = h2h or []

    sub = {}

    # ── 1. DATA COMPLETENESS (20 pts) ──────────────────────────────
    pts = 0
    sources_present = 0
    if xg_home.get("source") == "footystats":     sources_present += 2
    elif xg_home.get("source") == "goals_proxy":  sources_present += 1
    if xg_away.get("source") == "footystats":     sources_present += 2
    elif xg_away.get("source") == "goals_proxy":  sources_present += 1
    if form_home and len(form_home) >= 3:         sources_present += 1
    if form_away and len(form_away) >= 3:         sources_present += 1
    if h2h and len(h2h) >= 3:                    sources_present += 1

    pts = min(20, sources_present * 3)
    sub["data_completeness"] = pts

    # ── 2. LINEUP CERTAINTY (15 pts) ───────────────────────────────
    pts = 0
    if lineups_available:
        pts = 15
    elif _is_within_hours(fixture.get("date_str"), 4):
        pts = 5   # kickoff soon, lineups likely released
    sub["lineup_certainty"] = pts

    # ── 3. ODDS INTEGRITY (15 pts) ─────────────────────────────────
    pts = 0
    odds_1x2 = odds_data.get("odds_1x2", {}) or {}
    if odds_1x2.get("home") and odds_1x2.get("draw") and odds_1x2.get("away"):
        # Check margin
        margin = _book_margin(odds_1x2)
        if margin <= 0.05:   pts = 15   # sharp (Pinnacle ~2-3%)
        elif margin <= 0.08: pts = 10   # normal
        elif margin <= 0.12: pts = 7    # soft
        else:                pts = 3    # suspicious
    elif odds_1x2.get("home"):
        pts = 5  # partial odds
    sub["odds_integrity"] = pts

    # ── 4. RECENCY / FRESHNESS (15 pts) ────────────────────────────
    pts = 15
    data_age = odds_data.get("odds_age_sec", 9999) / 60  # → minutes
    if data_age > TRUST_MAX_DATA_AGE_MIN:
        penalty = min(10, int((data_age - TRUST_MAX_DATA_AGE_MIN) / 30) * 3)
        pts = max(0, 15 - penalty)
    sub["recency_freshness"] = pts

    # ── 5. SOURCE AGREEMENT (15 pts) ───────────────────────────────
    # Agreement between xG-based probability and odds-implied probability
    pts = 0
    if odds_1x2.get("home") and xg_home.get("xg_scored") is not None:
        hxg = xg_home.get("xg_scored", 1.0)
        axg = xg_away.get("xg_scored", 1.0)
        xg_ratio = hxg / (hxg + axg + 0.001)
        implied_home = 1 / odds_1x2["home"] if odds_1x2["home"] else 0.4
        gap = abs(xg_ratio - implied_home)
        if gap <= 0.05:   pts = 15
        elif gap <= 0.10: pts = 10
        elif gap <= 0.20: pts = 5
        else:             pts = 2
    else:
        pts = 5  # can't measure, partial credit
    sub["source_agreement"] = pts

    # ── 6. FORM QUALITY (10 pts) ───────────────────────────────────
    pts = 0
    if len(form_home) >= 5 and len(form_away) >= 5:  pts = 10
    elif len(form_home) >= 3 and len(form_away) >= 3: pts = 6
    elif form_home or form_away:                       pts = 3
    sub["form_quality"] = pts

    # ── 7. H2H RICHNESS (10 pts) ───────────────────────────────────
    pts = 0
    if len(h2h) >= 5:   pts = 10
    elif len(h2h) >= 3: pts = 6
    elif len(h2h) >= 1: pts = 3
    sub["h2h_richness"] = pts

    # ── TOTAL ──────────────────────────────────────────────────────
    total = sum(sub.values())
    total = min(100, total)

    # DCS (Data Confidence Score) as fraction — used by verdict engine
    dcs = _compute_dcs(xg_home, xg_away, form_home, form_away)

    label = "STRONG" if total >= 75 else "MODERATE" if total >= 55 else "WEAK"
    flags = _compute_flags(sub, odds_data, dcs)

    return {
        "trust_score": total,
        "sub_scores":  sub,
        "trust_label": label,
        "dcs":         dcs,
        "flags":       flags,
    }


def _compute_dcs(xg_home, xg_away, form_home, form_away) -> float:
    """DCS: Data Confidence Score [0..1.0] for the APEX model."""
    dcs = 0.0
    if xg_home.get("source") == "footystats": dcs += 0.30
    elif xg_home.get("source") == "goals_proxy": dcs += 0.10
    if xg_away.get("source") == "footystats": dcs += 0.30
    elif xg_away.get("source") == "goals_proxy": dcs += 0.10
    if len(form_home) >= 5: dcs += 0.20
    elif len(form_home) >= 3: dcs += 0.10
    if len(form_away) >= 5: dcs += 0.20
    elif len(form_away) >= 3: dcs += 0.10
    return round(min(1.0, dcs), 2)


def _book_margin(odds_1x2: dict) -> float:
    """Overround margin = sum(1/odd) - 1."""
    try:
        overround = sum(1.0 / odds_1x2[k] for k in ("home", "draw", "away") if odds_1x2.get(k))
        return round(overround - 1.0, 4)
    except (ZeroDivisionError, TypeError):
        return 0.1


def _is_within_hours(date_str: Optional[str], hours: int) -> bool:
    if not date_str:
        return False
    try:
        match_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = (match_dt - now).total_seconds() / 3600
        return 0 <= diff <= hours
    except Exception:
        return False


def _compute_flags(sub: dict, odds_data: dict, dcs: float) -> list:
    flags = []
    if dcs < 0.58:
        flags.append("DCS_FAIL: insufficient data for reliable prediction")
    if sub.get("odds_integrity", 0) < 5:
        flags.append("NO_ODDS: bookmaker odds unavailable")
    if sub.get("lineup_certainty", 0) == 0:
        flags.append("NO_LINEUPS: composition unknown")
    if sub.get("form_quality", 0) < 3:
        flags.append("WEAK_FORM: insufficient recent match data")
    if sub.get("source_agreement", 0) <= 2:
        flags.append("DIVERGENCE: model and market strongly disagree")
    return flags
