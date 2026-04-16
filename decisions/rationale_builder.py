"""APEX OMEGA — decisions/rationale_builder.py
Plain text output — no Markdown to avoid Telegram parse errors.
"""
from datetime import datetime, timezone

SIG_ICO  = {"BET":"[BET]","SIGNAL":"[SIGNAL]","NO_BET":"[NO BET]","REJECT":"[REJECT]"}
TIER_ICO = {"P0":"[UCL]","N1":"[TOP5]","N2":"[N2]","N3":"[N3]"}
CONF_LBL = lambda c: "FAIBLE" if c < 20 else "MOYEN" if c < 35 else "FORT"


def _d(date_str):
    if not date_str: return "—"
    try:
        dt = datetime.fromisoformat(str(date_str).replace("Z","+00:00"))
        return dt.strftime("%d/%m %H:%M UTC")
    except Exception:
        return str(date_str)[:16]


def _sep(char="─", n=42):
    return char * n


def format_scan_summary(r: dict) -> str:
    ns = len(r["signals"]); nb = len(r["no_bets"]); nj = len(r["rejects"])
    lines = [
        _sep("═"),
        "  APEX OMEGA — SCAN REPORT",
        _sep("═"),
        f"Fenetre : {r['hours']}h | Mode : {r['mode'].upper()}",
        f"Analyses: {r['scanned']}  Signaux: {ns}  NoBet: {nb}  Rejects: {nj}",
        f"Duree   : {r.get('duration_sec',0):.1f}s",
        _sep(),
    ]
    if not r["signals"]:
        lines.append("Aucun signal de valeur detecte.")
        return "\n".join(lines)

    lines.append("SIGNAUX VALIDES")
    lines.append(_sep())
    for v in r["signals"]:
        fix = v["fixture"]; p = v["primary"]
        lines += [
            f"{fix['team_home']} vs {fix['team_away']}",
            f"  {_d(fix.get('date_str'))} | {fix.get('league_name','?')}",
            f"  {SIG_ICO.get(p['signal'],'?')} {p['market']}",
            f"  Cote: {p.get('odds','N/A')} | Edge: {(p.get('edge') or 0)*100:+.1f}%",
            f"  Confiance: {p['confidence']}/50 ({CONF_LBL(p['confidence'])})",
            f"  Mise: {v.get('stake_units',0):.1f}u ({v.get('stake_pct',0):.1f}%)",
            "",
        ]
    return "\n".join(lines)


def format_verdict_telegram(v: dict, include_all_markets: bool = True) -> str:
    status  = v["status"]
    fix     = v["fixture"]
    trust   = v.get("trust", {})
    model   = v.get("model", {})
    cfg     = v.get("league_cfg", {})
    tier    = cfg.get("tier","N3")

    probs   = model.get("prob_1x2",{})
    dcs     = trust.get("dcs",0)
    hxg     = model.get("hxg",0)
    axg     = model.get("axg",0)
    ts      = trust.get("trust_score","?")

    lines = [
        _sep("═"),
        f"APEX OMEGA — ANALYSE  {TIER_ICO.get(tier,'')}",
        _sep("═"),
        f"{fix.get('league_name','?')}"
        f" | {_d(fix.get('date_str'))}",
        f"{fix.get('team_home','?')} vs {fix.get('team_away','?')}",
        _sep(),
        "MODELE DIXON-COLES",
        f"  xG : {hxg:.2f} (dom) — {axg:.2f} (ext)"
        f" | Total: {hxg+axg:.2f}",
        f"  DCS : {dcs:.2f} | Trust: {ts}/100",
        f"  Prob: H={probs.get('home',0)*100:.1f}%"
        f"  D={probs.get('draw',0)*100:.1f}%"
        f"  A={probs.get('away',0)*100:.1f}%",
    ]

    top = model.get("top_scores",[])
    if top:
        sc = "  ".join(f"{h}-{a}({p*100:.0f}%)" for h,a,p in top[:4])
        lines.append(f"  Scores prob: {sc}")

    h2h = v.get("h2h",[])
    if h2h:
        avg   = sum(m.get("total",0) for m in h2h)/len(h2h)
        btts_r = sum(1 for m in h2h if m.get("btts"))/len(h2h)*100
        lines += [_sep(), f"H2H ({len(h2h)} matchs): moy {avg:.1f}g | BTTS {btts_r:.0f}%"]
        for m in h2h[:3]:
            lines.append(f"  {m.get('date','?')} {m.get('home','?')} {m.get('score','?')} {m.get('away','?')}")

    if include_all_markets and v.get("all_markets"):
        lines += [_sep(), "MARCHES ANALYSES"]
        for m in v["all_markets"]:
            e = f"{(m.get('edge') or 0)*100:+.1f}%" if m.get("edge") is not None else " N/A"
            sig = SIG_ICO.get(m["signal"],"   ?")
            lines.append(
                f"  {sig} {m['market'][:28]:<28}"
                f" P:{m['model_prob']*100:.0f}%"
                f" C:{m.get('odds','—')}"
                f" E:{e}"
                f" Conf:{m['confidence']}/50"
            )

    flags = trust.get("flags",[])
    if flags:
        lines += [_sep(), "ALERTES"]
        for f in flags:
            lines.append(f"  ! {f}")

    lines.append(_sep())

    if status == "REJECT":
        lines.append(f"REJECT: {v.get('reason','?')}"),
        return "\n".join(lines)

    if status == "NO_BET":
        lines.append(f"NO BET — {v.get('reason','Pas de value')}")
        return "\n".join(lines)

    p   = v["primary"]
    route = v.get("route","?")
    lines += [
        f"DECISION : {SIG_ICO.get(p['signal'],'?')}",
        f"  Marche : {p['market']}",
        f"  Cote   : {p.get('odds','N/A')}",
        f"  Edge   : {(p.get('edge') or 0)*100:+.2f}%",
        f"  Conf   : {p['confidence']}/50 ({CONF_LBL(p['confidence'])})",
        f"  Route  : {route} | Mode: {v.get('mode','?').upper()}",
        "",
        "KELLY / MISE",
        f"  Kelly brut : {v.get('kelly_raw',0):.1f}%"
        f" -> Kelly 1/4: {v.get('kelly_frac_pct',0):.2f}%",
        f"  Mise       : {v.get('stake_units',0):.2f}u"
        f" / {v.get('bankroll',1000):.0f}u"
        f" ({v.get('stake_pct',0):.2f}%)",
    ]

    secs = [m for m in v.get("valid_markets",[]) if m != p]
    if secs:
        lines += ["", "COMPLEMENTAIRES"]
        for m in secs[:4]:
            lines.append(
                f"  {m['market']} | E:{(m.get('edge') or 0)*100:+.1f}%"
                f" | Conf:{m['confidence']}/50"
            )

    ghost = (p.get("ghost") or {})
    if ghost.get("samples",0) >= 5:
        lines += [
            "",
            f"GHOST MEMORY: {(ghost.get('reliability',0))*100:.0f}%"
            f" sur {ghost['samples']} signaux",
        ]

    return "\n".join(lines)
