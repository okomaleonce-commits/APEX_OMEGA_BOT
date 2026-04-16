"""
APEX OMEGA — storage/signals_repo.py
Ghost Signal memory: stores and retrieves signal reliability scores.
"""
import hashlib
import logging
import json
from datetime import datetime, timezone
from core.database import get_conn
from core.config import GHOST_MIN_RELIABILITY, GHOST_MIN_SAMPLES

log = logging.getLogger("apex.storage")


def make_signal_hash(league_id: int, team_home: str, team_away: str,
                      market_type: str, edge_bucket: str) -> str:
    """Unique hash per signal pattern."""
    key = f"{league_id}|{team_home.lower()}|{team_away.lower()}|{market_type}|{edge_bucket}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


def get_edge_bucket(edge: float) -> str:
    """Bucket edge into ranges for hashing."""
    if edge < 0.03:   return "0-3pct"
    elif edge < 0.05: return "3-5pct"
    elif edge < 0.08: return "5-8pct"
    elif edge < 0.12: return "8-12pct"
    else:             return "12pct+"


def check_ghost_filter(league_id: int, team_home: str, team_away: str,
                        market_type: str, edge: float) -> dict:
    """
    Check if a signal should be blocked by Ghost Filter.
    Returns: {blocked: bool, reason: str, reliability: float, samples: int}
    """
    bucket = get_edge_bucket(edge)
    sig_hash = make_signal_hash(league_id, team_home, team_away, market_type, bucket)

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM ghost_signals WHERE signal_hash = ?", (sig_hash,)
        ).fetchone()

        if row is None:
            return {"blocked": False, "reason": "new_pattern", "reliability": None, "samples": 0}

        samples = row["wins"] + row["losses"] + row["pushes"]
        reliability = row["reliability"]

        if samples < GHOST_MIN_SAMPLES:
            return {"blocked": False, "reason": "insufficient_samples",
                    "reliability": reliability, "samples": samples}

        if reliability < GHOST_MIN_RELIABILITY:
            return {
                "blocked": True,
                "reason":  f"Ghost Filter: reliability {reliability:.2f} < {GHOST_MIN_RELIABILITY} "
                           f"({row['losses']}L/{row['wins']}W in {samples} signals)",
                "reliability": reliability,
                "samples": samples
            }

        return {"blocked": False, "reason": "ok", "reliability": reliability, "samples": samples}
    finally:
        conn.close()


def log_signal(
    fixture: dict,
    market_type: str,
    pick: str,
    odds: float,
    edge: float,
    confidence: int,
    trust_score: int,
    stake_pct: float,
    decision_code: str,
    mode: str,
) -> str:
    """Store a new signal in signal_log. Returns signal_hash."""
    bucket    = get_edge_bucket(edge)
    sig_hash  = make_signal_hash(
        fixture["league_id"], fixture["team_home"],
        fixture["team_away"], market_type, bucket
    )

    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO ghost_signals
              (signal_hash, league_id, team_home, team_away, market_type, edge_bucket,
               wins, losses, pushes, reliability, last_updated, description)
            VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 0.5, ?, ?)
        """, (
            sig_hash, fixture["league_id"], fixture["team_home"],
            fixture["team_away"], market_type, bucket,
            datetime.now(timezone.utc).isoformat(),
            f"{fixture['team_home']} vs {fixture['team_away']} — {market_type}"
        ))

        conn.execute("""
            INSERT INTO signal_log
              (signal_hash, fixture_id, league_id, team_home, team_away,
               match_date, market_type, pick, odds, edge, confidence,
               trust_score, stake_pct, decision_code, mode, emitted_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            sig_hash, fixture.get("fixture_id", 0),
            fixture["league_id"], fixture["team_home"], fixture["team_away"],
            fixture.get("date_str", "")[:10], market_type, pick, odds, edge,
            confidence, trust_score, stake_pct, decision_code, mode,
            datetime.now(timezone.utc).isoformat()
        ))
        conn.commit()
    finally:
        conn.close()

    return sig_hash


def update_signal_result(sig_hash: str, result: str, profit_loss: float = 0.0) -> None:
    """Update signal outcome (WIN/LOSS/PUSH) and recalculate reliability."""
    conn = get_conn()
    try:
        # Update signal_log
        conn.execute("""
            UPDATE signal_log SET result=?, profit_loss=?
            WHERE signal_hash=? AND result='PENDING'
        """, (result, profit_loss, sig_hash))

        # Update ghost_signals
        if result == "WIN":
            conn.execute("UPDATE ghost_signals SET wins=wins+1 WHERE signal_hash=?", (sig_hash,))
        elif result == "LOSS":
            conn.execute("UPDATE ghost_signals SET losses=losses+1 WHERE signal_hash=?", (sig_hash,))
        elif result == "PUSH":
            conn.execute("UPDATE ghost_signals SET pushes=pushes+1 WHERE signal_hash=?", (sig_hash,))

        # Recalculate reliability (weighted recent)
        row = conn.execute(
            "SELECT wins, losses, pushes FROM ghost_signals WHERE signal_hash=?", (sig_hash,)
        ).fetchone()

        if row:
            total = row["wins"] + row["losses"] + row["pushes"]
            if total > 0:
                reliability = (row["wins"] + 0.5 * row["pushes"]) / total
                conn.execute(
                    "UPDATE ghost_signals SET reliability=?, last_updated=? WHERE signal_hash=?",
                    (round(reliability, 4), datetime.now(timezone.utc).isoformat(), sig_hash)
                )

        conn.commit()
    finally:
        conn.close()


def get_ghost_stats() -> dict:
    """Get overall ghost signal memory statistics."""
    conn = get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM ghost_signals").fetchone()[0]
        blocked = conn.execute(
            "SELECT COUNT(*) FROM ghost_signals WHERE reliability < ? AND wins+losses+pushes >= ?",
            (GHOST_MIN_RELIABILITY, GHOST_MIN_SAMPLES)
        ).fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM signal_log WHERE result='PENDING'"
        ).fetchone()[0]
        win_loss = conn.execute(
            "SELECT SUM(wins), SUM(losses), SUM(pushes) FROM ghost_signals"
        ).fetchone()
        total_pl = conn.execute("SELECT SUM(profit_loss) FROM signal_log").fetchone()[0]

        return {
            "patterns_learned": total,
            "blocked_patterns":  blocked,
            "pending_signals":   pending,
            "total_wins":        win_loss[0] or 0,
            "total_losses":      win_loss[1] or 0,
            "total_pushes":      win_loss[2] or 0,
            "total_pl":          round(total_pl or 0, 2),
        }
    finally:
        conn.close()


def get_recent_signals(limit: int = 10) -> list:
    """Return most recent emitted signals."""
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT team_home, team_away, match_date, market_type, pick,
                   odds, edge, confidence, decision_code, result, profit_loss
            FROM signal_log ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
