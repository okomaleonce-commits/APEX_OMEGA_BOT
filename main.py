"""
APEX OMEGA — main.py
Entry point:
  python main.py              → Telegram bot (+ health-check HTTP server)
  python main.py scan 24h     → CLI
  python main.py match Arsenal Chelsea
  python main.py report / history / result
"""
import sys, os, threading, socket, logging
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core.logger  # noqa
log = logging.getLogger("apex.main")

PORT = int(os.environ.get("PORT", 10000))


class _ReuseHTTPServer(HTTPServer):
    """HTTPServer with SO_REUSEADDR so fast restarts don't hit EADDRINUSE."""
    allow_reuse_address = True


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"status":"ok","service":"apex-omega-bot","version":"1.0"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass  # silence access logs


def _start_health_server():
    """Daemon thread: HTTP health-check server for Render port detection."""
    try:
        server = _ReuseHTTPServer(("0.0.0.0", PORT), _HealthHandler)
        log.info(f"Health-check listening on :{PORT}")
        server.serve_forever()
    except OSError as e:
        log.warning(f"Health server bind error: {e} — port {PORT} may already be in use")
    except Exception as e:
        log.error(f"Health server crashed: {e}")


def main():
    # ── DB ───────────────────────────────────────────────────────────
    try:
        from core.database import init_db
        init_db()
    except Exception as e:
        log.error(f"DB init failed: {e} — continuing")

    # ── CLI ──────────────────────────────────────────────────────────
    if len(sys.argv) > 1 and sys.argv[1] in {"scan","match","report","history","result"}:
        from interfaces.cli import run_cli
        run_cli(sys.argv[1:])
        return

    # ── Health thread (daemon — dies with main) ───────────────────────
    threading.Thread(target=_start_health_server, daemon=True, name="health").start()

    # ── Telegram bot (blocking) ───────────────────────────────────────
    from interfaces.telegram_bot import run_bot
    run_bot()


if __name__ == "__main__":
    main()
