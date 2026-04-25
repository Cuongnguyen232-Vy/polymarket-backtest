"""
config.py — 2m Strict Strategy Parameters
═══════════════════════════════════════════
All parameters for the "2m Strict" Polymarket BTC backtest.
"""

# ─── Strategy Rules ──────────────────────────────────────────
STRATEGY_NAME = "2m Strict — First 2m of Every 5m Bar + Dual EMA Filter"

# Timing: first 2m candle of each 5m window
# 5m windows start at :00, :05, :10, ...
# First 2m candle opens at :00, :05, :10, ... (minute % 5 == 0)
TIMING_MODULO = 5  # minutes

# Volume Vector: current volume >= 200% of avg(10 previous candles)
VOLUME_SURGE_MULTIPLIER = 2.0
VOLUME_LOOKBACK = 10

# Full-Bodied: body >= 0.08% of close price
MIN_BODY_PCT = 0.0008  # 0.08%

# EMA Trend Filter
EMA_30M_PERIOD = 20   # 20 EMA on 30-minute chart
EMA_1H_PERIOD = 50    # 50 EMA on 1-hour chart

# ─── Backtest Parameters ─────────────────────────────────────
BACKTEST_MONTHS = 12
BET_SIZE_USD = 100  # Fixed $100 per trade

# Fill price sensitivity test (Polymarket contract prices)
FILL_PRICES = [0.80, 0.82, 0.85]

# NY Session hours (EST = UTC-5, EDT = UTC-4)
# Approximate: 9:30 AM - 4:00 PM ET → 13:30 - 20:00 UTC (EDT)
NY_SESSION_START_UTC = 13  # hour
NY_SESSION_END_UTC = 20    # hour

# Starting balance for drawdown calculation
INITIAL_BALANCE = 10_000

# ─── Data Source ──────────────────────────────────────────────
BINANCE_BASE_URL = "https://api.binance.com"
SYMBOL = "BTCUSDT"
DATA_CACHE_DIR = "cache"

# ─── Database ────────────────────────────────────────────────
# Set via DATABASE_URL environment variable

# ─── API Server ──────────────────────────────────────────────
DEFAULT_PORT = 5050
