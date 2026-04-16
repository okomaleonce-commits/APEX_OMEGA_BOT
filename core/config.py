"""
APEX OMEGA — core/config.py
Central configuration: leagues, thresholds, API endpoints.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── API CREDENTIALS ──────────────────────────────────────────
API_FOOTBALL_KEY  = os.getenv("API_FOOTBALL_KEY", "")
FOOTYSTATS_KEY    = os.getenv("FOOTYSTATS_KEY", "")
ODDS_API_KEY      = os.getenv("ODDS_API_KEY", "")
ODDS_BOOKMAKERS   = os.getenv("ODDS_API_BOOKMAKERS", "Bet365,Pinnacle").split(",")

BOT_TOKEN         = os.getenv("BOT_TOKEN", "")
CHAT_ID           = os.getenv("CHAT_ID", "")

DB_PATH           = os.getenv("DB_PATH", "/var/data/apex_signals.db")
DATA_DIR          = os.getenv("DATA_DIR", "/var/data")
BANKROLL          = float(os.getenv("BANKROLL", "1000"))
DEFAULT_MODE      = os.getenv("DEFAULT_MODE", "safe")   # safe | aggressive
SCAN_HOURS_AHEAD  = int(os.getenv("SCAN_HOURS_AHEAD", "24"))

# ─── API ENDPOINTS ────────────────────────────────────────────
APIF_BASE         = "https://v3.football.api-sports.io"
FOOTYSTATS_BASE   = "https://api.football-data-api.com"
ODDS_API_BASE     = "https://api.the-odds-api.com/v4"

# ─── LEAGUE REGISTRY ─────────────────────────────────────────
# tier: P0=UEFA KO, N1=Top5, N2=Secondary, N3=Other
# rho:  Dixon-Coles low-score correction
# home_adv: multiplier applied to goals_proxy (not footystats)
# edge_min: minimum edge threshold for BET signal
# fs_id: FootyStats league ID (if mapped)
# sport: "soccer" for Odds API

LEAGUES = {
    # ── UEFA ──────────────────────────────────────────────────
    2:   {"name": "UEFA Champions League", "tier": "P0", "rho": -0.13, "home_adv": 1.08, "edge_min": 0.04, "fs_id": 2},
    3:   {"name": "UEFA Europa League",    "tier": "P0", "rho": -0.13, "home_adv": 1.08, "edge_min": 0.04, "fs_id": 3},
    848: {"name": "UEFA Conference League","tier": "P0", "rho": -0.13, "home_adv": 1.08, "edge_min": 0.04, "fs_id": 848},

    # ── TOP 5 ─────────────────────────────────────────────────
    39:  {"name": "English Premier League","tier": "N1", "rho": -0.13, "home_adv": 1.10, "edge_min": 0.04, "fs_id": 2012},
    140: {"name": "La Liga",               "tier": "N1", "rho": -0.13, "home_adv": 1.12, "edge_min": 0.04, "fs_id": 2014},
    78:  {"name": "Bundesliga",            "tier": "N1", "rho": -0.13, "home_adv": 1.11, "edge_min": 0.04, "fs_id": 2002},
    135: {"name": "Serie A",               "tier": "N1", "rho": -0.13, "home_adv": 1.13, "edge_min": 0.04, "fs_id": 2019},
    61:  {"name": "Ligue 1",               "tier": "N1", "rho": -0.13, "home_adv": 1.12, "edge_min": 0.04, "fs_id": 2015},

    # ── SECONDARY ─────────────────────────────────────────────
    94:  {"name": "Primeira Liga (POR)",   "tier": "N2", "rho": -0.14, "home_adv": 1.14, "edge_min": 0.03, "fs_id": None},
    88:  {"name": "Eredivisie (NED)",      "tier": "N2", "rho": -0.13, "home_adv": 1.11, "edge_min": 0.03, "fs_id": None},
    144: {"name": "Jupiler Pro League",    "tier": "N2", "rho": -0.13, "home_adv": 1.10, "edge_min": 0.03, "fs_id": None},
    169: {"name": "Eliteserien (NOR)",     "tier": "N2", "rho": -0.14, "home_adv": 1.10, "edge_min": 0.03, "fs_id": None},
    207: {"name": "Super Lig (TUR)",       "tier": "N2", "rho": -0.15, "home_adv": 1.15, "edge_min": 0.03, "fs_id": None},
    106: {"name": "Ekstraklasa (POL)",     "tier": "N2", "rho": -0.14, "home_adv": 1.12, "edge_min": 0.03, "fs_id": None},
    119: {"name": "Superliga (DEN)",       "tier": "N2", "rho": -0.13, "home_adv": 1.11, "edge_min": 0.03, "fs_id": None},
    71:  {"name": "Serie B (BRA)",         "tier": "N2", "rho": -0.16, "home_adv": 1.14, "edge_min": 0.03, "fs_id": None},
    128: {"name": "Liga Argentina",        "tier": "N2", "rho": -0.18, "home_adv": 1.13, "edge_min": 0.03, "fs_id": None},

    # ── AFRICA / CI ───────────────────────────────────────────
    233: {"name": "MTN Ligue 1 (CIV)",    "tier": "N3", "rho": -0.18, "home_adv": 1.16, "edge_min": 0.02, "fs_id": None},
    200: {"name": "Botola Pro (MAR)",      "tier": "N3", "rho": -0.19, "home_adv": 1.14, "edge_min": 0.02, "fs_id": None},
    202: {"name": "Premier League (GHA)", "tier": "N3", "rho": -0.18, "home_adv": 1.15, "edge_min": 0.02, "fs_id": None},
    197: {"name": "Premier League (NGA)", "tier": "N3", "rho": -0.17, "home_adv": 1.14, "edge_min": 0.02, "fs_id": None},

    # ── MAJOR CUPS ────────────────────────────────────────────
    45:  {"name": "FA Cup",                "tier": "N2", "rho": -0.13, "home_adv": 1.05, "edge_min": 0.03, "fs_id": None},
    137: {"name": "Coppa Italia",          "tier": "N2", "rho": -0.13, "home_adv": 1.05, "edge_min": 0.03, "fs_id": None},
}

# ─── TRUST MATRIX THRESHOLDS ─────────────────────────────────
TRUST_REJECT_THRESHOLD  = 50   # below → hard reject
TRUST_THIN_DATA_MIN     = 70   # THIN_DATA route needs ≥70
TRUST_MAX_DATA_AGE_MIN  = 60   # data older than 60min → penalise

# ─── EDGE / ROUTING THRESHOLDS ───────────────────────────────
EDGE_ELITE_KO_MIN       = 0.045
EDGE_DOMESTIC_MIN       = 0.030
EDGE_STAR_BIAS_MIN      = 0.050

# ─── GHOST SIGNAL THRESHOLDS ─────────────────────────────────
GHOST_MIN_RELIABILITY   = 0.40   # below → force REJECT
GHOST_MIN_SAMPLES       = 5      # need at least 5 samples to trust reliability

# ─── KELLY / STAKING ─────────────────────────────────────────
KELLY_FRACTION          = 0.25
MAX_STAKE_PCT           = 0.05   # 5% bankroll max
STAKE_ELITE             = (0.0075, 0.010)
STAKE_DOMESTIC          = (0.015,  0.025)
STAKE_STAR_BIAS         = (0.010,  0.010)

# ─── SCORING ─────────────────────────────────────────────────
CONFIDENCE_MIN_BET      = 10
CONFIDENCE_MIN_SIGNAL   = 15
ODD_MIN                 = 1.40
ODD_MAX_BET             = 3.80
ODD_MAX_SIGNAL          = 5.50
ODD_MIN_DRAW            = 2.00
EDGE_MIN_DRAW           = 0.08

# ─── SCAN DEFAULTS ───────────────────────────────────────────
SAFE_MODE_EDGE_BOOST    = 0.01   # Safe mode adds +1% to all edge_min
AGGRESSIVE_EDGE_DISCOUNT= 0.005  # Aggressive mode reduces edge_min by 0.5%

def get_league_cfg(league_id: int) -> dict:
    """Return league config or a generic fallback N3."""
    return LEAGUES.get(league_id, {
        "name": f"League#{league_id}", "tier": "N3",
        "rho": -0.14, "home_adv": 1.10, "edge_min": 0.02, "fs_id": None
    })
