"""APEX OMEGA — risk/bankroll.py  (stub, extended in future versions)"""
from core.config import BANKROLL, MAX_STAKE_PCT, KELLY_FRACTION

def compute_stake(kelly_f: float, bankroll: float = BANKROLL) -> float:
    stake_pct = min(kelly_f * KELLY_FRACTION, MAX_STAKE_PCT)
    return round(bankroll * stake_pct, 2)
