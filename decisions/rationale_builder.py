"""
APEX OMEGA — decisions/rationale_builder.py
Formats verdict dicts into readable Telegram Markdown / CLI ASCII output.
"""
from datetime import datetime, timezone
from typing import Optional


def format_verdict_telegram(verdict: dict) -> str:
    """
    Full Telegram-formatted verdict message with all markets.
    Uses MarkdownV2-compatible escaping.
    """
    status  = verdict.get("status", "REJECT")
    fixture = verdict.get("fixture", {})
    trust   = verdict.get("trust", {})
    model   = verdict.get("model", {})

    home = fixture.get("team_home", "?")
    away = fixture.get("team_away", "?")
    league = fixture.get("league_name", "Unknown")
    match_dt = _fmt_date(fixture.get("date_str"))

    hxg = verdict.get("hxg_used", 0)
    axg = verdict.get("axg_used", 0)

    lines = []

    # ── HEADER ──────────────────────────────────────────────────────
    tier_emoji = {"P0": "🏆", "N1": "⭐", "N2": "🔵", "N3": "⚪"}.get(
        verdict.get("league_cfg", {}).get("tier", "N3"), "⚽"
    )
    lines.append(f"{'═'*44}")
    lines.append(f"🤖 *APEX OMEGA* — Analyse de match")
    lines.append(f"{'═'*44}")
    lines.append(f"{tier_emoji} *{_esc(league)}* | {match_dt}")
    lines.append(f"⚽ *{_esc(home)}* vs *{_esc(away)}*")
    lines.append("")

    # ── MODULE 1: DONNÉES ────────────────────────────────────────────
    dcs   = trust.get("dcs", 0)
    tscore = trust.get("trust_score", 0)
    dcs_bar = _progress_bar(dcs, 1.0, 10)
    trust_bar = _progress_bar(tscore, 100, 10)
    xg_src_h = verdict.get("xg_home", {}).get("source", "none")
    xg_src_a = verdict.get("xg_away", {}).get("source", "none")

    lines.append("📊 *MODULE 1 — DONNÉES & CONFIANCE*")
    lines.append(f"  xG Domicile  : `{hxg:.2f}` _{xg_src_h}_")
    lines.append(f"  xG Extérieur : `{axg:.2f}` _{xg_src_a}_")
    lines.append(f"  xG Total     : `{hxg+axg:.2f}`")
    lines.append(f"  DCS          : `{dcs:.2f}` {dcs_bar} {'✅' if dcs>=0.58 else '🔴'}")
    lines.append(f"  Trust Score  : `{tscore}/100` {trust_bar} _{trust.get('trust_label','')}_")

    if trust.get("flags"):
        for flag in trust["flags"]:
            lines.append(f"  ⚠️ `{flag}`")
    lines.append("")

    # ── MODULE 2: PROBABILITÉS ───────────────────────────────────────
    probs = model.get("prob_1x2", {})
    ph = probs.get("home", 0)
    pd = probs.get("draw", 0)
    pa = probs.get("away", 0)
    rho = model.get("rho", -0.13)

    lines.append(f"🧮 *MODULE 2 — PROBABILITÉS DIXON\\-COLES* \\(ρ={rho}\\)")
    lines.append(f"  P\\(Domicile\\)  : `{ph*100:.1f}%` {_prob_bar(ph)}")
    lines.append(f"  P\\(Nul\\)       : `{pd*100:.1f}%` {_prob_bar(pd)}")
    lines.append(f"  P\\(Extérieur\\) : `{pa*100:.1f}%` {_prob_bar(pa)}")
    lines.append("")

    # ── MODULE 3: COTES ──────────────────────────────────────────────
    odds_data = verdict.get("odds_data", {})
    odds_1x2  = odds_data.get("odds_1x2") or {}
    bm        = odds_data.get("bookmaker", "—")

    lines.append(f"💰 *MODULE 3 — COTES BOOKMAKER* \\({_esc(bm)}\\)")
    if odds_1x2.get("home"):
        ih = 1/odds_1x2["home"] if odds_1x2["home"] else 0
        id_ = 1/odds_1x2["draw"] if odds_1x2.get("draw") else 0
        ia  = 1/odds_1x2["away"] if odds_1x2.get("away") else 0
        lines.append(f"  Cotes   : `{odds_1x2.get('home','—')}` / `{odds_1x2.get('draw','—')}` / `{odds_1x2.get('away','—')}`")
        lines.append(f"  Implicite: `{ih*100:.0f}%` / `{id_*100:.0f}%` / `{ia*100:.0f}%`")
    else:
        lines.append("  _Aucune cote disponible_")
    lines.append("")

    # ── EARLY RETURN: REJECT ─────────────────────────────────────────
    if status == "REJECT":
        lines.append("🚫 *VERDICT : REJETÉ*")
        lines.append(f"  Raison : `{_esc(verdict.get('reason','—'))}`")
        lines.append(f"{'─'*44}")
        return "\n".join(lines)

    # ── MODULE 4: TABLEAU COMPLET DES MARCHÉS ───────────────────────
    all_markets = verdict.get("all_markets", [])
    lines.append("🎯 *MODULE 4 — TOUS LES MARCHÉS*")
    lines.append(f"  `{'Marché':<26} {'P%':>5} {'Cote':>5} {'Edge':>6} {'Conf':>5} {'Signal':>8}`")
    lines.append(f"  `{'─'*60}`")

    for m in all_markets:
        p_str    = f"{m['model_prob']*100:.0f}%"
        odd_str  = f"{m['odds']:.2f}" if m.get("odds") else "—"
        edge_str = f"{m['edge']*100:+.1f}%" if m.get("edge") is not None else "—"
        conf_str = f"{m['confidence']}/50"
        sig      = m["signal"]
        sig_icon = {"BET": "✅", "SIGNAL": "📡", "NO_BET": "❌"}.get(sig, "❌")

        label = m["market"][:26]
        ghost_flag = " 👻" if m.get("ghost", {}) and m["ghost"].get("blocked") else ""
        lines.append(f"  `{label:<26} {p_str:>5} {odd_str:>5} {edge_str:>6} {conf_str:>5}` {sig_icon}{ghost_flag}")

    lines.append("")

    # ── MODULE 5: H2H ───────────────────────────────────────────────
    h2h       = verdict.get("h2h", [])
    form_home = verdict.get("form_home", [])
    form_away = verdict.get("form_away", [])

    lines.append("📈 *MODULE 5 — H2H & FORME*")
    if h2h:
        avg_goals = sum(r.get("total", 0) for r in h2h) / len(h2h)
        btts_rate = sum(1 for r in h2h if r.get("btts")) / len(h2h)
        h2h_scores = " | ".join(r.get("score", "?") for r in h2h[:5])
        lines.append(f"  H2H scores   : `{h2h_scores}`")
        lines.append(f"  Moy. buts H2H: `{avg_goals:.1f}` | BTTS rate: `{btts_rate*100:.0f}%`")
    else:
        lines.append("  _H2H non disponible_")

    fh_str = "".join(r.get("result","?") for r in form_home[:5]) or "—"
    fa_str = "".join(r.get("result","?") for r in form_away[:5]) or "—"
    lines.append(f"  Forme {_esc(home[:12])}: `{fh_str}`")
    lines.append(f"  Forme {_esc(away[:12])}: `{fa_str}`")
    lines.append("")

    # ── MODULE 6: SCORES EXACTS ─────────────────────────────────────
    top_scores = model.get("top_scores", [])
    if top_scores:
        lines.append("🎲 *MODULE 6 — SCORES EXACTS LES PLUS PROBABLES*")
        for h, a, p in top_scores[:5]:
            bar = "█" * int(p * 100)
            lines.append(f"  `{h}-{a}` : `{p*100:.1f}%` {bar}")
        lines.append("")

    # ── MODULE 7: KELLY & SIZING ────────────────────────────────────
    if status == "SIGNAL":
        lines.append("🏦 *MODULE 7 — KELLY & MISE*")
        lines.append(f"  Kelly brut    : `{verdict.get('kelly_raw',0):.1f}%`")
        lines.append(f"  Kelly 25%     : `{verdict.get('kelly_frac_pct',0):.1f}%`")
        lines.append(f"  Stake suggéré : `{verdict.get('stake_pct',0):.2f}%` → `{verdict.get('stake_units',0):.2f}` unités")
        lines.append(f"  Bankroll      : `{verdict.get('bankroll',1000):.0f}` unités")
        lines.append(f"  Route         : `{verdict.get('route','—')}`")
        lines.append("")

    # ── VERDICT FINAL ───────────────────────────────────────────────
    lines.append(f"{'═'*44}")
    if status == "SIGNAL":
        primary = verdict.get("primary", {})
        sig_emoji = "🚀 BET" if primary.get("signal") == "BET" else "📡 SIGNAL"
        lines.append(f"*{sig_emoji}*")
        lines.append(f"  Marché  : `{_esc(primary.get('market','—'))}`")
        lines.append(f"  Pick    : `{_esc(str(primary.get('outcome_key','—')).upper())}`")
        odd_v = primary.get('odds')
        lines.append(f"  Cote    : `{odd_v:.2f}`" if odd_v else "  Cote    : _Signal pur_")
        edge_v = primary.get('edge')
        lines.append(f"  Edge    : `{edge_v*100:+.2f}%`" if edge_v is not None else "  Edge    : `—`")
        lines.append(f"  Confiance: `{primary.get('confidence',0)}/50`")
        lines.append(f"  Mise    : `{verdict.get('stake_units',0):.2f}u` \\(`{verdict.get('stake_pct',0):.2f}%` bankroll\\)")

        # Confirmed secondary markets
        others = [m for m in verdict.get("valid_markets", []) if m != primary]
        if others:
            lines.append("")
            lines.append("📋 *MARCHÉS SECONDAIRES CONFIRMÉS :*")
            for m in others[:4]:
                o = m.get("odds")
                e = m.get("edge")
                lines.append(
                    f"  • `{_esc(m['market'])}` @ `{o:.2f}`  edge `{e*100:+.1f}%`  conf `{m['confidence']}/50`"
                    if o and e is not None else
                    f"  • `{_esc(m['market'])}` — conf `{m['confidence']}/50`"
                )
    else:
        lines.append("⛔ *NO BET*")
        lines.append(f"  Raison: `{_esc(verdict.get('reason','—'))}`")

    ghost = verdict.get("ghost_stats", {})
    if ghost:
        lines.append("")
        lines.append(f"👻 _Ghost Memory: {ghost.get('patterns_learned',0)} patterns | "
                     f"{ghost.get('blocked_patterns',0)} bloqués_")

    lines.append(f"{'─'*44}")
    lines.append(f"_Mode: {verdict.get('mode','safe')} | "
                 f"Scan: {datetime.now(timezone.utc).strftime('%H:%M UTC')}_")

    return "\n".join(lines)


def format_scan_summary_telegram(scan_result: dict) -> str:
    """Summary message after a full scan."""
    signals   = scan_result.get("signals", [])
    no_bets   = scan_result.get("no_bets", [])
    rejects   = scan_result.get("rejects", [])
    mode      = scan_result.get("mode", "safe")
    hours     = scan_result.get("hours", 24)
    duration  = scan_result.get("duration", 0)
    ghost     = scan_result.get("ghost_stats", {})

    lines = []
    lines.append(f"{'═'*44}")
    lines.append(f"🤖 *APEX OMEGA — Rapport de Scan*")
    lines.append(f"{'═'*44}")
    lines.append(f"📅 Horizon  : `{hours}h` | Mode: `{mode.upper()}`")
    lines.append(f"🔍 Matchs   : `{scan_result.get('total',0)}` scannés en `{duration}s`")
    lines.append(f"✅ Signaux  : `{len(signals)}`")
    lines.append(f"⛔ No Bet   : `{len(no_bets)}`")
    lines.append(f"🚫 Rejetés  : `{len(rejects)}`")
    lines.append("")

    if signals:
        lines.append("🚀 *SIGNAUX DÉTECTÉS :*")
        for v in signals:
            fix = v.get("fixture", {})
            p   = v.get("primary", {})
            home = fix.get("team_home", "?")[:14]
            away = fix.get("team_away", "?")[:14]
            league = fix.get("league_name", "?")[:20]
            dt = _fmt_date(fix.get("date_str"), short=True)
            odd  = p.get("odds")
            edge = p.get("edge")
            conf = p.get("confidence", 0)
            sig_icon = "🚀" if p.get("signal") == "BET" else "📡"
            odd_str  = f"@ {odd:.2f}" if odd else "signal pur"
            edge_str = f"edge {edge*100:+.1f}%" if edge is not None else ""
            lines.append(
                f"  {sig_icon} *{_esc(home)} vs {_esc(away)}*"
            )
            lines.append(
                f"     `{_esc(p.get('market','?'))}` {odd_str} {edge_str} conf `{conf}/50`"
            )
            lines.append(f"     {_esc(league)} | {dt}")
    else:
        lines.append("_Aucun signal validé dans cette fenêtre_")

    lines.append("")
    lines.append(f"👻 _Ghost Memory: {ghost.get('patterns_learned',0)} patterns | "
                 f"{ghost.get('blocked_patterns',0)} bloqués | "
                 f"P/L cumulé: {ghost.get('total_pl',0):+.1f}u_")
    lines.append(f"{'─'*44}")

    return "\n".join(lines)


def format_stats_telegram(ghost_stats: dict, recent_signals: list) -> str:
    """Stats message for /stats command."""
    lines = []
    lines.append(f"{'═'*44}")
    lines.append("📊 *APEX OMEGA — Statistiques*")
    lines.append(f"{'═'*44}")
    lines.append(f"👻 *Ghost Signal Memory*")
    lines.append(f"  Patterns appris : `{ghost_stats.get('patterns_learned',0)}`")
    lines.append(f"  Patterns bloqués: `{ghost_stats.get('blocked_patterns',0)}`")
    lines.append(f"  Signaux pending : `{ghost_stats.get('pending_signals',0)}`")
    w = ghost_stats.get('total_wins', 0)
    l = ghost_stats.get('total_losses', 0)
    pu = ghost_stats.get('total_pushes', 0)
    tot = w + l + pu
    wr = f"{w/tot*100:.0f}%" if tot > 0 else "—"
    lines.append(f"  Win/Loss/Push   : `{w}W / {l}L / {pu}P` \\(WR: {wr}\\)")
    lines.append(f"  P/L cumulé      : `{ghost_stats.get('total_pl',0):+.2f}u`")
    lines.append("")

    if recent_signals:
        lines.append("📋 *10 derniers signaux :*")
        for s in recent_signals:
            res_icon = {"WIN": "✅", "LOSS": "❌", "PUSH": "🔄", "PENDING": "⏳"}.get(
                s.get("result", "PENDING"), "⏳"
            )
            lines.append(
                f"  {res_icon} `{s['team_home'][:10]} vs {s['team_away'][:10]}` "
                f"— {s.get('market_type','?')[:20]} "
                f"@ {s.get('odds',0):.2f} "
                f"P/L: `{s.get('profit_loss',0):+.2f}u`"
            )

    lines.append(f"{'─'*44}")
    return "\n".join(lines)


def format_verdict_cli(verdict: dict) -> str:
    """CLI ASCII table format."""
    from tabulate import tabulate

    fixture = verdict.get("fixture", {})
    status  = verdict.get("status", "REJECT")
    model   = verdict.get("model", {})
    trust   = verdict.get("trust", {})
    probs   = model.get("prob_1x2", {})

    h = fixture.get("team_home", "?")
    a = fixture.get("team_away", "?")

    out = []
    out.append("=" * 60)
    out.append(f"  APEX OMEGA | {h} vs {a}")
    out.append(f"  {fixture.get('league_name','?')} | {_fmt_date(fixture.get('date_str'))}")
    out.append("=" * 60)
    out.append(f"  Trust: {trust.get('trust_score',0)}/100 | DCS: {trust.get('dcs',0):.2f}")
    out.append(f"  P(H): {probs.get('home',0)*100:.1f}%  P(D): {probs.get('draw',0)*100:.1f}%  P(A): {probs.get('away',0)*100:.1f}%")
    out.append(f"  hxG={verdict.get('hxg_used',0):.2f}  axG={verdict.get('axg_used',0):.2f}")
    out.append("-" * 60)

    if verdict.get("all_markets"):
        headers = ["Market", "P%", "Odd", "Edge", "Conf", "Signal"]
        rows = []
        for m in verdict["all_markets"]:
            p = f"{m['model_prob']*100:.0f}%"
            o = f"{m['odds']:.2f}" if m.get("odds") else "—"
            e = f"{m['edge']*100:+.1f}%" if m.get("edge") is not None else "—"
            c = f"{m['confidence']}/50"
            s = m["signal"]
            rows.append([m["market"][:30], p, o, e, c, s])
        out.append(tabulate(rows, headers=headers, tablefmt="simple"))

    out.append("-" * 60)
    if status == "SIGNAL":
        p = verdict.get("primary", {})
        out.append(f"  ✅ SIGNAL: {p.get('market')} | {p.get('outcome_key','').upper()}")
        out.append(f"  Mise: {verdict.get('stake_pct',0):.2f}% = {verdict.get('stake_units',0):.2f}u")
    else:
        out.append(f"  ⛔ {status}: {verdict.get('reason','—')}")
    out.append("=" * 60)
    return "\n".join(out)


# ── HELPERS ──────────────────────────────────────────────────

def _esc(text: str) -> str:
    """Escape Telegram MarkdownV2 special chars."""
    if not text:
        return ""
    for ch in r"\_*[]()~`>#+=|{}.!-":
        text = text.replace(ch, f"\\{ch}")
    return text


def _fmt_date(date_str: Optional[str], short: bool = False) -> str:
    if not date_str:
        return "—"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if short:
            return dt.strftime("%d/%m %H:%M")
        return dt.strftime("%d/%m/%Y %H:%M UTC")
    except Exception:
        return date_str[:16] if date_str else "—"


def _progress_bar(value: float, max_val: float, width: int = 8) -> str:
    pct = min(1.0, value / max_val) if max_val > 0 else 0
    filled = int(pct * width)
    return "█" * filled + "░" * (width - filled)


def _prob_bar(prob: float) -> str:
    bars = int(prob * 20)
    return "▓" * bars + "░" * (20 - bars)
