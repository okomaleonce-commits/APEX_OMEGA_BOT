"""
APEX OMEGA — interfaces/telegram_bot.py
Full Telegram bot with commands + natural language match analysis.
Commands: /start /scan /scan_today /stats /mode /help
NLP: "PSG Lens 25/04" | "EPL Arsenal Chelsea demain"
"""
import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ParseMode

from core.config import BOT_TOKEN, CHAT_ID, BANKROLL, LEAGUES
from core.database import init_db
from scanner.scan_engine import run_scan, analyse_single_match
from decisions.rationale_builder import (
    format_verdict_telegram, format_scan_summary_telegram,
    format_stats_telegram
)
from storage.signals_repo import get_ghost_stats, get_recent_signals

log = logging.getLogger("apex.telegram")

# ── BOT STATE (in-memory) ──────────────────────────────────────
_state = {
    "mode": "safe",
    "bankroll": BANKROLL,
    "scanning": False,
}

MAX_MESSAGE_LEN = 4000


# ── COMMAND HANDLERS ──────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("🔍 Scan 24h",    callback_data="scan_24"),
         InlineKeyboardButton("📅 Scan Aujourd'hui", callback_data="scan_today")],
        [InlineKeyboardButton("📊 Stats",        callback_data="stats"),
         InlineKeyboardButton("⚙️ Mode",         callback_data="mode_toggle")],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🤖 *APEX OMEGA — Bot de Paris Sportif*\n\n"
        "Moteur Dixon\\-Coles \\+ Ghost Signal Memory \\+ Trust Matrix\n\n"
        "*Commandes disponibles :*\n"
        "`/scan` — Scan 24h\n"
        "`/scan today` — Scan du jour\n"
        "`/scan 1h` — Urgence \\(prochaine heure\\)\n"
        "`/scan 3h` — 3 heures\n"
        "`/scan 6h` — 6 heures\n"
        "`/stats` — Statistiques\n"
        "`/mode` — Basculer Safe/Aggressive\n"
        "`/help` — Aide\n\n"
        "*Analyse directe :*\n"
        "`Arsenal Chelsea` — Analyse ce match\n"
        "`EPL Arsenal Chelsea 26/04` — Avec ligue et date",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=markup
    )


async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /scan, /scan today, /scan Nh"""
    args = ctx.args or []
    arg  = " ".join(args).strip().lower()

    if _state["scanning"]:
        await update.message.reply_text("⏳ Scan déjà en cours, veuillez patienter…")
        return

    hours = _parse_scan_arg(arg)
    await _do_scan(update, ctx, hours=hours, label=arg or "24h")


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ Chargement des statistiques…")
    ghost   = get_ghost_stats()
    recents = get_recent_signals(10)
    text    = format_stats_telegram(ghost, recents)
    await _send_long(update, text)


async def cmd_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    current = _state["mode"]
    new_mode = "aggressive" if current == "safe" else "safe"
    _state["mode"] = new_mode
    icon = "🔥" if new_mode == "aggressive" else "🛡️"
    await update.message.reply_text(
        f"{icon} Mode basculé : *{new_mode.upper()}*\n\n"
        f"{'Seuils edge réduits — plus de signaux' if new_mode == 'aggressive' else 'Seuils edge stricts — signaux premium uniquement'}",
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 *APEX OMEGA — Aide*\n\n"
        "*Commandes scan :*\n"
        "`/scan` — Prochaines 24h toutes ligues\n"
        "`/scan today` — Matchs d'aujourd'hui\n"
        "`/scan 1h` — Urgence \\(1 heure\\)\n"
        "`/scan 2h` à `/scan 12h` — Fenêtre personnalisée\n\n"
        "*Analyse directe \\(message libre\\) :*\n"
        "`Arsenal Chelsea` — Recherche et analyse\n"
        "`EPL Arsenal Chelsea 26/04` — Ligue \\+ date\n"
        "`Champions League PSG Bayern` — Toutes infos\n\n"
        "*Lecture des signaux :*\n"
        "🚀 BET — Pari validé \\(edge ✅, cote ✅, confiance ✅\\)\n"
        "📡 SIGNAL — Signal pur \\(cote hors plage BET\\)\n"
        "⛔ NO BET — Critères non remplis\n"
        "🚫 REJECT — Trust/DCS insuffisant\n"
        "👻 Ghost — Signal bloqué par la mémoire des pertes",
        parse_mode=ParseMode.MARKDOWN_V2
    )


# ── NATURAL LANGUAGE MESSAGE HANDLER ──────────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Parse free-text messages for match queries.
    Formats: "Arsenal Chelsea", "EPL Arsenal Chelsea 26/04", "PSG Bayern 2h"
    """
    text = update.message.text.strip()
    if not text:
        return

    # Check if it looks like a scan command variant
    text_lower = text.lower()
    if text_lower.startswith("scan"):
        hours = _parse_scan_arg(text_lower.replace("scan", "").strip())
        await _do_scan(update, ctx, hours=hours, label=f"{hours}h")
        return

    # Parse as match query
    parsed = _parse_match_query(text)
    if not parsed:
        await update.message.reply_text(
            "❓ Format non reconnu\\. Essayez :\n"
            "`Arsenal Chelsea` ou\n"
            "`EPL Arsenal Chelsea 26/04`\n"
            "ou `/scan` pour un scan complet",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    team_home   = parsed["team_home"]
    team_away   = parsed["team_away"]
    match_date  = parsed.get("date")
    league_id   = parsed.get("league_id")

    await update.message.reply_text(
        f"🔍 Analyse de *{team_home}* vs *{team_away}*…",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    try:
        verdict = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: analyse_single_match(
                team_home, team_away, match_date, league_id,
                mode=_state["mode"], bankroll=_state["bankroll"]
            )
        )
        text_out = format_verdict_telegram(verdict)
        await _send_long(update, text_out)
    except Exception as e:
        log.error(f"Analysis error: {e}")
        await update.message.reply_text(f"❌ Erreur d'analyse : `{str(e)[:100]}`",
                                         parse_mode=ParseMode.MARKDOWN_V2)


# ── INLINE KEYBOARD CALLBACKS ─────────────────────────────────

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "scan_24":
        await _do_scan(update, ctx, hours=24, label="24h", via_callback=True)
    elif data == "scan_today":
        from datetime import datetime
        now = datetime.now()
        remaining = 24 - now.hour
        await _do_scan(update, ctx, hours=max(1, remaining), label="aujourd'hui", via_callback=True)
    elif data == "stats":
        ghost   = get_ghost_stats()
        recents = get_recent_signals(10)
        text    = format_stats_telegram(ghost, recents)
        await _send_long_callback(query, text)
    elif data == "mode_toggle":
        current  = _state["mode"]
        new_mode = "aggressive" if current == "safe" else "safe"
        _state["mode"] = new_mode
        icon = "🔥" if new_mode == "aggressive" else "🛡️"
        await query.edit_message_text(
            f"{icon} Mode : *{new_mode.upper()}*",
            parse_mode=ParseMode.MARKDOWN_V2
        )


# ── INTERNAL SCAN RUNNER ──────────────────────────────────────

async def _do_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                   hours: int = 24, label: str = "24h",
                   via_callback: bool = False) -> None:
    _state["scanning"] = True
    msg_target = update.callback_query.message if via_callback else update.message

    status_msg = await msg_target.reply_text(
        f"⏳ Scan en cours \\(horizon: *{label}* | mode: *{_state['mode'].upper()}*\\)…",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    try:
        scan_result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: run_scan(
                hours_ahead=hours,
                mode=_state["mode"],
                bankroll=_state["bankroll"]
            )
        )

        # Send summary first
        summary = format_scan_summary_telegram(scan_result)
        await status_msg.edit_text(summary, parse_mode=ParseMode.MARKDOWN_V2)

        # Send each signal as individual message
        for verdict in scan_result.get("signals", []):
            try:
                detail = format_verdict_telegram(verdict)
                await msg_target.reply_text(detail, parse_mode=ParseMode.MARKDOWN_V2)
                await asyncio.sleep(0.5)  # rate limit guard
            except Exception as e:
                log.error(f"Signal message error: {e}")

    except Exception as e:
        log.error(f"Scan error: {e}")
        await status_msg.edit_text(f"❌ Erreur scan : `{str(e)[:200]}`",
                                    parse_mode=ParseMode.MARKDOWN_V2)
    finally:
        _state["scanning"] = False


# ── HELPERS ───────────────────────────────────────────────────

def _parse_scan_arg(arg: str) -> int:
    """Parse scan arg → hours. '1h' → 1, 'today' → remaining hours, '' → 24."""
    if not arg or arg in ("", "24h", "24"):
        return 24
    if arg in ("today", "aujourd'hui", "auj"):
        now = datetime.now()
        return max(1, 24 - now.hour)
    m = re.match(r"(\d+)\s*h", arg)
    if m:
        return max(1, min(int(m.group(1)), 168))
    try:
        return int(arg)
    except ValueError:
        return 24


def _parse_match_query(text: str) -> Optional[dict]:
    """
    Parse natural-language match query.
    Extracts: team_home, team_away, optional date (dd/mm), optional league keyword.
    Examples:
      "Arsenal Chelsea"
      "PSG Lens 26/04"
      "Champions League Real Madrid Bayern 25/04"
    """
    # Remove date if present
    date_match = re.search(r"\b(\d{1,2})[/\-\.](\d{1,2})(?:[/\-\.](\d{2,4}))?\b", text)
    date_str = None
    if date_match:
        day, month = date_match.group(1), date_match.group(2)
        year = date_match.group(3) or str(datetime.now().year)
        if len(year) == 2:
            year = "20" + year
        date_str = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        text = text[:date_match.start()] + text[date_match.end():]

    # Detect league keyword
    league_id = None
    league_keywords = {
        "epl": 39, "premier league": 39, "pl": 39,
        "liga": 140, "la liga": 140,
        "bundesliga": 78, "bl": 78,
        "serie a": 135, "seriea": 135,
        "ligue 1": 61, "ligue1": 61, "l1": 61,
        "champions": 2, "ucl": 2, "cl": 2,
        "europa": 3, "uel": 3,
        "conference": 848, "uecl": 848,
    }

    text_clean = text.strip()
    for kw, lid in league_keywords.items():
        if kw in text_clean.lower():
            league_id = lid
            text_clean = re.sub(kw, "", text_clean, flags=re.IGNORECASE).strip()
            break

    # Remaining text = team names
    # Split by common separators or "vs"/"contre"
    parts = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s+contre\s+", text_clean, flags=re.IGNORECASE)
    if len(parts) >= 2:
        return {
            "team_home": parts[0].strip(),
            "team_away": parts[1].strip(),
            "date": date_str,
            "league_id": league_id,
        }

    # Try splitting on 2+ consecutive caps words (team names)
    words = text_clean.split()
    if len(words) >= 2:
        mid = len(words) // 2
        return {
            "team_home": " ".join(words[:mid]),
            "team_away": " ".join(words[mid:]),
            "date": date_str,
            "league_id": league_id,
        }

    return None


async def _send_long(update: Update, text: str) -> None:
    """Split long messages to respect Telegram 4096 char limit."""
    chunks = _split_message(text)
    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as e:
            # Try plain text fallback
            plain = re.sub(r"[\\*`_\[\]]", "", chunk)
            try:
                await update.message.reply_text(plain[:4096])
            except Exception:
                log.error(f"Message send error: {e}")


async def _send_long_callback(query, text: str) -> None:
    chunks = _split_message(text)
    for i, chunk in enumerate(chunks):
        try:
            if i == 0:
                await query.edit_message_text(chunk, parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await query.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as e:
            log.error(f"Callback message error: {e}")


def _split_message(text: str, max_len: int = MAX_MESSAGE_LEN) -> list[str]:
    """Split message at newlines respecting max length."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            if current:
                chunks.append(current)
            current = line
        else:
            current = (current + "\n" + line) if current else line
    if current:
        chunks.append(current)
    return chunks


# ── BOT LAUNCHER ──────────────────────────────────────────────

def run_bot() -> None:
    """Start the Telegram bot (blocking)."""
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("scan",   cmd_scan))
    app.add_handler(CommandHandler("stats",  cmd_stats))
    app.add_handler(CommandHandler("mode",   cmd_mode))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("🤖 APEX OMEGA Telegram Bot started")
    app.run_polling(drop_pending_updates=True)
