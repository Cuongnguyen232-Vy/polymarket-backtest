"""
db.py — Neon PostgreSQL Database Layer for 2m Strict Backtest
═════════════════════════════════════════════════════════════
Adapted from K9 bot db.py for backtest result storage.
"""

import os
import json
import psycopg2
import psycopg2.extras
from datetime import datetime, date, timezone
from contextlib import contextmanager

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
except ImportError:
    pass

DATABASE_URL = os.getenv("DATABASE_URL")


class Database:
    """Neon PostgreSQL connection manager for backtest data."""

    def __init__(self, db_url: str = None):
        self.db_url = db_url or DATABASE_URL
        if not self.db_url:
            raise ValueError("DATABASE_URL not set in .env or environment")

    @contextmanager
    def get_conn(self):
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
        with self.get_conn() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                yield cursor
            finally:
                cursor.close()

    # ─── Schema ──────────────────────────────────────────────

    def create_tables(self):
        """Create all tables for backtest storage."""
        with self.get_conn() as conn:
            cur = conn.cursor()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100),
                    start_date DATE,
                    end_date DATE,
                    total_signals INT DEFAULT 0,
                    total_longs INT DEFAULT 0,
                    total_shorts INT DEFAULT 0,
                    win_rate DECIMAL(6,2) DEFAULT 0,
                    long_win_rate DECIMAL(6,2) DEFAULT 0,
                    short_win_rate DECIMAL(6,2) DEFAULT 0,
                    setups_per_week_all DECIMAL(8,2) DEFAULT 0,
                    setups_per_week_ny DECIMAL(8,2) DEFAULT 0,
                    max_dd_80 DECIMAL(8,2) DEFAULT 0,
                    max_dd_82 DECIMAL(8,2) DEFAULT 0,
                    max_dd_85 DECIMAL(8,2) DEFAULT 0,
                    final_pnl_80 DECIMAL(12,2) DEFAULT 0,
                    final_pnl_82 DECIMAL(12,2) DEFAULT 0,
                    final_pnl_85 DECIMAL(12,2) DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id SERIAL PRIMARY KEY,
                    run_id INT REFERENCES backtest_runs(id) ON DELETE CASCADE,
                    signal_time TIMESTAMP WITH TIME ZONE,
                    signal_type VARCHAR(5),
                    btc_price DECIMAL(12,2),
                    candle_open DECIMAL(12,2),
                    candle_close DECIMAL(12,2),
                    candle_volume DECIMAL(18,2),
                    volume_ratio DECIMAL(8,2),
                    body_pct DECIMAL(8,4),
                    ema_30m_20 DECIMAL(12,2),
                    ema_1h_50 DECIMAL(12,2),
                    fivemin_open DECIMAL(12,2),
                    fivemin_close DECIMAL(12,2),
                    fivemin_direction VARCHAR(5),
                    is_win BOOLEAN,
                    pnl_80 DECIMAL(8,2),
                    pnl_82 DECIMAL(8,2),
                    pnl_85 DECIMAL(8,2),
                    is_ny_session BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS bt_daily_summary (
                    id SERIAL PRIMARY KEY,
                    run_id INT REFERENCES backtest_runs(id) ON DELETE CASCADE,
                    date DATE,
                    total_signals INT DEFAULT 0,
                    wins INT DEFAULT 0,
                    losses INT DEFAULT 0,
                    win_rate DECIMAL(6,2) DEFAULT 0,
                    long_signals INT DEFAULT 0,
                    short_signals INT DEFAULT 0,
                    long_wins INT DEFAULT 0,
                    short_wins INT DEFAULT 0,
                    pnl_80 DECIMAL(12,2) DEFAULT 0,
                    pnl_82 DECIMAL(12,2) DEFAULT 0,
                    pnl_85 DECIMAL(12,2) DEFAULT 0,
                    cum_pnl_80 DECIMAL(12,2) DEFAULT 0,
                    cum_pnl_82 DECIMAL(12,2) DEFAULT 0,
                    cum_pnl_85 DECIMAL(12,2) DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """)

            # Indexes
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_signals_run ON signals(run_id);
                CREATE INDEX IF NOT EXISTS idx_signals_time ON signals(signal_time);
                CREATE INDEX IF NOT EXISTS idx_signals_type ON signals(signal_type);
                CREATE INDEX IF NOT EXISTS idx_daily_run ON bt_daily_summary(run_id);
                CREATE INDEX IF NOT EXISTS idx_daily_date ON bt_daily_summary(date);
            """)

            conn.commit()
            print("✅ All backtest tables created")

    def drop_tables(self):
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                DROP TABLE IF EXISTS bt_daily_summary CASCADE;
                DROP TABLE IF EXISTS signals CASCADE;
                DROP TABLE IF EXISTS backtest_runs CASCADE;
            """)
            conn.commit()
            print("🗑️ All tables dropped")

    # ─── Backtest Runs CRUD ──────────────────────────────────

    def insert_backtest_run(self, data: dict) -> int:
        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO backtest_runs (
                    name, start_date, end_date, total_signals,
                    total_longs, total_shorts, win_rate,
                    long_win_rate, short_win_rate,
                    setups_per_week_all, setups_per_week_ny,
                    max_dd_80, max_dd_82, max_dd_85,
                    final_pnl_80, final_pnl_82, final_pnl_85
                ) VALUES (
                    %(name)s, %(start_date)s, %(end_date)s, %(total_signals)s,
                    %(total_longs)s, %(total_shorts)s, %(win_rate)s,
                    %(long_win_rate)s, %(short_win_rate)s,
                    %(setups_per_week_all)s, %(setups_per_week_ny)s,
                    %(max_dd_80)s, %(max_dd_82)s, %(max_dd_85)s,
                    %(final_pnl_80)s, %(final_pnl_82)s, %(final_pnl_85)s
                ) RETURNING id;
            """, data)
            return cur.fetchone()["id"]

    def get_latest_run(self) -> dict:
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT * FROM backtest_runs
                ORDER BY created_at DESC LIMIT 1;
            """)
            return cur.fetchone()

    def get_all_runs(self) -> list:
        with self.get_cursor() as cur:
            cur.execute("SELECT * FROM backtest_runs ORDER BY created_at DESC;")
            return cur.fetchall()

    # ─── Signals CRUD ────────────────────────────────────────

    def insert_signal(self, data: dict):
        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO signals (
                    run_id, signal_time, signal_type, btc_price,
                    candle_open, candle_close, candle_volume,
                    volume_ratio, body_pct, ema_30m_20, ema_1h_50,
                    fivemin_open, fivemin_close, fivemin_direction,
                    is_win, pnl_80, pnl_82, pnl_85, is_ny_session
                ) VALUES (
                    %(run_id)s, %(signal_time)s, %(signal_type)s, %(btc_price)s,
                    %(candle_open)s, %(candle_close)s, %(candle_volume)s,
                    %(volume_ratio)s, %(body_pct)s, %(ema_30m_20)s, %(ema_1h_50)s,
                    %(fivemin_open)s, %(fivemin_close)s, %(fivemin_direction)s,
                    %(is_win)s, %(pnl_80)s, %(pnl_82)s, %(pnl_85)s, %(is_ny_session)s
                );
            """, data)

    def batch_insert_signals(self, signals_list: list[dict]):
        """Batch insert all signals in ONE connection (fast for Neon)."""
        if not signals_list:
            return
        sql = """
            INSERT INTO signals (
                run_id, signal_time, signal_type, btc_price,
                candle_open, candle_close, candle_volume,
                volume_ratio, body_pct, ema_30m_20, ema_1h_50,
                fivemin_open, fivemin_close, fivemin_direction,
                is_win, pnl_80, pnl_82, pnl_85, is_ny_session
            ) VALUES (
                %(run_id)s, %(signal_time)s, %(signal_type)s, %(btc_price)s,
                %(candle_open)s, %(candle_close)s, %(candle_volume)s,
                %(volume_ratio)s, %(body_pct)s, %(ema_30m_20)s, %(ema_1h_50)s,
                %(fivemin_open)s, %(fivemin_close)s, %(fivemin_direction)s,
                %(is_win)s, %(pnl_80)s, %(pnl_82)s, %(pnl_85)s, %(is_ny_session)s
            );
        """
        with self.get_conn() as conn:
            cur = conn.cursor()
            psycopg2.extras.execute_batch(cur, sql, signals_list, page_size=100)
            conn.commit()
            cur.close()

    def get_signals(self, run_id: int, limit: int = 200, offset: int = 0,
                    signal_type: str = None, wins_only: bool = None) -> list:
        with self.get_cursor() as cur:
            query = "SELECT * FROM signals WHERE run_id = %s"
            params = [run_id]

            if signal_type:
                query += " AND signal_type = %s"
                params.append(signal_type)
            if wins_only is not None:
                query += " AND is_win = %s"
                params.append(wins_only)

            query += " ORDER BY signal_time DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            cur.execute(query, params)
            return cur.fetchall()

    def count_signals(self, run_id: int) -> int:
        with self.get_cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM signals WHERE run_id = %s", (run_id,))
            return cur.fetchone()["cnt"]

    # ─── Daily Summary CRUD ──────────────────────────────────

    def insert_daily_summary(self, data: dict):
        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO bt_daily_summary (
                    run_id, date, total_signals, wins, losses, win_rate,
                    long_signals, short_signals, long_wins, short_wins,
                    pnl_80, pnl_82, pnl_85,
                    cum_pnl_80, cum_pnl_82, cum_pnl_85
                ) VALUES (
                    %(run_id)s, %(date)s, %(total_signals)s, %(wins)s, %(losses)s,
                    %(win_rate)s, %(long_signals)s, %(short_signals)s,
                    %(long_wins)s, %(short_wins)s,
                    %(pnl_80)s, %(pnl_82)s, %(pnl_85)s,
                    %(cum_pnl_80)s, %(cum_pnl_82)s, %(cum_pnl_85)s
                );
            """, data)

    def batch_insert_daily_summaries(self, summaries: list[dict]):
        """Batch insert all daily summaries in ONE connection."""
        if not summaries:
            return
        sql = """
            INSERT INTO bt_daily_summary (
                run_id, date, total_signals, wins, losses, win_rate,
                long_signals, short_signals, long_wins, short_wins,
                pnl_80, pnl_82, pnl_85,
                cum_pnl_80, cum_pnl_82, cum_pnl_85
            ) VALUES (
                %(run_id)s, %(date)s, %(total_signals)s, %(wins)s, %(losses)s,
                %(win_rate)s, %(long_signals)s, %(short_signals)s,
                %(long_wins)s, %(short_wins)s,
                %(pnl_80)s, %(pnl_82)s, %(pnl_85)s,
                %(cum_pnl_80)s, %(cum_pnl_82)s, %(cum_pnl_85)s
            );
        """
        with self.get_conn() as conn:
            cur = conn.cursor()
            psycopg2.extras.execute_batch(cur, sql, summaries, page_size=50)
            conn.commit()
            cur.close()

    def get_daily_summaries(self, run_id: int) -> list:
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT * FROM bt_daily_summary
                WHERE run_id = %s ORDER BY date;
            """, (run_id,))
            return cur.fetchall()

    # ─── Stats ───────────────────────────────────────────────

    def get_run_stats(self, run_id: int) -> dict:
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN is_win THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN NOT is_win THEN 1 ELSE 0 END) as losses,
                    SUM(CASE WHEN signal_type = 'LONG' THEN 1 ELSE 0 END) as longs,
                    SUM(CASE WHEN signal_type = 'SHORT' THEN 1 ELSE 0 END) as shorts,
                    SUM(CASE WHEN signal_type = 'LONG' AND is_win THEN 1 ELSE 0 END) as long_wins,
                    SUM(CASE WHEN signal_type = 'SHORT' AND is_win THEN 1 ELSE 0 END) as short_wins,
                    SUM(CASE WHEN is_ny_session THEN 1 ELSE 0 END) as ny_total,
                    SUM(CASE WHEN is_ny_session AND is_win THEN 1 ELSE 0 END) as ny_wins,
                    SUM(pnl_80) as total_pnl_80,
                    SUM(pnl_82) as total_pnl_82,
                    SUM(pnl_85) as total_pnl_85
                FROM signals WHERE run_id = %s;
            """, (run_id,))
            return cur.fetchone()


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
    print("\n🎉 Database ready!")
