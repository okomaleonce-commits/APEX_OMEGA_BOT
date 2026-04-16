"""
APEX OMEGA — interfaces/telegram_bot.py
Full Telegram bot: commands + natural language match parsing.
All scan calls route through scanner/scan_engine.py.
"""
import logging
import re
import asyncio
from datetime import datetime, timezone

from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)
from telegram.constants import ParseMode

from core.config import BOT_TOKEN, BANKROLL, DEFAULT_MODE
# init_db called in main.py
from scanner.scan_engine import run_scan, analyse_by_teams
from decisions.rationale_builder import format_verdict_telegram, format_scan_summary
from storage.signals_repo import get_ghost_stats, get_recent_signals, update_signal_result

log = logging.getLogger("apex.telegram")

_BOT_MODE = DEFAULT_MODE
_BANKROLL = BANKROLL
_SCANNING = False

LEAGUE_ALIASES = {
    "epl": 39, "premier": 39, "premierleague": 39, "pl": 39,
    "laliga": 140, "liga": 140, "espagne": 140,
    "bundesliga": 78, "bl": 78, "allemagne": 78,
    "seriea": 135, "serie": 135, "italie": 135,
    "ligue1": 61, "l1": 61, "france": 61,
    "ucl": 2, "cl": 2, "champions": 2,
    "uel": 3, "europa": 3,
    "uecl": 848, "conference": 848,
}


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "╔══════════════════════════════════════╗\n"
        "║  *APEX OMEGA BOT v1\\.0*\n"
        "╚══════════════════════════════════════╝\n\n"
        "🤖 Intelligence analytique football activée\\.\n\n"
        "*COMMANDES:*\n"
        "  /scan — Scan 24h\n"
        "  /scan\\_today — Matchs du jour\n"
        "  /scan\\_1h — Urgence 1h\n"
        "  /scan\\_3h — Prochaines 3h\n"
        "  /scan\\_6h — Prochaines 6h\n"
        "  /scan\\_12h — Prochaines 12h\n"
        "  /scan\\_48h — Prochaines 48h\n"
        "  /stats — Ghost Memory & P\\&L\n"
        "  /history — 10 derniers signaux\n"
        "  /mode — Safe ↔ Aggressive\n"
        "  /bankroll \\[montant\\] — Définir bankroll\n\n"
        "*ANALYSE DIRECTE \\(exemples\\):*\n"
        "  `Arsenal Chelsea`\n"
        "  `ligue1 PSG Lyon`\n"
        "  `ucl Man City Real Madrid`\n"
        "  `Arsenal Chelsea 15/07`\n\n"
        f"Mode: {_BOT_MODE.upper()} | Bankroll: {_BANKROLL:.0f}u"
    )
    # Use simpler text to avoid MarkdownV2 issues
    simple = (
        "APEX OMEGA BOT v1.0\n\n"
        "Commandes disponibles:\n"
        "/scan | /scan_today | /scan_1h | /scan_3h\n"
        "/scan_6h | /scan_12h | /scan_48h\n"
        "/stats | /history | /mode | /bankroll\n\n"
        "Analyse directe:\n"
        "  Arsenal Chelsea\n"
        "  ligue1 PSG Lyon\n"
        "  ucl Man City Real Madrid 15/07\n\n"
        f"Mode: {_BOT_MODE.upper()} | Bankroll: {_BANKROLL:.0f}u"
    )
    await update.message.reply_text(simple)


async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _do_scan(update, ctx, hours=24)

async def cmd_scan_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now(timezone.utc)
    hours = max(24 - now.hour, 1)
    await _do_scan(update, ctx, hours=hours)

async def cmd_scan_1h(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _do_scan(update, ctx, hours=1)

async def cmd_scan_3h(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _do_scan(update, ctx, hours=3)

async def cmd_scan_6h(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _do_scan(update, ctx, hours=6)

async def cmd_scan_12h(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _do_scan(update, ctx, hours=12)

async def cmd_scan_48h(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _do_scan(update, ctx, hours=48)


async def _do_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE, hours: int) -> None:
    global _SCANNING
    if _SCANNING:
        await update.message.reply_text("Scan deja en cours, patience...")
        return

    _SCANNING = True
    msg = await update.message.reply_text(
        f"Scan lance — {hours}h | Mode {_BOT_MODE.upper()}\nRecuperation fixtures..."
    )

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: run_scan(hours_ahead=hours, mode=_BOT_MODE, bankroll=_BANKROLL)
        )
        summary = format_scan_summary(result)
        await msg.edit_text(summary, parse_mode=ParseMode.MARKDOWN)

        for verdict in result["signals"]:
            card = format_verdict_telegram(verdict, include_all_markets=True)
            for chunk in _split_message(card):
                await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        log.error(f"Scan error: {e}", exc_info=True)
        await msg.edit_text(f"Erreur scan: {e}")
    finally:
        _SCANNING = False


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    stats = get_ghost_stats()
    w, l  = stats["total_wins"], stats["total_losses"]
    total = w + l + stats["total_pushes"]
    wr    = w / total * 100 if total > 0 else 0

    text = (
        f"APEX OMEGA — STATISTIQUES\n\n"
        f"Bankroll       : {_BANKROLL:.0f}u\n"
        f"Mode           : {_BOT_MODE.upper()}\n\n"
        f"GHOST MEMORY\n"
        f"  Patterns      : {stats['patterns_learned']}\n"
        f"  Bloques       : {stats['blocked_patterns']}\n"
        f"  En attente    : {stats['pending_signals']}\n\n"
        f"HISTORIQUE\n"
        f"  Signaux       : {total}\n"
        f"  W/L           : {w}W / {l}L ({wr:.1f}%)\n"
        f"  P&L           : {stats['total_pl']:+.2f}u\n"
    )
    await update.message.reply_text(text)


async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    signals = get_recent_signals(limit=10)
    if not signals:
        await update.message.reply_text("Aucun signal enregistre.")
        return

    lines = ["10 DERNIERS SIGNAUX\n\n"]
    icons = {"WIN": "V", "LOSS": "X", "PUSH": "~", "PENDING": "..."}
    for s in signals:
        ic = icons.get(s["result"], "?")
        lines.append(
            f"[{ic}] {s['team_home']} vs {s['team_away']}\n"
            f"    {s['market_type']} | {s['pick']} @ {s['odds']:.2f} "
            f"| Edge {s['edge']*100:.1f}% | {s['match_date']}\n"
            f"    PL: {s['profit_loss']:+.2f}u\n\n"
        )
    await update.message.reply_text("".join(lines))


async def cmd_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    global _BOT_MODE
    _BOT_MODE = "aggressive" if _BOT_MODE == "safe" else "safe"
    await update.message.reply_text(
        f"Mode bascule -> {_BOT_MODE.upper()}\n\n"
        "SAFE       = seuils hauts, moins de signaux\n"
        "AGGRESSIVE = seuils bas, plus de signaux"
    )


async def cmd_bankroll(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    global _BANKROLL
    args = ctx.args
    if args and args[0].replace(".", "", 1).isdigit():
        _BANKROLL = float(args[0])
        await update.message.reply_text(f"Bankroll: {_BANKROLL:.0f} unites")
    else:
        await update.message.reply_text(f"Bankroll actuelle: {_BANKROLL:.0f}u\nUsage: /bankroll 5000")


async def cmd_result(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /result <hash> WIN|LOSS|PUSH [profit]")
        return
    sig_hash = args[0]
    result   = args[1].upper()
    pl       = float(args[2]) if len(args) > 2 else 0.0
    if result not in ("WIN", "LOSS", "PUSH"):
        await update.message.reply_text("Resultat invalide: WIN, LOSS ou PUSH")
        return
    update_signal_result(sig_hash, result, pl)
    await update.message.reply_text(f"Resultat enregistre: {sig_hash} -> {result} ({pl:+.2f}u)")


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    if not text or text.startswith("/"):
        return

    match = _parse_match_request(text)
    if not match:
        return

    team_home  = match["home"]
    team_away  = match["away"]
    match_date = match.get("date")
    league_id  = match.get("league_id")

    await update.message.reply_text(
        f"Analyse: {team_home} vs {team_away}\nCollecte en cours..."
    )

    try:
        loop = asyncio.get_event_loop()
        verdict = await loop.run_in_executor(
            None,
            lambda: analyse_by_teams(
                team_home, team_away,
                match_date=match_date, league_id=league_id,
                mode=_BOT_MODE, bankroll=_BANKROLL
            )
        )
        card = format_verdict_telegram(verdict, include_all_markets=True)
        for chunk in _split_message(card):
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        log.error(f"Analysis error: {e}", exc_info=True)
        await update.message.reply_text(f"Erreur: {e}")


def _parse_match_request(text: str) -> dict | None:
    tokens = text.strip().split()
    if len(tokens) < 2:
        return None

    result = {"home": None, "away": None, "date": None, "league_id": None}

    # League alias at start
    if tokens and tokens[0].lower().replace(" ", "") in LEAGUE_ALIASES:
        result["league_id"] = LEAGUE_ALIASES[tokens[0].lower().replace(" ", "")]
        tokens = tokens[1:]

    if len(tokens) < 2:
        return None

    # Date detection
    date_re = re.compile(r"^(\d{1,2})[/\-\.](\d{1,2})(?:[/\-\.](\d{2,4}))?$")
    clean = []
    for t in tokens:
        m = date_re.match(t)
        if m:
            day, month = m.group(1), m.group(2)
            year = m.group(3) or str(datetime.now().year)
            if len(year) == 2:
                year = "20" + year
            result["date"] = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        else:
            clean.append(t)

    tokens = clean
    if len(tokens) < 2:
        return None

    # vs separator
    vs_idx = None
    for i, t in enumerate(tokens):
        if t.lower() in ("vs", "v", "contre", "-"):
            vs_idx = i
            break

    if vs_idx is not None:
        result["home"] = " ".join(tokens[:vs_idx]).strip()
        result["away"] = " ".join(tokens[vs_idx+1:]).strip()
    else:
        mid = len(tokens) // 2
        result["home"] = " ".join(tokens[:mid]).strip()
        result["away"] = " ".join(tokens[mid:]).strip()

    if not result["home"] or not result["away"]:
        return None
    return result


def _split_message(text: str, limit: int = 4000) -> list:
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            parts.append(current)
            current = line + "\n"
        else:
            current += line + "\n"
    if current:
        parts.append(current)
    return parts


def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("scan",        cmd_scan))
    app.add_handler(CommandHandler("scan_today",  cmd_scan_today))
    app.add_handler(CommandHandler("scan_1h",     cmd_scan_1h))
    app.add_handler(CommandHandler("scan_3h",     cmd_scan_3h))
    app.add_handler(CommandHandler("scan_6h",     cmd_scan_6h))
    app.add_handler(CommandHandler("scan_12h",    cmd_scan_12h))
    app.add_handler(CommandHandler("scan_48h",    cmd_scan_48h))
    app.add_handler(CommandHandler("stats",       cmd_stats))
    app.add_handler(CommandHandler("history",     cmd_history))
    app.add_handler(CommandHandler("mode",        cmd_mode))
    app.add_handler(CommandHandler("bankroll",    cmd_bankroll))
    app.add_handler(CommandHandler("result",      cmd_result))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app


def run_bot() -> None:
    log.info("APEX OMEGA Bot starting...")
    app = build_app()

    async def post_init(application: Application) -> None:
        cmds = [
            BotCommand("scan",       "Scan 24h"),
            BotCommand("scan_today", "Matchs du jour"),
            BotCommand("scan_1h",    "Urgence 1h"),
            BotCommand("scan_3h",    "Prochaines 3h"),
            BotCommand("scan_6h",    "Prochaines 6h"),
            BotCommand("scan_12h",   "Prochaines 12h"),
            BotCommand("scan_48h",   "Prochaines 48h"),
            BotCommand("stats",      "Stats & Ghost Memory"),
            BotCommand("history",    "10 derniers signaux"),
            BotCommand("mode",       "Safe / Aggressive"),
            BotCommand("bankroll",   "Definir bankroll"),
            BotCommand("result",     "Enregistrer resultat"),
        ]
        await application.bot.set_my_commands(cmds)

    app.post_init = post_init
    app.run_polling(allowed_updates=Update.ALL_TYPES)
