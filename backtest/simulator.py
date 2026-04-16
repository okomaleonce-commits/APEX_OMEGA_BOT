"""
APEX OMEGA — backtest/simulator.py
Walk-forward backtest simulator.
Uses signal_log and outcomes_repo to measure historical performance.
"""
import logging
from core.database import get_conn

log = logging.getLogger("apex.backtest")


def run_backtest(league_id: int = None, market_type: str = None) -> dict:
    """
    Run a backtest over completed signals.
    Filters: league_id, market_type.
    Returns: {roi, win_rate, avg_odds, total_signals, ...}
    """
    conn = get_conn()
    try:
        query = "SELECT * FROM signal_log WHERE result != 'PENDING'"
        params = []
        if league_id:
            query += " AND league_id = ?"
            params.append(league_id)
        if market_type:
            query += " AND market_type LIKE ?"
            params.append(f"%{market_type}%")

        rows = [dict(r) for r in conn.execute(query, params).fetchall()]

        if not rows:
            return {"error": "No completed signals for backtest"}

        n = len(rows)
        wins   = sum(1 for r in rows if r["result"] == "WIN")
        losses = sum(1 for r in rows if r["result"] == "LOSS")
        pushes = sum(1 for r in rows if r["result"] == "PUSH")
        total_pl     = sum(r["profit_loss"] for r in rows)
        total_staked = sum(r["stake_pct"] for r in rows)
        avg_odds     = sum(r["odds"] for r in rows if r["odds"]) / n if n > 0 else 0

        win_rate = wins / n if n > 0 else 0
        roi      = total_pl / total_staked if total_staked > 0 else 0

        # By league breakdown
        by_league = {}
        for r in rows:
            lid = r["league_id"]
            if lid not in by_league:
                by_league[lid] = {"w": 0, "l": 0, "pl": 0}
            if r["result"] == "WIN":   by_league[lid]["w"] += 1
            elif r["result"] == "LOSS": by_league[lid]["l"] += 1
            by_league[lid]["pl"] += r["profit_loss"]

        return {
            "total_signals": n,
            "wins": wins, "losses": losses, "pushes": pushes,
            "win_rate": round(win_rate, 4),
            "roi": round(roi, 4),
            "total_pl": round(total_pl, 2),
            "avg_odds": round(avg_odds, 2),
            "by_league": by_league,
        }
    finally:
        conn.close()
