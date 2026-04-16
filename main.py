"""
APEX OMEGA — main.py
Entry point.
  - python main.py             → Start Telegram bot
  - python main.py scan 24h    → CLI scan
  - python main.py analyse "Arsenal" "Chelsea" → CLI match analysis
  - python main.py report      → CLI ghost memory report
"""
import sys
import logging

# Must import logger setup first
import core.logger  # noqa: F401

from core.database import init_db

log = logging.getLogger("apex.main")

CLI_COMMANDS = ("scan", "report", "analyse")


def main():
    init_db()

    args = sys.argv[1:]

    if args and args[0].lower() in CLI_COMMANDS:
        # ── CLI mode ─────────────────────────────────────────────
        from interfaces.cli import run_cli
        run_cli(args)
    else:
        # ── Telegram bot mode ─────────────────────────────────────
        from core.config import BOT_TOKEN
        if not BOT_TOKEN:
            log.error("BOT_TOKEN not set — cannot start Telegram bot")
            print("ERROR: BOT_TOKEN environment variable is required.")
            print("Run CLI mode: python main.py scan 24h")
            sys.exit(1)

        log.info("Starting APEX OMEGA Telegram Bot…")
        from interfaces.telegram_bot import run_bot
        run_bot()


if __name__ == "__main__":
    main()
