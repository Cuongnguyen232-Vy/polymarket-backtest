"""
bot_worker.py — Render.com Worker Entry Point
═══════════════════════════════════════════════
Runs the K9 trading bot in a background thread while serving
a minimal HTTP health endpoint on the Render PORT.

This keeps the Render free-tier service alive (prevents spin-down)
when combined with an external cron pinger like cron-job.org.
═══════════════════════════════════════════════
"""

import os
import sys
import json
import asyncio
import threading
import logging
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# Ensure bot modules are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from db import Database

logger = logging.getLogger("bot_worker")

# ─── Global state ────────────────────────────────────────────
bot_instance = None
bot_started_at = None
bot_thread_alive = False


# ─── Health HTTP Handler ─────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that serves health status."""

    def do_HEAD(self):
        """Handle HEAD requests from monitoring services like UptimeRobot."""
        if self.path in ["/health", "/", "/api/bot-status"]:
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == "/health" or self.path == "/":
            self._respond_health()
        elif self.path == "/api/bot-status":
            self._respond_health()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")

    def _respond_health(self):
        """Return bot health as JSON."""
        try:
            db = Database()
            report = db.get_health_report()
            status_data = {
                "status": "running" if bot_thread_alive else "stopped",
                "started_at": bot_started_at,
                "uptime_seconds": (datetime.now(timezone.utc) - datetime.fromisoformat(bot_started_at)).total_seconds() if bot_started_at else 0,
                "health": report,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
            body = json.dumps(status_data, default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            body = json.dumps({
                "status": "running" if bot_thread_alive else "error",
                "error": str(e),
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }).encode()
            self.wfile.write(body)

    def log_message(self, format, *args):
        """Suppress default HTTP logs to keep output clean."""
        pass


# ─── Bot Thread ──────────────────────────────────────────────

def run_bot_thread():
    """Run the K9 bot in its own thread with its own event loop."""
    global bot_instance, bot_thread_alive

    from bot_main import K9Bot
    import signal as sig

    bot_thread_alive = True
    logger.info("🤖 Bot thread starting...")

    try:
        bot_instance = K9Bot(reset=False)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(bot_instance.run())
        except Exception as e:
            logger.error(f"Bot crashed: {e}", exc_info=True)
            # Log to DB for remote diagnosis
            try:
                db = Database()
                db.log("CRITICAL", "worker", f"Bot crashed and will restart: {e}")
            except:
                pass
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"Bot thread fatal error: {e}", exc_info=True)
    finally:
        bot_thread_alive = False
        logger.warning("⚠️ Bot thread stopped!")


# ─── Main ────────────────────────────────────────────────────

def main():
    global bot_started_at

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    port = int(os.environ.get("PORT", 8080))
    bot_started_at = datetime.now(timezone.utc).isoformat()

    # Start bot in background thread
    bot_thread = threading.Thread(target=run_bot_thread, daemon=True)
    bot_thread.start()
    logger.info("✅ Bot thread launched!")

    # Start HTTP health server (blocks main thread)
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"🌐 Health endpoint listening on port {port}")
    logger.info(f"   Ping /health to keep alive")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
