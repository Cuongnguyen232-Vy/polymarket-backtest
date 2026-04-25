"""
db.py — Neon PostgreSQL Database Layer
═══════════════════════════════════════════════════════════════
Manages connection to Neon PostgreSQL and provides:
- Schema creation (6 tables)
- CRUD operations for all trading entities
- Daily summary aggregation

Tables:
  1. bot_config      — Runtime configuration key-value store
  2. markets         — Active Polymarket markets (scanned)
  3. trades          — Complete trade log (entry → exit)
  4. positions       — Currently open positions
  5. daily_summary   — Daily PnL aggregation for reports
  6. bot_log         — Activity/error logging
═══════════════════════════════════════════════════════════════
"""

import os
import json
import psycopg2
import psycopg2.extras
from datetime import datetime, date, timezone
from contextlib import contextmanager

# Load .env from project root (optional — Render sets env vars directly)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
except ImportError:
    pass  # dotenv not installed (e.g. on Render), env vars set externally

DATABASE_URL = os.getenv("DATABASE_URL")


class Database:
    """Neon PostgreSQL connection manager with CRUD for all tables."""

    def __init__(self, db_url: str = None):
        self.db_url = db_url or DATABASE_URL
        if not self.db_url:
            raise ValueError("DATABASE_URL not set in .env")
        self._conn = None

    # ─── Connection Management ───────────────────────────────

    @contextmanager
    def get_conn(self):
        """Context manager for database connections with auto-commit."""
        conn = psycopg2.connect(self.db_url)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def get_cursor(self):
        """Context manager for cursor with dict-like rows."""
        with self.get_conn() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                yield cursor
            finally:
                cursor.close()

    # ─── Schema Creation ─────────────────────────────────────

    def create_tables(self):
        """Create all 6 tables if they don't exist."""
        with self.get_conn() as conn:
            cur = conn.cursor()

            # 1. bot_config — key-value runtime configuration
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_config (
                    key VARCHAR(100) PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """)

            # 2. markets — active Polymarket markets from scanner
            cur.execute("""
                CREATE TABLE IF NOT EXISTS markets (
                    id VARCHAR(200) PRIMARY KEY,
                    event_title TEXT,
                    question TEXT,
                    asset VARCHAR(10),
                    timeframe_minutes INT,
                    yes_token_id TEXT,
                    no_token_id TEXT,
                    yes_price DECIMAL(8,4),
                    no_price DECIMAL(8,4),
                    volume DECIMAL(18,2),
                    end_date TIMESTAMP WITH TIME ZONE,
                    orderbook_depth_yes DECIMAL(18,2) DEFAULT 0,
                    orderbook_depth_no DECIMAL(18,2) DEFAULT 0,
                    spread DECIMAL(8,4) DEFAULT 0,
                    scanned_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    is_eligible BOOLEAN DEFAULT FALSE
                );
            """)

            # 3. trades — complete trade lifecycle log
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id SERIAL PRIMARY KEY,
                    market_id VARCHAR(200),
                    market_title TEXT,
                    asset VARCHAR(10),
                    side VARCHAR(3),
                    entry_price DECIMAL(8,4),
                    exit_price DECIMAL(8,4),
                    size_usd DECIMAL(12,2),
                    shares DECIMAL(12,4),
                    pnl DECIMAL(12,2),
                    status VARCHAR(20) DEFAULT 'OPEN',
                    entry_reason TEXT,
                    exit_reason TEXT,
                    tp_target DECIMAL(8,4),
                    sl_target DECIMAL(8,4),
                    entry_time TIMESTAMP WITH TIME ZONE,
                    exit_time TIMESTAMP WITH TIME ZONE,
                    hold_minutes DECIMAL(8,1),
                    fill_type VARCHAR(20) DEFAULT 'PESSIMISTIC',
                    entry_depth_snapshot DECIMAL(18,2),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """)

            # 4. positions — currently open positions
            cur.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id SERIAL PRIMARY KEY,
                    trade_id INT REFERENCES trades(id) ON DELETE CASCADE,
                    market_id VARCHAR(200),
                    yes_token_id TEXT,
                    no_token_id TEXT,
                    side VARCHAR(3),
                    entry_price DECIMAL(8,4),
                    current_price DECIMAL(8,4),
                    size_usd DECIMAL(12,2),
                    shares DECIMAL(12,4),
                    unrealized_pnl DECIMAL(12,2) DEFAULT 0,
                    tp_price DECIMAL(8,4),
                    sl_price DECIMAL(8,4),
                    force_exit_at TIMESTAMP WITH TIME ZONE,
                    status VARCHAR(20) DEFAULT 'OPEN',
                    opened_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """)

            # 5. daily_summary — aggregated daily PnL for reports
            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_summary (
                    date DATE PRIMARY KEY,
                    total_trades INT DEFAULT 0,
                    winners INT DEFAULT 0,
                    losers INT DEFAULT 0,
                    breakeven INT DEFAULT 0,
                    win_rate DECIMAL(6,2) DEFAULT 0,
                    gross_profit DECIMAL(15,2) DEFAULT 0,
                    gross_loss DECIMAL(15,2) DEFAULT 0,
                    net_pnl DECIMAL(15,2) DEFAULT 0,
                    cumulative_pnl DECIMAL(15,2) DEFAULT 0,
                    avg_win DECIMAL(12,2) DEFAULT 0,
                    avg_loss DECIMAL(12,2) DEFAULT 0,
                    rr_ratio DECIMAL(6,2) DEFAULT 0,
                    avg_hold_minutes DECIMAL(8,1) DEFAULT 0,
                    balance DECIMAL(15,2) DEFAULT 0,
                    max_drawdown DECIMAL(12,2) DEFAULT 0,
                    best_trade DECIMAL(12,2) DEFAULT 0,
                    worst_trade DECIMAL(12,2) DEFAULT 0,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """)

            # 6. bot_log — activity and error logging
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_log (
                    id SERIAL PRIMARY KEY,
                    level VARCHAR(10),
                    module VARCHAR(30),
                    message TEXT,
                    data JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """)

            # Create indexes for performance
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_status
                    ON trades(status);
                CREATE INDEX IF NOT EXISTS idx_trades_entry_time
                    ON trades(entry_time);
                CREATE INDEX IF NOT EXISTS idx_trades_market_id
                    ON trades(market_id);
                CREATE INDEX IF NOT EXISTS idx_positions_status
                    ON positions(status);
                CREATE INDEX IF NOT EXISTS idx_bot_log_created
                    ON bot_log(created_at);
                CREATE INDEX IF NOT EXISTS idx_markets_eligible
                    ON markets(is_eligible);
            """)

            conn.commit()
            print("✅ All 6 tables + indexes created successfully")

    def drop_tables(self):
        """Drop all tables (for reset/testing)."""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                DROP TABLE IF EXISTS bot_log CASCADE;
                DROP TABLE IF EXISTS daily_summary CASCADE;
                DROP TABLE IF EXISTS positions CASCADE;
                DROP TABLE IF EXISTS trades CASCADE;
                DROP TABLE IF EXISTS markets CASCADE;
                DROP TABLE IF EXISTS bot_config CASCADE;
            """)
            conn.commit()
            print("🗑️  All tables dropped")

    # ─── Markets CRUD ────────────────────────────────────────

    def upsert_market(self, market: dict):
        """Insert or update a market record."""
        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO markets (
                    id, event_title, question, asset, timeframe_minutes,
                    yes_token_id, no_token_id, yes_price, no_price,
                    volume, end_date, orderbook_depth_yes,
                    orderbook_depth_no, spread, is_eligible, scanned_at
                ) VALUES (
                    %(id)s, %(event_title)s, %(question)s, %(asset)s,
                    %(timeframe_minutes)s, %(yes_token_id)s, %(no_token_id)s,
                    %(yes_price)s, %(no_price)s, %(volume)s, %(end_date)s,
                    %(orderbook_depth_yes)s, %(orderbook_depth_no)s,
                    %(spread)s, %(is_eligible)s, NOW()
                )
                ON CONFLICT (id) DO UPDATE SET
                    yes_price = EXCLUDED.yes_price,
                    no_price = EXCLUDED.no_price,
                    volume = EXCLUDED.volume,
                    orderbook_depth_yes = EXCLUDED.orderbook_depth_yes,
                    orderbook_depth_no = EXCLUDED.orderbook_depth_no,
                    spread = EXCLUDED.spread,
                    is_eligible = EXCLUDED.is_eligible,
                    scanned_at = NOW();
            """, market)

    def get_eligible_markets(self) -> list:
        """Get all markets that passed PolyM filters."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT * FROM markets
                WHERE is_eligible = TRUE
                ORDER BY volume DESC;
            """)
            return cur.fetchall()

    # ─── Trades CRUD ─────────────────────────────────────────

    def insert_trade(self, trade: dict) -> int:
        """Insert a new trade and return its ID."""
        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO trades (
                    market_id, market_title, asset, side,
                    entry_price, size_usd, shares, status,
                    entry_reason, tp_target, sl_target,
                    entry_time, fill_type, entry_depth_snapshot
                ) VALUES (
                    %(market_id)s, %(market_title)s, %(asset)s, %(side)s,
                    %(entry_price)s, %(size_usd)s, %(shares)s, 'OPEN',
                    %(entry_reason)s, %(tp_target)s, %(sl_target)s,
                    %(entry_time)s, %(fill_type)s, %(entry_depth_snapshot)s
                )
                RETURNING id;
            """, trade)
            return cur.fetchone()["id"]

    def close_trade(self, trade_id: int, exit_data: dict):
        """Close a trade with exit details."""
        with self.get_cursor() as cur:
            cur.execute("""
                UPDATE trades SET
                    exit_price = %(exit_price)s,
                    pnl = %(pnl)s,
                    status = %(status)s,
                    exit_reason = %(exit_reason)s,
                    exit_time = %(exit_time)s,
                    hold_minutes = %(hold_minutes)s
                WHERE id = %(trade_id)s;
            """, {**exit_data, "trade_id": trade_id})

    def get_open_trades(self) -> list:
        """Get all trades with status OPEN."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT * FROM trades WHERE status = 'OPEN'
                ORDER BY entry_time;
            """)
            return cur.fetchall()

    def get_trades_for_date(self, target_date: date) -> list:
        """Get all closed trades for a specific date."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT * FROM trades
                WHERE DATE(exit_time) = %s
                  AND status != 'OPEN'
                ORDER BY exit_time;
            """, (target_date,))
            return cur.fetchall()

    def get_all_trades(self) -> list:
        """Get all trades for CSV export."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT * FROM trades ORDER BY entry_time;
            """)
            return cur.fetchall()

    # ─── Positions CRUD ──────────────────────────────────────

    def insert_position(self, position: dict) -> int:
        """Insert a new open position."""
        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO positions (
                    trade_id, market_id, yes_token_id, no_token_id,
                    side, entry_price, current_price, size_usd, shares,
                    tp_price, sl_price, force_exit_at
                ) VALUES (
                    %(trade_id)s, %(market_id)s, %(yes_token_id)s,
                    %(no_token_id)s, %(side)s, %(entry_price)s,
                    %(entry_price)s, %(size_usd)s, %(shares)s,
                    %(tp_price)s, %(sl_price)s, %(force_exit_at)s
                )
                RETURNING id;
            """, position)
            return cur.fetchone()["id"]

    def get_open_positions(self) -> list:
        """Get all currently open positions."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT p.*, t.market_title, t.asset, t.entry_time
                FROM positions p
                JOIN trades t ON p.trade_id = t.id
                WHERE p.status = 'OPEN'
                ORDER BY p.opened_at;
            """)
            return cur.fetchall()

    def update_position_price(self, position_id: int,
                               current_price: float,
                               unrealized_pnl: float):
        """Update current price and unrealized PnL for a position."""
        with self.get_cursor() as cur:
            cur.execute("""
                UPDATE positions SET
                    current_price = %s,
                    unrealized_pnl = %s
                WHERE id = %s;
            """, (current_price, unrealized_pnl, position_id))

    def close_position(self, position_id: int):
        """Mark position as closed."""
        with self.get_cursor() as cur:
            cur.execute("""
                UPDATE positions SET status = 'CLOSED'
                WHERE id = %s;
            """, (position_id,))

    def has_position_for_market(self, market_id: str) -> bool:
        """Check if there's already an open position for this market."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) as cnt FROM positions
                WHERE market_id = %s AND status = 'OPEN';
            """, (market_id,))
            return cur.fetchone()["cnt"] > 0

    def count_open_positions(self) -> int:
        """Count total open positions."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) as cnt FROM positions
                WHERE status = 'OPEN';
            """)
            return cur.fetchone()["cnt"]

    # ─── Daily Summary ───────────────────────────────────────

    def update_daily_summary(self, target_date: date, balance: float):
        """
        Aggregate all closed trades for a date into daily_summary.
        Called at end of each trading day or on demand.
        """
        with self.get_cursor() as cur:
            # Get all closed trades for this date
            cur.execute("""
                SELECT
                    COUNT(*) as total_trades,
                    COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) as winners,
                    COALESCE(SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END), 0) as losers,
                    COALESCE(SUM(CASE WHEN pnl = 0 THEN 1 ELSE 0 END), 0) as breakeven,
                    COALESCE(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 0) as gross_profit,
                    COALESCE(SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END), 0) as gross_loss,
                    COALESCE(SUM(pnl), 0) as net_pnl,
                    COALESCE(AVG(CASE WHEN pnl > 0 THEN pnl END), 0) as avg_win,
                    COALESCE(AVG(CASE WHEN pnl < 0 THEN ABS(pnl) END), 0) as avg_loss,
                    COALESCE(AVG(hold_minutes), 0) as avg_hold_minutes,
                    COALESCE(MAX(pnl), 0) as best_trade,
                    COALESCE(MIN(pnl), 0) as worst_trade
                FROM trades
                WHERE DATE(exit_time) = %s
                  AND status != 'OPEN';
            """, (target_date,))
            stats = cur.fetchone()

            # Calculate derived metrics
            total = stats["total_trades"] or 0
            wins = stats["winners"] or 0
            losses = stats["losers"] or 0
            avg_win = float(stats["avg_win"] or 0)
            avg_loss = float(stats["avg_loss"] or 0)

            win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
            rr_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0

            # Get cumulative PnL
            cur.execute("""
                SELECT COALESCE(SUM(net_pnl), 0) as cum_pnl
                FROM daily_summary
                WHERE date < %s;
            """, (target_date,))
            prev_cum = float(cur.fetchone()["cum_pnl"])
            cumulative_pnl = prev_cum + float(stats["net_pnl"] or 0)

            # Upsert daily summary
            cur.execute("""
                INSERT INTO daily_summary (
                    date, total_trades, winners, losers, breakeven,
                    win_rate, gross_profit, gross_loss, net_pnl,
                    cumulative_pnl, avg_win, avg_loss, rr_ratio,
                    avg_hold_minutes, balance, best_trade, worst_trade,
                    updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, NOW()
                )
                ON CONFLICT (date) DO UPDATE SET
                    total_trades = EXCLUDED.total_trades,
                    winners = EXCLUDED.winners,
                    losers = EXCLUDED.losers,
                    breakeven = EXCLUDED.breakeven,
                    win_rate = EXCLUDED.win_rate,
                    gross_profit = EXCLUDED.gross_profit,
                    gross_loss = EXCLUDED.gross_loss,
                    net_pnl = EXCLUDED.net_pnl,
                    cumulative_pnl = EXCLUDED.cumulative_pnl,
                    avg_win = EXCLUDED.avg_win,
                    avg_loss = EXCLUDED.avg_loss,
                    rr_ratio = EXCLUDED.rr_ratio,
                    avg_hold_minutes = EXCLUDED.avg_hold_minutes,
                    balance = EXCLUDED.balance,
                    best_trade = EXCLUDED.best_trade,
                    worst_trade = EXCLUDED.worst_trade,
                    updated_at = NOW();
            """, (
                target_date, total, wins, losses, stats["breakeven"],
                win_rate, stats["gross_profit"], stats["gross_loss"],
                stats["net_pnl"], cumulative_pnl, avg_win, avg_loss,
                rr_ratio, stats["avg_hold_minutes"], balance,
                stats["best_trade"], stats["worst_trade"]
            ))

    def get_daily_summaries(self) -> list:
        """Get all daily summaries for reporting."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT * FROM daily_summary ORDER BY date;
            """)
            return cur.fetchall()

    def get_latest_summary(self) -> dict:
        """Get the most recent daily summary."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT * FROM daily_summary
                ORDER BY date DESC LIMIT 1;
            """)
            return cur.fetchone()

    # ─── Bot Log ─────────────────────────────────────────────

    def log(self, level: str, module: str, message: str,
            data: dict = None):
        """Insert a log entry."""
        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO bot_log (level, module, message, data)
                VALUES (%s, %s, %s, %s);
            """, (level, module, message,
                  json.dumps(data) if data else None))

    def get_recent_logs(self, level: str = None, limit: int = 100):
        """Get recent log entries, optionally filtered by level."""
        with self.get_cursor() as cur:
            if level:
                cur.execute("""
                    SELECT id, level, module, message, data, created_at
                    FROM bot_log
                    WHERE level = %s
                    ORDER BY created_at DESC
                    LIMIT %s;
                """, (level.upper(), limit))
            else:
                cur.execute("""
                    SELECT id, level, module, message, data, created_at
                    FROM bot_log
                    ORDER BY created_at DESC
                    LIMIT %s;
                """, (limit,))
            return cur.fetchall()

    def get_health_report(self):
        """Generate a health summary for remote diagnosis."""
        report = {}
        with self.get_cursor() as cur:
            # Last heartbeat / any log
            cur.execute("""
                SELECT created_at FROM bot_log
                ORDER BY created_at DESC LIMIT 1;
            """)
            row = cur.fetchone()
            report["last_activity"] = row["created_at"].isoformat() if row else None

            # Error count last 24h
            cur.execute("""
                SELECT COUNT(*) as cnt FROM bot_log
                WHERE level IN ('ERROR', 'CRITICAL')
                AND created_at > NOW() - INTERVAL '24 hours';
            """)
            report["errors_24h"] = int(cur.fetchone()["cnt"])

            # Warning count last 24h
            cur.execute("""
                SELECT COUNT(*) as cnt FROM bot_log
                WHERE level = 'WARNING'
                AND created_at > NOW() - INTERVAL '24 hours';
            """)
            report["warnings_24h"] = int(cur.fetchone()["cnt"])

            # Recent errors (last 10)
            cur.execute("""
                SELECT level, module, message, data, created_at
                FROM bot_log
                WHERE level IN ('ERROR', 'CRITICAL', 'WARNING')
                ORDER BY created_at DESC LIMIT 10;
            """)
            report["recent_issues"] = cur.fetchall()

            # Total logs last 24h
            cur.execute("""
                SELECT COUNT(*) as cnt FROM bot_log
                WHERE created_at > NOW() - INTERVAL '24 hours';
            """)
            report["total_logs_24h"] = int(cur.fetchone()["cnt"])

        return report

    # ─── Bot Config ──────────────────────────────────────────

    def set_config(self, key: str, value: str):
        """Set a runtime config value."""
        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO bot_config (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_at = NOW();
            """, (key, value))

    def get_config(self, key: str, default: str = None) -> str:
        """Get a runtime config value."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT value FROM bot_config WHERE key = %s;
            """, (key,))
            row = cur.fetchone()
            return row["value"] if row else default

    # ─── Stats / Utility ─────────────────────────────────────

    def get_stats(self) -> dict:
        """Get overall bot statistics."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT
                    (SELECT COUNT(*) FROM trades) as total_trades,
                    (SELECT COUNT(*) FROM trades WHERE status = 'OPEN') as open_trades,
                    (SELECT COUNT(*) FROM trades WHERE status != 'OPEN') as closed_trades,
                    (SELECT COUNT(*) FROM positions WHERE status = 'OPEN') as open_positions,
                    (SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE status != 'OPEN') as total_pnl,
                    (SELECT COUNT(*) FROM markets WHERE is_eligible = TRUE) as eligible_markets;
            """)
            return cur.fetchone()

    def count_trades_today(self) -> dict:
        """
        Count trades entered TODAY (UTC) — used to restore
        _daily_trade_count after Render restarts.

        Returns:
            {"total": int, "wins": int, "losses": int}
        """
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total,
                    COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) as wins,
                    COALESCE(SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END), 0) as losses
                FROM trades
                WHERE DATE(entry_time AT TIME ZONE 'UTC') = (NOW() AT TIME ZONE 'UTC')::date;
            """)
            row = cur.fetchone()
            return {
                "total": int(row["total"]),
                "wins": int(row["wins"]),
                "losses": int(row["losses"]),
            }


# ─── Quick Test ──────────────────────────────────────────────

if __name__ == "__main__":
    db = Database()

    print("🔌 Testing Neon PostgreSQL connection...")
    with db.get_cursor() as cur:
        cur.execute("SELECT version();")
        version = cur.fetchone()
        print(f"✅ Connected: {list(version.values())[0][:60]}")

    print("\n📦 Creating tables...")
    db.create_tables()

    print("\n📊 Testing CRUD operations...")
    db.set_config("bot_started_at", datetime.now(timezone.utc).isoformat())
    started = db.get_config("bot_started_at")
    print(f"✅ Config set/get: bot_started_at = {started}")

    db.log("INFO", "db_test", "Database initialization test successful")
    print("✅ Log entry created")

    stats = db.get_stats()
    print(f"✅ Stats: {dict(stats)}")

    print("\n🎉 Database layer fully operational!")
