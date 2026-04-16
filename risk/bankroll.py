"""
APEX OMEGA — risk/bankroll.py
Bankroll and exposure management.
"""
from core.config import DB_PATH, BANKROLL
from core.database import get_conn
from datetime import datetime, timezone
import logging

log = logging.getLogger("apex.risk")


def get_current_bankroll() -> float:
    """Read current bankroll from DB, fallback to config."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT profit_loss FROM signal_log WHERE result != 'PENDING'"
        ).fetchall()
        total_pl = sum(r["profit_loss"] for r in row)
        return round(BANKROLL + total_pl, 2)
    except Exception:
        return BANKROLL
    finally:
        conn.close()


def get_daily_exposure() -> float:
    """Total stake % already committed today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT stake_pct FROM signal_log WHERE emitted_at LIKE ? AND result='PENDING'",
            (f"{today}%",)
        ).fetchall()
        return sum(r["stake_pct"] for r in rows)
    except Exception:
        return 0.0
    finally:
        conn.close()


def check_exposure_limit(proposed_stake_pct: float, daily_limit: float = 0.12) -> dict:
    """
    Check if adding this stake would exceed daily exposure limit.
    Default: 12% bankroll max per day.
    """
    current = get_daily_exposure()
    if current + proposed_stake_pct > daily_limit:
        return {
            "allowed": False,
            "reason": f"Daily exposure {current*100:.1f}% + {proposed_stake_pct*100:.1f}% > limit {daily_limit*100:.0f}%",
            "current_exposure": current,
        }
    return {"allowed": True, "current_exposure": current}
