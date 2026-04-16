"""
APEX OMEGA — core/database.py
SQLite with safe path resolution:
  1. Try DB_PATH (/var/data/... on Render with persistent disk)
  2. Fallback to /tmp/apex_signals.db if disk not mounted
"""
import sqlite3
import os
import logging
from core.config import DB_PATH, DATA_DIR

log = logging.getLogger("apex.db")

# Resolved path (set once at import time)
_RESOLVED_PATH: str = ""


def _resolve_db_path() -> str:
    """Return the best writable DB path."""
    global _RESOLVED_PATH
    if _RESOLVED_PATH:
        return _RESOLVED_PATH

    candidates = [
        (DATA_DIR, DB_PATH),
        ("/tmp", "/tmp/apex_signals.db"),
        (".", "./apex_signals.db"),
    ]

    for data_dir, db_path in candidates:
        try:
            os.makedirs(data_dir, exist_ok=True)
            # Test write access
            test_file = os.path.join(data_dir, ".apex_write_test")
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
            _RESOLVED_PATH = db_path
            log.info(f"Database path resolved: {db_path}")
            return db_path
        except (OSError, PermissionError) as e:
            log.warning(f"Cannot use {db_path}: {e}")
            continue

    # Last resort
    _RESOLVED_PATH = "/tmp/apex_signals.db"
    log.warning("Falling back to /tmp/apex_signals.db")
    return _RESOLVED_PATH


def get_conn() -> sqlite3.Connection:
    path = _resolve_db_path()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Performance pragmas
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db() -> None:
    """Create all tables if they don't exist."""
    path = _resolve_db_path()
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS ghost_signals (
            signal_hash   TEXT PRIMARY KEY,
            league_id     INTEGER,
            team_home     TEXT,
            team_away     TEXT,
            market_type   TEXT,
            edge_bucket   TEXT,
            wins          INTEGER DEFAULT 0,
            losses        INTEGER DEFAULT 0,
            pushes        INTEGER DEFAULT 0,
            reliability   REAL    DEFAULT 0.5,
            last_updated  TEXT,
            description   TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS signal_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_hash   TEXT,
            fixture_id    INTEGER,
            league_id     INTEGER,
            team_home     TEXT,
            team_away     TEXT,
            match_date    TEXT,
            market_type   TEXT,
            pick          TEXT,
            odds          REAL,
            edge          REAL,
            confidence    INTEGER,
            trust_score   INTEGER,
            stake_pct     REAL,
            decision_code TEXT,
            mode          TEXT,
            emitted_at    TEXT,
            result        TEXT DEFAULT 'PENDING',
            profit_loss   REAL DEFAULT 0.0
        )
    """)

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

    c.execute("""
        CREATE TABLE IF NOT EXISTS calibration_cache (
            league_id      INTEGER PRIMARY KEY,
            rho            REAL,
            avg_home_goals REAL,
            avg_away_goals REAL,
            home_win_rate  REAL,
            sample_size    INTEGER,
            fitted_at      TEXT
        )
    """)

    conn.commit()
    conn.close()
    log.info(f"Database initialised at {path}")
