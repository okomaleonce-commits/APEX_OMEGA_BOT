"""
APEX OMEGA — core/database.py
SQLite initialisation for persistent storage (Render disk).
"""
import sqlite3
import os
import logging
from core.config import DB_PATH, DATA_DIR

log = logging.getLogger("apex.db")


def get_conn() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create all tables if they don't exist."""
    conn = get_conn()
    c = conn.cursor()

    # Ghost signals memory table
    c.execute("""
        CREATE TABLE IF NOT EXISTS ghost_signals (
            signal_hash     TEXT PRIMARY KEY,
            league_id       INTEGER,
            team_home       TEXT,
            team_away       TEXT,
            market_type     TEXT,
            edge_bucket     TEXT,
            wins            INTEGER DEFAULT 0,
            losses          INTEGER DEFAULT 0,
            pushes          INTEGER DEFAULT 0,
            reliability     REAL DEFAULT 0.5,
            last_updated    TEXT,
            description     TEXT
        )
    """)

    # Signal log — every emitted signal
    c.execute("""
        CREATE TABLE IF NOT EXISTS signal_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_hash     TEXT,
            fixture_id      INTEGER,
            league_id       INTEGER,
            team_home       TEXT,
            team_away       TEXT,
            match_date      TEXT,
            market_type     TEXT,
            pick            TEXT,
            odds            REAL,
            edge            REAL,
            confidence      INTEGER,
            trust_score     INTEGER,
            stake_pct       REAL,
            decision_code   TEXT,
            mode            TEXT,
            emitted_at      TEXT,
            result          TEXT DEFAULT 'PENDING',
            profit_loss     REAL DEFAULT 0.0
        )
    """)

    # Scan run log
    c.execute("""
        CREATE TABLE IF NOT EXISTS scan_runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at          TEXT,
            mode            TEXT,
            hours_ahead     INTEGER,
            matches_scanned INTEGER,
            signals_emitted INTEGER,
            rejects         INTEGER,
            duration_sec    REAL
        )
    """)

    # Calibration cache (pre-fitted DC params)
    c.execute("""
        CREATE TABLE IF NOT EXISTS calibration_cache (
            league_id       INTEGER PRIMARY KEY,
            rho             REAL,
            avg_home_goals  REAL,
            avg_away_goals  REAL,
            home_win_rate   REAL,
            sample_size     INTEGER,
            fitted_at       TEXT
        )
    """)

    conn.commit()
    conn.close()
    log.info(f"Database initialised at {DB_PATH}")
