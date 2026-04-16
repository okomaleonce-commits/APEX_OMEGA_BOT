"""
APEX OMEGA — interfaces/cli.py
CLI interface using argparse.
python main.py scan          → 24h scan
python main.py scan today    → today's matches
python main.py scan 1h       → next hour
python main.py scan 6h       → 6 hours
python main.py report        → ghost signal memory report
python main.py analyse "Arsenal" "Chelsea"  → single match
"""
import argparse
import sys
import logging
from datetime import datetime

from core.database import init_db
from core.config import BANKROLL, DEFAULT_MODE
from scanner.scan_engine import run_scan, analyse_single_match
from decisions.rationale_builder import format_verdict_cli, format_scan_summary_telegram
from storage.signals_repo import get_ghost_stats, get_recent_signals

log = logging.getLogger("apex.cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apex-omega",
        description="APEX OMEGA — Football betting analytics engine"
    )
    sub = parser.add_subparsers(dest="command")

    # ── scan ──────────────────────────────────────────────────────
    scan_p = sub.add_parser("scan", help="Scan upcoming fixtures")
    scan_p.add_argument("window", nargs="?", default="24h",
                        help="Time window: today / 1h / 6h / 24h (default)")
    scan_p.add_argument("--mode", choices=["safe", "aggressive"], default=DEFAULT_MODE)
    scan_p.add_argument("--bankroll", type=float, default=BANKROLL)
    scan_p.add_argument("--league", type=int, action="append", dest="leagues",
                        help="Filter by league ID (repeat for multiple)")
    scan_p.add_argument("--max", type=int, default=50, help="Max fixtures to scan")

    # ── report ────────────────────────────────────────────────────
    rep_p = sub.add_parser("report", help="Show ghost signal memory report")
    rep_p.add_argument("--recent", type=int, default=10)

    # ── analyse ───────────────────────────────────────────────────
    ana_p = sub.add_parser("analyse", help="Analyse a specific match")
    ana_p.add_argument("home", help="Home team name")
    ana_p.add_argument("away", help="Away team name")
    ana_p.add_argument("--date", help="Match date YYYY-MM-DD")
    ana_p.add_argument("--league", type=int, help="League ID")
    ana_p.add_argument("--mode", choices=["safe", "aggressive"], default=DEFAULT_MODE)
    ana_p.add_argument("--bankroll", type=float, default=BANKROLL)

    return parser


def _parse_window(window: str) -> int:
    """Convert window string to hours integer."""
    w = window.lower().strip()
    if w in ("today", "aujourd'hui"):
        now = datetime.now()
        return max(1, 24 - now.hour)
    import re
    m = re.match(r"(\d+)\s*h?", w)
    if m:
        return max(1, min(int(m.group(1)), 168))
    return 24


def run_cli(argv=None) -> None:
    init_db()
    parser = build_parser()
    args   = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # ── SCAN ──────────────────────────────────────────────────────
    if args.command == "scan":
        hours = _parse_window(args.window)
        print(f"\n🔍 APEX OMEGA Scan | horizon={hours}h | mode={args.mode}\n")

        result = run_scan(
            hours_ahead=hours,
            league_ids=args.leagues,
            mode=args.mode,
            bankroll=args.bankroll,
            max_fixtures=args.max,
        )

        # Print summary
        sigs = result["signals"]
        print(f"{'='*60}")
        print(f" Fixtures scannées : {result['total']}")
        print(f" Signaux émis      : {len(sigs)}")
        print(f" No Bet            : {len(result['no_bets'])}")
        print(f" Rejetés           : {len(result['rejects'])}")
        print(f" Durée             : {result['duration']}s")
        print(f"{'='*60}")

        for v in sigs:
            print(format_verdict_cli(v))

        if not sigs:
            print("\n  Aucun signal validé dans cette fenêtre.\n")

    # ── REPORT ────────────────────────────────────────────────────
    elif args.command == "report":
        stats   = get_ghost_stats()
        recents = get_recent_signals(args.recent)

        print(f"\n{'='*60}")
        print(f"  APEX OMEGA — Ghost Signal Memory Report")
        print(f"{'='*60}")
        print(f"  Patterns appris  : {stats['patterns_learned']}")
        print(f"  Patterns bloqués : {stats['blocked_patterns']}")
        print(f"  Signaux pending  : {stats['pending_signals']}")
        w = stats['total_wins']; l = stats['total_losses']; p = stats['total_pushes']
        tot = w + l + p
        wr = f"{w/tot*100:.1f}%" if tot > 0 else "—"
        print(f"  W/L/P            : {w}W / {l}L / {p}P  (WR: {wr})")
        print(f"  P/L cumulé       : {stats['total_pl']:+.2f}u")
        print(f"{'─'*60}")

        if recents:
            print(f"\n  Derniers {args.recent} signaux :")
            from tabulate import tabulate
            headers = ["Home", "Away", "Marché", "Cote", "Edge", "Conf", "Résultat", "P/L"]
            rows = [[
                s["team_home"][:12], s["team_away"][:12],
                s["market_type"][:18],
                f"{s.get('odds',0):.2f}",
                f"{s.get('edge',0)*100:+.1f}%" if s.get("edge") else "—",
                f"{s.get('confidence',0)}/50",
                s.get("result","—"),
                f"{s.get('profit_loss',0):+.2f}u"
            ] for s in recents]
            print(tabulate(rows, headers=headers, tablefmt="simple"))
        print()

    # ── ANALYSE ───────────────────────────────────────────────────
    elif args.command == "analyse":
        print(f"\n🎯 Analyse : {args.home} vs {args.away}\n")
        verdict = analyse_single_match(
            args.home, args.away,
            match_date=args.date,
            league_id=args.league,
            mode=args.mode,
            bankroll=args.bankroll,
        )
        print(format_verdict_cli(verdict))
