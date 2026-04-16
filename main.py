"""
APEX OMEGA — main.py
Entry point:
  python main.py              → Telegram bot
  python main.py scan 24h     → CLI
  python main.py match Arsenal Chelsea
  python main.py report
"""
import sys
import os

# ── ensure PYTHONPATH includes project root ─────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core.logger  # noqa — configures logging

import logging
log = logging.getLogger("apex.main")


def main():
    # Initialise database (with path fallback built in)
    try:
        from core.database import init_db
        init_db()
    except Exception as e:
        log.error(f"DB init failed: {e} — continuing anyway")

    # CLI mode if args are recognised subcommands
    cli_cmds = {"scan", "match", "report", "history", "result"}
    if len(sys.argv) > 1 and sys.argv[1] in cli_cmds:
        from interfaces.cli import run_cli
        run_cli(sys.argv[1:])
    else:
        from interfaces.telegram_bot import run_bot
        run_bot()


if __name__ == "__main__":
    main()
