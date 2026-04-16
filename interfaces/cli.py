"""
APEX OMEGA — interfaces/cli.py
CLI: python main.py scan [today|1h|3h|6h|12h|24h|48h]
     python main.py match Arsenal Chelsea [15/07]
     python main.py report
     python main.py history [--n 10]
     python main.py result HASH WIN [profit]
"""
import argparse, re, sys
from datetime import datetime, timezone
from tabulate import tabulate

from core.config import BANKROLL, DEFAULT_MODE
from core.database import init_db
from scanner.scan_engine import run_scan, analyse_by_teams
from storage.signals_repo import get_ghost_stats, get_recent_signals, update_signal_result


def _banner():
    print("=" * 55)
    print("  APEX OMEGA — Football Analytics Engine v1.0")
    print("=" * 55)


def _print_verdict(v: dict):
    fix   = v["fixture"]
    trust = v.get("trust", {})
    model = v.get("model", {})
    probs = model.get("prob_1x2", {})
    print(f"\n{'─'*55}")
    print(f"  {fix.get('team_home')} vs {fix.get('team_away')}")
    print(f"  {fix.get('league_name','?')} | {str(fix.get('date_str',''))[:16]}")
    print(f"  Trust: {trust.get('trust_score','?')}/100 | DCS: {trust.get('dcs',0):.2f}")
    print(f"  xG: {model.get('hxg',0):.2f}—{model.get('axg',0):.2f} | "
          f"Total: {model.get('xg_total',0):.2f}")
    print(f"  Probs: H={probs.get('home',0)*100:.1f}% "
          f"D={probs.get('draw',0)*100:.1f}% "
          f"A={probs.get('away',0)*100:.1f}%")

    if v["status"] == "SIGNAL":
        p = v["primary"]
        print(f"\n  *** SIGNAL: {p['market']} ***")
        print(f"  Cote: {p.get('odds','N/A')} | Edge: +{(p.get('edge') or 0)*100:.2f}%")
        print(f"  Confiance: {p['confidence']}/50 | Stake: {v.get('stake_units',0):.2f}u")
        rows = []
        for m in v.get("all_markets", []):
            e = f"{(m.get('edge') or 0)*100:+.1f}%" if m.get("edge") is not None else "N/A"
            rows.append([m["market"][:28], f"{m['model_prob']*100:.0f}%",
                         str(m.get("odds","—")), e, f"{m['confidence']}/50", m["signal"]])
        if rows:
            print("\n" + tabulate(rows,
                headers=["Marche", "P", "Cote", "Edge", "Conf", "Signal"],
                tablefmt="simple"))
    elif v["status"] == "REJECT":
        print(f"\n  REJECT: {v.get('reason','?')}")
    else:
        print(f"\n  NO BET: {v.get('reason','Pas de value')}")


def _parse_window(w: str) -> int:
    if w == "today":
        return max(24 - datetime.now(timezone.utc).hour, 1)
    m = re.fullmatch(r"(\d+)h", w.lower())
    return int(m.group(1)) if m else 24


def run_cli(argv=None):
    init_db(); _banner()
    p = argparse.ArgumentParser(prog="apex-omega")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("scan")
    sp.add_argument("window", nargs="?", default="24h")
    sp.add_argument("--mode", choices=["safe","aggressive"], default=DEFAULT_MODE)
    sp.add_argument("--bankroll", type=float, default=BANKROLL)

    mp = sub.add_parser("match")
    mp.add_argument("teams", nargs="+")
    mp.add_argument("--mode", choices=["safe","aggressive"], default=DEFAULT_MODE)
    mp.add_argument("--bankroll", type=float, default=BANKROLL)

    sub.add_parser("report")
    hp = sub.add_parser("history")
    hp.add_argument("--n", type=int, default=10)

    rp = sub.add_parser("result")
    rp.add_argument("hash"); rp.add_argument("result", choices=["WIN","LOSS","PUSH"])
    rp.add_argument("pl", nargs="?", type=float, default=0.0)

    ns = p.parse_args(argv)

    if ns.cmd == "scan":
        hrs = _parse_window(ns.window)
        print(f"\nSCAN {hrs}h | Mode:{ns.mode.upper()} | BR:{ns.bankroll:.0f}u\n")
        r = run_scan(hours_ahead=hrs, mode=ns.mode, bankroll=ns.bankroll)
        print(f"Scanned:{r['scanned']} | Signals:{len(r['signals'])} | "
              f"NoBet:{len(r['no_bets'])} | Rejects:{len(r['rejects'])} | {r.get('duration_sec',0):.1f}s")
        for v in r["signals"]:
            _print_verdict(v)

    elif ns.cmd == "match":
        tok = ns.teams
        date_str = None; clean = []
        for t in tok:
            m = re.fullmatch(r"(\d{1,2})[/\-\.](\d{1,2})", t)
            if m:
                date_str = f"{datetime.now().year}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
            else:
                clean.append(t)
        mid = len(clean) // 2
        home, away = " ".join(clean[:mid]), " ".join(clean[mid:])
        print(f"\nANALYSE: {home} vs {away}\n")
        v = analyse_by_teams(home, away, match_date=date_str, mode=ns.mode, bankroll=ns.bankroll)
        _print_verdict(v)

    elif ns.cmd == "report":
        s = get_ghost_stats()
        w, l = s["total_wins"], s["total_losses"]
        t = w + l + s["total_pushes"]
        print(f"\nGHOST MEMORY: {s['patterns_learned']} patterns | "
              f"{s['blocked_patterns']} bloques | {s['pending_signals']} pending")
        print(f"WR: {w/t*100:.1f}% ({w}W/{l}L/{s['total_pushes']}P)" if t else "Aucun signal")
        print(f"P&L: {s['total_pl']:+.2f}u")

    elif ns.cmd == "history":
        sigs = get_recent_signals(limit=ns.n)
        if not sigs:
            print("Aucun signal."); return
        rows = [[f"{s['team_home']} vs {s['team_away']}", s['market_type'],
                 s['pick'], f"{s['odds']:.2f}", f"{s['edge']*100:.1f}%",
                 s['result'], f"{s['profit_loss']:+.2f}u", s['match_date']] for s in sigs]
        print(tabulate(rows, headers=["Match","Marche","Pick","Cote","Edge","Res","P&L","Date"], tablefmt="simple"))

    elif ns.cmd == "result":
        update_signal_result(ns.hash, ns.result, ns.pl)
        print(f"OK: {ns.hash} -> {ns.result} ({ns.pl:+.2f}u)")

    else:
        p.print_help()
