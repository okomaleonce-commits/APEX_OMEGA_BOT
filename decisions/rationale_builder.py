"""APEX OMEGA — decisions/rationale_builder.py"""
from datetime import datetime, timezone

SIG_ICO  = {"BET":"🚀","SIGNAL":"📡","NO_BET":"⛔","REJECT":"🚫"}
TIER_ICO = {"P0":"🏆","N1":"⭐","N2":"🔵","N3":"🟡"}
TRST_ICO = {"STRONG":"🟢","MODERATE":"🟡","WEAK":"🔴"}


def _d(date_str):
    if not date_str: return "—"
    try:
        dt = datetime.fromisoformat(str(date_str).replace("Z","+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(date_str)[:16]


def format_scan_summary(r: dict) -> str:
    n = len(r["signals"]); nb = len(r["no_bets"]); nj = len(r["rejects"])
    msg = (f"APEX OMEGA — SCAN REPORT\n\n"
           f"Fenetre: {r['hours']}h | Mode: {r['mode'].upper()}\n"
           f"Analyses: {r['scanned']} | Signaux: {n} | NoBet: {nb} | Rejects: {nj}\n"
           f"Duree: {r.get('duration_sec',0):.1f}s\n\n")
    if not r["signals"]:
        return msg + "Aucun signal de valeur detecte.\n"
    msg += "SIGNAUX VALIDES\n" + "─"*40 + "\n"
    for v in r["signals"]:
        fix = v["fixture"]; p = v["primary"]
        msg += (f"\n{fix['team_home']} vs {fix['team_away']}\n"
                f"  {_d(fix.get('date_str'))} | {fix.get('league_name','?')}\n"
                f"  {p['market']} @ {p.get('odds','N/A')} | "
                f"Edge +{(p.get('edge') or 0)*100:.1f}% | Conf {p['confidence']}/50\n"
                f"  Mise: {v.get('stake_units',0):.1f}u ({v.get('stake_pct',0):.1f}%)\n")
    return msg


def format_verdict_telegram(v: dict, include_all_markets: bool = True) -> str:
    status  = v["status"]
    fix     = v["fixture"]
    trust   = v.get("trust", {})
    model   = v.get("model", {})
    cfg     = v.get("league_cfg", {})
    tier    = cfg.get("tier","N3")

    h = (f"{TIER_ICO.get(tier,'🔵')} {fix.get('league_name','?')} | {tier} | {_d(fix.get('date_str'))}\n"
         f"*{fix.get('team_home','?')}* vs *{fix.get('team_away','?')}*\n")

    probs = model.get("prob_1x2",{})
    dcs   = trust.get("dcs",0)
    hxg   = model.get("hxg",0); axg = model.get("axg",0)

    mb = (f"\nxG: {hxg:.2f} — {axg:.2f} | Total: {hxg+axg:.2f}\n"
          f"DCS: {dcs:.2f} | Trust: {trust.get('trust_score','?')}/100 "
          f"{TRST_ICO.get(trust.get('trust_label','WEAK'),'')}\n"
          f"Probs DC: H={probs.get('home',0)*100:.1f}% "
          f"D={probs.get('draw',0)*100:.1f}% "
          f"A={probs.get('away',0)*100:.1f}%\n")

    top = model.get("top_scores",[])
    if top:
        sc = "  ".join(f"{h}-{a}({p*100:.0f}%)" for h,a,p in top[:4])
        mb += f"Scores: {sc}\n"

    h2h = v.get("h2h",[])
    hb = ""
    if h2h:
        avg = sum(m.get("total",0) for m in h2h)/len(h2h)
        btts_r = sum(1 for m in h2h if m.get("btts"))/len(h2h)*100
        hb = f"\nH2H (last {len(h2h)}): moy {avg:.1f}g | BTTS {btts_r:.0f}%\n"
        for m in h2h[:5]:
            hb += f"  {m.get('date','?')}: {m.get('score','?')}\n"

    mkt = ""
    if include_all_markets and v.get("all_markets"):
        mkt = "\nTOUS LES MARCHES\n"
        for m in v["all_markets"]:
            e = f"{(m.get('edge') or 0)*100:+.1f}%" if m.get("edge") is not None else "N/A"
            sig = SIG_ICO.get(m["signal"],"—")
            mkt += (f"  {sig} {m['market'][:26]:<26} "
                    f"P:{m['model_prob']*100:.0f}% Cote:{str(m.get('odds','—')):>5} "
                    f"E:{e:>7} C:{m['confidence']}/50\n")

    flags = trust.get("flags",[])
    fb = ("\nALERTES\n" + "\n".join(f"  ! {f}" for f in flags) + "\n") if flags else ""

    if status == "REJECT":
        return h + mb + fb + f"\nREJECT: {v.get('reason','?')}\n"
    if status == "NO_BET":
        return h + mb + hb + mkt + fb + f"\nNO BET — {v.get('reason','Pas de value')}\n"

    p   = v["primary"]
    dec = (f"\nDECISION — {p['signal']}\n"
           f"  Marche  : {p['market']}\n"
           f"  Cote    : {p.get('odds','N/A')}\n"
           f"  Edge    : +{(p.get('edge') or 0)*100:.2f}%\n"
           f"  Conf    : {p['confidence']}/50\n"
           f"  Route   : {v.get('route','?')} | Mode: {v.get('mode','?').upper()}\n\n"
           f"KELLY\n"
           f"  Brut: {v.get('kelly_raw',0):.1f}% -> Frac: {v.get('kelly_frac_pct',0):.2f}%\n"
           f"  Mise: {v.get('stake_units',0):.2f}u / {v.get('bankroll',1000):.0f}u "
           f"({v.get('stake_pct',0):.2f}%)\n")

    secs = [m for m in v.get("valid_markets",[]) if m != p]
    sb = ""
    if secs:
        sb = "\nCOMPLEMENTAIRES\n"
        for m in secs[:4]:
            sb += (f"  {m['market']} @ {m.get('odds','?')} | "
                   f"Edge +{(m.get('edge') or 0)*100:.1f}% | "
                   f"Conf {m['confidence']}/50\n")

    ghost = p.get("ghost",{}) or {}
    gb = ""
    if ghost.get("samples",0) >= 5:
        gb = (f"\nGHOST: {(ghost.get('reliability',0))*100:.0f}% "
              f"fiabilite sur {ghost['samples']} signaux\n")

    return h + mb + hb + mkt + dec + sb + gb + fb
