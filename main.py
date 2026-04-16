"""
APEX OMEGA — main.py
Entry point: runs Telegram bot by default, or CLI if args provided.

  python main.py              → Telegram bot (polling)
  python main.py scan 24h     → CLI scan
  python main.py match Arsenal Chelsea
  python main.py report
"""
import sys
import core.logger  # noqa — sets up logging

def main():
    # If CLI args provided, run CLI
    if len(sys.argv) > 1 and sys.argv[1] in ("scan", "match", "report", "history", "result"):
        from interfaces.cli import run_cli
        run_cli(sys.argv[1:])
    else:
        # Default: run Telegram bot
        from interfaces.telegram_bot import run_bot
        run_bot()

if __name__ == "__main__":
    main()
