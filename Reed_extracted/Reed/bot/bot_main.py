"""
bot_main.py — PolyM Paper Trading Bot Orchestrator
═══════════════════════════════════════════════════════════════
Main entry point. Runs all modules concurrently:

1. Market Scanner    → REST scan every 60s for new markets  
2. Strategy Engine   → Evaluates signals per market
3. Paper Executor    → Executes paper trades, tracks PnL
4. Position Monitor  → WebSocket price feed + exit checks
5. Daily Reporter    → Auto-generates report at 00:00 UTC

Reviewer Fixes Applied:
  #1: WebSocket for price monitoring (not REST polling)
  #2: Pessimistic fill model for limit order simulation

Usage:
  python bot_main.py          # Run normally
  python bot_main.py --reset  # Reset DB and start fresh
═══════════════════════════════════════════════════════════════
"""

import dns_bypass  # Bypass DNS nhà mạng VN

import sys
import json
import asyncio
import logging
import signal as sig
from datetime import datetime, timezone, timedelta

from config import (
    SCAN_INTERVAL_SEC, POSITION_CHECK_SEC,
    TARGET_TRADES_PER_DAY, MAX_CONCURRENT_POSITIONS,
    PAPER_INITIAL_BALANCE, DAILY_REPORT_HOUR_UTC,
    WS_MARKET_URL, WS_PING_INTERVAL_SEC,
    CLOB_API_BASE,
)
from db import Database
from market_scanner import MarketScanner
from strategy_engine import StrategyEngine
from paper_executor import PaperExecutor

# ─── Logging Setup ───────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-12s] %(levelname)-5s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("PolyM_bot.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("PolyM.main")


class PolyMBot:
    """
    PolyM Paper Trading Bot — Main Orchestrator.
    
    Coordinates all modules in an async event loop:
    - scan_loop: Find new eligible markets (REST, 1/min)
    - monitor_loop: Check positions for exit (every second)
    - price_feed: WebSocket connection for live prices
    - report_loop: Daily report generation at 00:00 UTC
    """

    def __init__(self, reset: bool = False):
        self.db = Database()
        self._running = False
        self._tasks: list[asyncio.Task] = []

        # Reset DB if requested
        if reset:
            logger.warning("🗑️  Resetting database...")
            self.db.drop_tables()

        # Init tables
        self.db.create_tables()

        # Init modules
        self.scanner = MarketScanner(self.db)
        self.strategy = StrategyEngine(self.db)

        # Restore balance from DB or start fresh
        saved_balance = self.db.get_config("balance")
        initial = float(saved_balance) if saved_balance else PAPER_INITIAL_BALANCE
        self.executor = PaperExecutor(self.db, self.strategy, initial)

        # Track subscribed tokens for WebSocket
        self._subscribed_tokens: set[str] = set()

        logger.info("=" * 60)
        logger.info("  PolyM PAPER TRADING BOT — INITIALIZED")
        logger.info(f"  Balance: ${self.executor.balance:,.2f}")
        logger.info(f"  Target: {TARGET_TRADES_PER_DAY} trades/day")
        logger.info(f"  Max positions: {MAX_CONCURRENT_POSITIONS}")
        logger.info("=" * 60)

    # ─── Main Run ────────────────────────────────────────────

    async def run(self):
        """Start all async loops."""
        self._running = True

        self.db.log("INFO", "main", "Bot started", {
            "balance": self.executor.balance,
            "target_trades": TARGET_TRADES_PER_DAY,
        })

        # Create concurrent tasks
        self._tasks = [
            asyncio.create_task(self._scan_loop(), name="scanner"),
            asyncio.create_task(self._monitor_loop(), name="monitor"),
            asyncio.create_task(self._report_loop(), name="reporter"),
            asyncio.create_task(self._stats_loop(), name="stats"),
        ]

        logger.info("🚀 All loops started. Bot is running 24/7.")
        logger.info("   Press Ctrl+C to stop gracefully.\n")

        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            logger.info("Tasks cancelled, shutting down...")

    async def stop(self):
        """Graceful shutdown."""
        self._running = False
        logger.info("\n⏹  Stopping bot...")

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Close scanner session
        await self.scanner.close()

        # Generate final daily summary
        today = datetime.now(timezone.utc).date()
        await self.executor.generate_daily_summary(today)

        # Export final CSV
        self.executor.export_trades_csv()

        # Log shutdown
        self.db.log("INFO", "main", "Bot stopped", {
            "balance": self.executor.balance,
            "total_trades": self.executor.total_trades,
        })

        stats = self.db.get_stats()
        logger.info(f"\n📊 Final Stats:")
        logger.info(f"   Total trades: {stats['total_trades']}")
        logger.info(f"   Total PnL:    ${float(stats['total_pnl']):+,.2f}")
        logger.info(f"   Balance:      ${self.executor.balance:,.2f}")
        logger.info(f"\n✅ Bot stopped cleanly.")

    # ─── Scan Loop (REST, 1/min) ─────────────────────────────

    async def _scan_loop(self):
        """
        Periodically scan for new eligible markets.
        REST API only, once per minute (avoids rate limits).
        
        Daily capacity gate: stops entering new trades once
        the day's target trade count is reached (matching PolyM's
        daily return percentage on the equity curve).
        """
        while self._running:
            try:
                # Check if we've hit today's trade target
                if not self.executor.has_daily_capacity():
                    logger.debug("Daily trade target reached, waiting...")
                    await asyncio.sleep(SCAN_INTERVAL_SEC)
                    continue

                markets = await self.scanner.scan_markets()

                for market in markets:
                    # Re-check capacity between trades
                    if not self.executor.has_daily_capacity():
                        break

                    # Fetch orderbooks for strategy evaluation
                    ob_yes = await self.scanner._fetch_orderbook(
                        market.yes_token_id
                    )
                    ob_no = await self.scanner._fetch_orderbook(
                        market.no_token_id
                    )

                    if not ob_yes or not ob_no:
                        continue

                    # Ask strategy engine for a signal
                    signal = self.strategy.evaluate(
                        market, ob_yes, ob_no, self.executor.balance
                    )

                    if signal:
                        # Execute paper trade
                        trade_id = await self.executor.execute_entry(signal)

                        if trade_id:
                            # Record trade time for pacing
                            self.executor.record_trade_done()

                            # Add tokens to WebSocket subscription
                            self._subscribed_tokens.add(market.yes_token_id)
                            self._subscribed_tokens.add(market.no_token_id)

                    # Small delay between market evaluations
                    await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"Scan loop error: {e}", exc_info=True)
                self.db.log("ERROR", "scanner", f"Scan loop error: {e}", {
                    "traceback": str(e)
                })

            # Wait before next scan
            await asyncio.sleep(SCAN_INTERVAL_SEC)

    # ─── Monitor Loop (Frequent, Price-Driven) ───────────────

    async def _monitor_loop(self):
        """
        Monitor open positions for exit conditions.
        
        Uses 2 parallel approaches:
        1. WebSocket price feed (preferred, real-time)
        2. REST fallback (if WS disconnected, every 10s)
        """
        ws_task = None

        while self._running:
            try:
                # Start WebSocket if we have tokens to monitor
                if self._subscribed_tokens and not self.executor._ws_connected:
                    if ws_task is None or ws_task.done():
                        ws_task = asyncio.create_task(
                            self.executor.start_price_feed(
                                list(self._subscribed_tokens)
                            )
                        )

                # Check positions for exit
                await self.executor.monitor_positions()

                # Check pending pessimistic fills
                await self.executor.check_pending_fills()

                # If WebSocket is down, fetch prices via REST
                if not self.executor._ws_connected:
                    await self._rest_price_fallback()

            except Exception as e:
                logger.error(f"Monitor loop error: {e}", exc_info=True)
                self.db.log("ERROR", "monitor", f"Monitor loop error: {e}", {
                    "traceback": str(e)
                })

            await asyncio.sleep(POSITION_CHECK_SEC)

    async def _rest_price_fallback(self):
        """
        Fallback: fetch prices via REST when WebSocket is down.
        Only called when WS is disconnected.
        """
        positions = self.db.get_open_positions()

        for pos in positions:
            token_id = (
                pos["yes_token_id"]
                if pos["side"] == "YES"
                else pos["no_token_id"]
            )

            try:
                await self.scanner._ensure_session()
                url = f"{CLOB_API_BASE}/price"
                params = {"token_id": token_id}

                async with self.scanner.session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        price = float(data.get("price", 0))
                        if price > 0:
                            self.executor.update_price(token_id, price)

            except Exception as e:
                self.db.log("WARNING", "monitor", f"REST price fetch failed: {e}", {
                    "market_id": pos.get("market_id", "unknown")
                })

            # Rate limit REST calls
            await asyncio.sleep(1)

    # ─── Report Loop (Daily at 00:00 UTC) ────────────────────

    async def _report_loop(self):
        """Generate daily report at 00:00 UTC."""
        while self._running:
            now = datetime.now(timezone.utc)

            # Calculate seconds until next report time
            next_report = now.replace(
                hour=DAILY_REPORT_HOUR_UTC,
                minute=0, second=0, microsecond=0
            )
            if now >= next_report:
                next_report += timedelta(days=1)

            wait_seconds = (next_report - now).total_seconds()
            logger.info(
                f"📅 Next daily report in "
                f"{wait_seconds/3600:.1f} hours "
                f"({next_report.strftime('%Y-%m-%d %H:%M UTC')})"
            )

            await asyncio.sleep(min(wait_seconds, 3600))

            # Check if it's time
            now = datetime.now(timezone.utc)
            if now.hour == DAILY_REPORT_HOUR_UTC and now.minute < 5:
                yesterday = (now - timedelta(days=1)).date()
                await self.executor.generate_daily_summary(yesterday)

                report = self.executor.get_daily_report_text(yesterday)
                logger.info(f"\n{report}")

                # Export CSV
                self.executor.export_trades_csv()

                # Wait to avoid duplicate triggers
                await asyncio.sleep(360)

    # ─── Stats Loop (Console Heartbeat) ──────────────────────

    async def _stats_loop(self):
        """Print periodic stats to console + log to DB."""
        while self._running:
            await asyncio.sleep(300)  # Every 5 minutes

            try:
                stats = self.db.get_stats()
                open_pos = stats["open_positions"]
                total_pnl = float(stats["total_pnl"])

                logger.info(
                    f"💓 Heartbeat | Balance: ${self.executor.balance:,.2f} "
                    f"| PnL: ${total_pnl:+,.2f} "
                    f"| Trades: {stats['total_trades']} "
                    f"| Open: {open_pos} "
                    f"| WS: {'🟢' if self.executor._ws_connected else '🔴'}"
                )

                # Log heartbeat to DB so we can check remotely
                self.db.log("HEARTBEAT", "main", "Bot alive", {
                    "balance": self.executor.balance,
                    "total_pnl": total_pnl,
                    "total_trades": stats["total_trades"],
                    "open_positions": open_pos,
                    "ws_connected": self.executor._ws_connected,
                    "eligible_markets": stats.get("eligible_markets", 0),
                    "daily_trades": self.executor._daily_trade_count,
                    "daily_target": "uncapped",
                    "daily_remaining": "unlimited",
                })
            except Exception as e:
                logger.error(f"Stats loop error: {e}")
                self.db.log("ERROR", "main", f"Stats loop error: {e}")


# ─── Entry Point ─────────────────────────────────────────────

def main():
    """CLI entry point."""
    reset = "--reset" in sys.argv

    if reset:
        confirm = input(
            "⚠️  This will DELETE all trading data. Continue? (y/N): "
        )
        if confirm.lower() != "y":
            print("Cancelled.")
            return

    bot = PolyMBot(reset=reset)

    # Handle Ctrl+C gracefully
    loop = asyncio.new_event_loop()

    def handle_signal():
        loop.create_task(bot.stop())

    try:
        for s in (sig.SIGINT, sig.SIGTERM):
            loop.add_signal_handler(s, handle_signal)
    except NotImplementedError:
        # Windows doesn't support add_signal_handler
        pass

    try:
        loop.run_until_complete(bot.run())
    except KeyboardInterrupt:
        loop.run_until_complete(bot.stop())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
