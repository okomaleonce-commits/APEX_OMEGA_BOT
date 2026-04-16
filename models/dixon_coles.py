"""
APEX OMEGA — models/dixon_coles.py
Dixon-Coles bivariate Poisson model with τ low-score correction.
Produces full probability matrix + 1X2, BTTS, O/U, exact scores.
"""
import math
import logging
from typing import Optional

log = logging.getLogger("apex.model")

MAX_GOALS = 7  # compute P(h, a) for h,a in [0..6]


def tau(h: int, a: int, mu: float, la: float, rho: float) -> float:
    """Dixon-Coles τ correction for low scores."""
    if h == 0 and a == 0:
        return 1 - mu * la * rho
    elif h == 1 and a == 0:
        return 1 + la * rho
    elif h == 0 and a == 1:
        return 1 + mu * rho
    elif h == 1 and a == 1:
        return 1 - rho
    else:
        return 1.0


def poisson_pmf(k: int, lam: float) -> float:
    """P(X=k) for Poisson(λ)."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def build_score_matrix(
    hxg: float,
    axg: float,
    rho: float = -0.13,
    max_goals: int = MAX_GOALS
) -> list[list[float]]:
    """
    Build P(home_goals=h, away_goals=a) matrix [h][a].
    Dimensions: (max_goals+1) × (max_goals+1)
    """
    hxg = max(hxg, 0.01)
    axg = max(axg, 0.01)
    n = max_goals + 1
    matrix = [[0.0] * n for _ in range(n)]

    total = 0.0
    for h in range(n):
        for a in range(n):
            p = poisson_pmf(h, hxg) * poisson_pmf(a, axg) * tau(h, a, hxg, axg, rho)
            p = max(p, 0.0)
            matrix[h][a] = p
            total += p

    # Normalise
    if total > 0:
        for h in range(n):
            for a in range(n):
                matrix[h][a] /= total

    return matrix


def compute_1x2(matrix: list[list[float]]) -> dict:
    """Derive P(Home), P(Draw), P(Away) from score matrix."""
    n = len(matrix)
    p_home = p_draw = p_away = 0.0
    for h in range(n):
        for a in range(len(matrix[h])):
            p = matrix[h][a]
            if h > a:
                p_home += p
            elif h == a:
                p_draw += p
            else:
                p_away += p
    total = p_home + p_draw + p_away
    if total > 0:
        return {
            "home": round(p_home / total, 4),
            "draw": round(p_draw / total, 4),
            "away": round(p_away / total, 4),
        }
    return {"home": 0.333, "draw": 0.333, "away": 0.334}


def compute_btts(matrix: list[list[float]]) -> dict:
    """P(BTTS=Yes) = P(home≥1 AND away≥1)."""
    n = len(matrix)
    p_yes = sum(
        matrix[h][a]
        for h in range(1, n)
        for a in range(1, n)
    )
    return {"yes": round(p_yes, 4), "no": round(1 - p_yes, 4)}


def compute_over_under(matrix: list[list[float]], line: float = 2.5) -> dict:
    """P(total > line) and P(total < line)."""
    n = len(matrix)
    p_over = sum(
        matrix[h][a]
        for h in range(n)
        for a in range(n)
        if h + a > line
    )
    return {"over": round(p_over, 4), "under": round(1 - p_over, 4)}


def compute_double_chance(probs_1x2: dict) -> dict:
    """Double Chance probabilities."""
    return {
        "1X": round(probs_1x2["home"] + probs_1x2["draw"], 4),
        "X2": round(probs_1x2["draw"] + probs_1x2["away"], 4),
        "12": round(probs_1x2["home"] + probs_1x2["away"], 4),
    }


def top_exact_scores(matrix: list[list[float]], top_n: int = 5) -> list[tuple]:
    """Return top N most likely exact scores [(h,a,prob), ...]."""
    n = len(matrix)
    scores = []
    for h in range(n):
        for a in range(len(matrix[h])):
            scores.append((h, a, matrix[h][a]))
    scores.sort(key=lambda x: x[2], reverse=True)
    return [(h, a, round(p, 4)) for h, a, p in scores[:top_n]]


def run_model(
    hxg: float,
    axg: float,
    rho: float = -0.13,
) -> dict:
    """
    Full model run: returns all computed market probabilities.
    This is the single entry point for the probability engine.
    """
    hxg = max(round(hxg, 3), 0.01)
    axg = max(round(axg, 3), 0.01)

    matrix   = build_score_matrix(hxg, axg, rho)
    probs_1x2 = compute_1x2(matrix)
    btts      = compute_btts(matrix)
    ou25      = compute_over_under(matrix, 2.5)
    ou15      = compute_over_under(matrix, 1.5)
    ou35      = compute_over_under(matrix, 3.5)
    ou45      = compute_over_under(matrix, 4.5)
    dc        = compute_double_chance(probs_1x2)
    exact     = top_exact_scores(matrix, top_n=6)

    return {
        "hxg": hxg, "axg": axg, "rho": rho,
        "xg_total": round(hxg + axg, 3),
        "matrix": matrix,
        "prob_1x2": probs_1x2,
        "prob_btts": btts,
        "prob_ou25": ou25,
        "prob_ou15": ou15,
        "prob_ou35": ou35,
        "prob_ou45": ou45,
        "prob_dc":   dc,
        "top_scores": exact,
    }


def compute_edge(model_prob: float, bookmaker_odd: Optional[float]) -> Optional[float]:
    """
    Edge = model_prob - implied_prob(bookmaker_odd).
    Returns None if odd is missing or invalid.
    """
    if not bookmaker_odd or bookmaker_odd <= 1.0:
        return None
    implied = 1.0 / bookmaker_odd
    return round(model_prob - implied, 4)


def kelly_fraction(model_prob: float, bookmaker_odd: float) -> float:
    """
    Full Kelly: f* = (b*p - q) / b
    b = odd - 1, p = model_prob, q = 1 - p
    """
    if not bookmaker_odd or bookmaker_odd <= 1.0:
        return 0.0
    b = bookmaker_odd - 1
    p = model_prob
    q = 1 - p
    f = (b * p - q) / b
    return max(round(f, 4), 0.0)
