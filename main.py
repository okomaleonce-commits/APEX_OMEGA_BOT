"""
APEX OMEGA — main.py
Entry point:
  python main.py              → Telegram bot (+ health-check HTTP server)
  python main.py scan 24h     → CLI
  python main.py match Arsenal Chelsea
  python main.py report / history / result
"""
import sys
import os
import threading
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── project root on PYTHONPATH ───────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core.logger  # noqa — sets up logging
log = logging.getLogger("apex.main")

PORT = int(os.environ.get("PORT", 10000))  # Render injects $PORT


# ── Minimal health-check HTTP server ─────────────────────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"status":"ok","service":"apex-omega-bot"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # Silence HTTP access logs


def _start_health_server():
    """Run tiny HTTP server in daemon thread so Render sees an open port."""
    try:
        server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
        log.info(f"Health-check server listening on port {PORT}")
        server.serve_forever()
    except Exception as e:
        log.error(f"Health server error: {e}")


def main():
    # ── DB init ──────────────────────────────────────────────────────
    try:
        from core.database import init_db
        init_db()
    except Exception as e:
        log.error(f"DB init failed: {e} — continuing anyway")

    # ── CLI mode ─────────────────────────────────────────────────────
    cli_cmds = {"scan", "match", "report", "history", "result"}
    if len(sys.argv) > 1 and sys.argv[1] in cli_cmds:
        from interfaces.cli import run_cli
        run_cli(sys.argv[1:])
        return

    # ── Bot mode: start health server in background then run bot ─────
    health_thread = threading.Thread(target=_start_health_server, daemon=True)
    health_thread.start()

    from interfaces.telegram_bot import run_bot
    run_bot()


if __name__ == "__main__":
    main()
