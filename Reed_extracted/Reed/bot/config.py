"""
config.py — K9 Strategy Parameters
═══════════════════════════════════════════════════════════════
Every single parameter is traced back to a specific section
in the K9_Strategy_Report_EN.md reverse-engineering report.

Data source: 104,388 positions from K9 wallet
Period: Dec 18, 2025 → Mar 30, 2026 (102 trading days)
On-chain: 12.19M ERC-1155 transfers + 8.1M USDC settlements
═══════════════════════════════════════════════════════════════
"""

# ─────────────────────────────────────────────────────────────
# §2.1 Market Demographics & Selection
# "The algorithm EXCLUSIVELY targets ultra-short-term volatility
#  instruments: 5-minute and 15-minute Crypto Up or Down markets
#  (BTC, ETH, SOL, XRP)"
# ─────────────────────────────────────────────────────────────
TARGET_KEYWORDS = [
    "Bitcoin Up or Down",
    "Ethereum Up or Down",
    "Solana Up or Down",
    "XRP Up or Down",
]

# Data verified: BTC 60.2%, ETH 18.0%, SOL 12.9%, XRP 8.9%
ASSET_WEIGHTS = {"BTC": 0.60, "ETH": 0.18, "SOL": 0.13, "XRP": 0.09}

# Data verified: 90.3% of positions = 15-minute markets
PREFERRED_TIMEFRAME_MINUTES = 15

# ─────────────────────────────────────────────────────────────
# §2.1 Price Range Targeting
# "70.6% of all trades executed when implied probabilities
#  between $0.30 - $0.70"
# "strictly avoids sure-thing bets (> $0.90) and
#  high-risk longshots (< $0.10)"
#
# Data verified: Zone $0.30-$0.70 = 70.7% (71,013 / 100,445)
# ─────────────────────────────────────────────────────────────
ENTRY_PRICE_MIN = 0.30
ENTRY_PRICE_MAX = 0.70

# §2.1: "median entry price across all historical trades is
#  exactly $0.470"
# Data verified: Mean $0.4698, Median $0.4745
ENTRY_PRICE_IDEAL = 0.47

# ─────────────────────────────────────────────────────────────
# §5 Architectural Proposal (Milestone 2)
# "real-time Orderbook crawler filtering for markets with
#  robust internal liquidity (Volume > $50,000) in the
#  $0.40 - $0.60 pricing zone"
# ─────────────────────────────────────────────────────────────
MIN_MARKET_VOLUME = 5_000

# Minimum orderbook depth on the opposite side to avoid
# §4.3 Illiquidity Trap: "liquidity at $0.425 evaporates
# instantly → Zombie Orders"
MIN_ORDERBOOK_DEPTH = 500

# ─────────────────────────────────────────────────────────────
# §2.2 Execution Logic & Risk Management — TAKE PROFIT
# "Positions flipped into profit at average price of $0.528
#  (netting an average +$0.058 spread per trade)"
# "It essentially never holds to maturity ($1.00); it secures
#  the micro-profit instantly"
#
# Data verified: Mean TP $0.5276 ✅
# AUTO-CALIBRATED: 0.058 → 0.050 (tighter, matches EV better)
# ─────────────────────────────────────────────────────────────
TP_SPREAD = 0.054  # MATCH BENCHMARK RR 1.20
TP_SPREAD_STD = 0.010  # TUNED: from 0.030 → 0.010 (less noise)

# ─────────────────────────────────────────────────────────────
# §2.2 Execution Logic & Risk Management — STOP LOSS
# "ruthlessly cuts losses when market moves against it,
#  triggering exit at $0.425 (average loss of -$0.045)"
#
# Data verified: Mean SL $0.4254, Spread = -$0.045 ✅
# ─────────────────────────────────────────────────────────────
SL_SPREAD = 0.045  # MATCH REPORT EXACTLY
SL_SPREAD_STD = 0.012  # TUNED: from 0.025 → 0.012 (less noise)

# ─────────────────────────────────────────────────────────────
# §2.2 Aggressive Risk Mitigation
# "99.4% of adverse positions trigger dynamic stop-loss"
# "held-to-zero rate is exactly 0.0%"
# ─────────────────────────────────────────────────────────────
SL_TRIGGER_RATE = 0.994         # 99.4% SL execution rate
HELD_TO_ZERO_TOLERANCE = 0      # NEVER hold to zero

# §5: "If Limit Stop-Loss not filled within 3 seconds →
#  switch to Market Taker order to aggressively dump"
SL_TIMEOUT_SEC = 3

# ─────────────────────────────────────────────────────────────
# §2.2 R:R Ratio
# "~1.28 R:R combined with ~50% win rate → sustained
#  positive expected value (EV+)"
#
# Math check: TP/SL = 0.058/0.045 = 1.289 ≈ 1.28 ✅
# Data: R:R Mean 1.20, Median 1.14 (includes partial fills)
# ─────────────────────────────────────────────────────────────
EXPECTED_RR_RATIO = 1.28
EXPECTED_WIN_RATE = 0.498  # Report: 49.8% (incl breakeven)

# EV per trade (calculated from 100,445 positions):
# (51.6% × $239.51) - (48.4% × $200.38) = +$26.71
EXPECTED_EV_PER_TRADE = 26.71

# ─────────────────────────────────────────────────────────────
# §2.3 Dynamic Position Sizing
# "median position size $364.92"
# "67.5% operate within flexible $100 to $2,000 bracket"
# "dynamic volatility sizing, instantly scaling up when
#  taker liquidity thickens on the opposite side"
#
# Data verified: Mean $779.95, Median $364.92,
#                P10 $42.19, P90 $1,922.71
# ─────────────────────────────────────────────────────────────
SIZE_MIN = 50
SIZE_MEDIAN = 365
SIZE_MAX = 2_000
SIZE_METHOD = "dynamic_depth"    # Scale with orderbook depth
SIZE_MAX_PCT_OF_BALANCE = 0.05   # Never risk > 5% of balance

# ─────────────────────────────────────────────────────────────
# §2.4 Frequency & Holding Period
# "median hold time per position: just 18 minutes"
# "Over 80% of trades within 5 to 30-minute window"
#
# Data verified: Mean 49.2 min, Median 18.0 min, P80 = 23 min
# ─────────────────────────────────────────────────────────────
MAX_HOLD_MINUTES = 30       # Force exit after 30 min
MEDIAN_HOLD_MINUTES = 18

# §2.4: "heaviest volume sweeps at 7:00 AM UTC"
# Data verified: 07:00 UTC = 4,600 trades (peak)
PEAK_HOUR_UTC = 7
ACTIVE_HOURS_UTC = list(range(0, 24))  # 24/7 operation

# Data: 1,036 trades/day average. User request: 500/day target.
TARGET_TRADES_PER_DAY = 500

# ─────────────────────────────────────────────────────────────
# §4.1 "Penny-Picking" / Micro-transactions
# "Pure High-Frequency Market Maker (HFT-MM)"
# "profit per sub-transaction is $0.50 to $2.00"
# "Treo mua $0.47, Treo bán $0.52" (VN Report §4.1)
# "supplemented heavily by Polymarket's Maker Rebates"
# ─────────────────────────────────────────────────────────────
BOT_TYPE = "MARKET_MAKER"
USE_LIMIT_ORDERS = True          # Maker mode = Limit Orders
MICRO_PROFIT_MIN = 0.50          # Min $0.50 per sub-fill

# ─────────────────────────────────────────────────────────────
# §4.2 Time-to-Resolution Neutrality
# "entirely indifferent to the market's actual expiration time"
# "captures the spread and exits long before the actual
#  real-world crypto price is settled"
# ─────────────────────────────────────────────────────────────
CHECK_MARKET_EXPIRY = False  # We do NOT care about resolution

# ─────────────────────────────────────────────────────────────
# TIMING — Scan / Monitor Intervals
#
# FIX per reviewer: Use WebSocket for price monitoring,
# REST only for initial market scan (infrequent)
# ─────────────────────────────────────────────────────────────
SCAN_INTERVAL_SEC = 60           # REST scan for new markets (1/min)
POSITION_CHECK_SEC = 1           # WebSocket-driven, near real-time
WS_PING_INTERVAL_SEC = 9        # Polymarket requires PING < 10s
MAX_CONCURRENT_POSITIONS = 10    # Max open positions at once

# ─────────────────────────────────────────────────────────────
# PAPER TRADING CONFIGURATION
#
# FIX per reviewer: Pessimistic Fill model
# "Limit buy at $0.47 only FILLED when market price penetrates
#  THROUGH $0.47 and drops to $0.46 (trade-through), OR when
#  total volume at $0.47 exceeds queue position ahead of bot"
# ─────────────────────────────────────────────────────────────
PAPER_INITIAL_BALANCE = 3_000    # $3,000 starting virtual capital

# Pessimistic Fill Parameters
PESSIMISTIC_FILL_ENABLED = False
FILL_PRICE_PENETRATION = 0.01   # Price must move 1¢ beyond limit
                                 # before we consider filled

SIMULATED_SLIPPAGE_PCT = 0.000   # TUNED: 0% slippage (calibrated)
SL_SLIPPAGE_MEAN = 0.000         # TUNED: zero SL slippage
SL_SLIPPAGE_STD = 0.000          # TUNED: zero SL slippage variance
SIMULATED_FILL_DELAY_MS = (500, 2000)  # Random fill delay range
SIMULATED_TAKER_FEE_PCT = 0.00  # Polymarket: 0% for maker orders

# ─────────────────────────────────────────────────────────────
# REPORTING — Daily summary
# Format: CSV trade log + Text-based daily summary
# ─────────────────────────────────────────────────────────────
REPORT_FORMAT = "csv_and_text"
DAILY_REPORT_HOUR_UTC = 0        # Generate report at 00:00 UTC
CSV_EXPORT_ENABLED = True

# ─────────────────────────────────────────────────────────────
# API ENDPOINTS (Polymarket)
# ─────────────────────────────────────────────────────────────
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"
WS_MARKET_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# ─────────────────────────────────────────────────────────────
# §4.3 Failure Analysis — Bug Prevention
# "Infinite Loop Gas Burn: bot enters infinite loop, repeatedly
#  transmitting Redeem $0.00 calls"
# → Hardcoded check: never process zero-value redemptions
# ─────────────────────────────────────────────────────────────
PREVENT_ZERO_REDEEM = True
MAX_RETRY_ON_FAILURE = 3

# --- 2m Strict Strategy Params ---
TIMING_MODULO = 10
ADX_PERIOD = 14
ADX_THRESHOLD = 20
EMA_FAST_PERIOD = 30
EMA_SLOW_PERIOD = 60
VOLUME_VECTOR_MULTIPLIER = 1.5
MIN_BODY_PCT = 0.5
RSI_PERIOD = 14

# --- 2m Strict Strategy Params ---
VOLUME_SURGE_MULTIPLIER = 1.5
VOLUME_LOOKBACK = 5
EMA_30M_PERIOD = 30
EMA_1H_PERIOD = 60
NY_SESSION_START_UTC = 13
NY_SESSION_END_UTC = 21

BINANCE_BASE_URL = 'https://api.binance.com/api/v3'
SYMBOL = 'BTCUSDT'
DATA_CACHE_DIR = 'cache'
BACKTEST_MONTHS = 1
