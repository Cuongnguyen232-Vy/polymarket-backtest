"""
backtester_phase1.py — PolyM Phase 1 Backtest
═══════════════════════════════════════════════
Backtest chiến lược 2m Strict trên 12 tháng dữ liệu Binance.
Báo cáo đầy đủ 6 chỉ số theo yêu cầu Task_phase_1.txt
"""

import dns_bypass  # Bypass DNS nhà mạng VN

import json
import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("backtest")

# ═══════════════════════════════════════════════════════════════
# BƯỚC 1: Tải dữ liệu nến từ Binance
# ═══════════════════════════════════════════════════════════════

BINANCE_URL = "https://api.binance.com/api/v3/klines"
CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

def fetch_klines(symbol, interval, start_ms, end_ms, label=""):
    """Tải nến từ Binance với phân trang."""
    all_candles = []
    current = start_ms
    
    while current < end_ms:
        for attempt in range(5):
            try:
                resp = requests.get(BINANCE_URL, params={
                    "symbol": symbol, "interval": interval,
                    "startTime": current, "endTime": end_ms, "limit": 1000
                }, timeout=30)
                if resp.status_code == 429:
                    time.sleep(10)
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                time.sleep(2 ** attempt)
        else:
            break
        
        if not data:
            break
        
        for row in data:
            all_candles.append({
                "t": int(row[0]), "o": float(row[1]), "h": float(row[2]),
                "l": float(row[3]), "c": float(row[4]), "v": float(row[5]),
                "ct": int(row[6])
            })
        
        current = int(data[-1][6]) + 1
        if len(data) < 1000:
            break
        time.sleep(0.15)
    
    logger.info(f"  Fetched {len(all_candles)} {label} candles")
    return all_candles

def aggregate_1m_to_2m(candles_1m):
    """Ghép 2 nến 1m thành 1 nến 2m."""
    candles_2m = []
    i = 0
    while i + 1 < len(candles_1m):
        c1, c2 = candles_1m[i], candles_1m[i + 1]
        if c2["t"] != c1["t"] + 60_000:
            i += 1
            continue
        candles_2m.append({
            "t": c1["t"], "o": c1["o"], "h": max(c1["h"], c2["h"]),
            "l": min(c1["l"], c2["l"]), "c": c2["c"],
            "v": c1["v"] + c2["v"], "ct": c2["ct"]
        })
        i += 2
    return candles_2m

def compute_ema(candles, period):
    """Tính EMA trên giá đóng cửa."""
    if not candles:
        return []
    k = 2.0 / (period + 1)
    ema = [candles[0]["c"]]
    for i in range(1, len(candles)):
        ema.append(candles[i]["c"] * k + ema[-1] * (1 - k))
    return ema

# ═══════════════════════════════════════════════════════════════
# BƯỚC 2: Chiến lược 2m Strict (5 bộ lọc)
# ═══════════════════════════════════════════════════════════════

TIMING_MODULO = 10
VOLUME_LOOKBACK = 10
VOLUME_MULTIPLIER = 2.0
MIN_BODY_PCT = 0.0008
EMA_30M_PERIOD = 20
EMA_1H_PERIOD = 50
NY_START_UTC = 13
NY_END_UTC = 21

def run_strategy(candles_2m, candles_5m, ema_30m_lookup, ema_1h_lookup):
    """Chạy chiến lược 2m Strict, trả về danh sách tín hiệu."""
    import bisect
    
    ema_30m_times = sorted(ema_30m_lookup.keys())
    ema_1h_times = sorted(ema_1h_lookup.keys())
    
    signals = []
    
    # Tạo lookup nến 5m: mỗi nến 2m thuộc nến 5m nào
    candle_5m_lookup = {}
    for c5 in candles_5m:
        candle_5m_lookup[c5["t"]] = c5
    
    for i in range(VOLUME_LOOKBACK, len(candles_2m)):
        candle = candles_2m[i]
        dt = datetime.fromtimestamp(candle["t"] / 1000, tz=timezone.utc)
        
        # ── Bộ lọc 1: THỜI GIAN ──
        if dt.minute % TIMING_MODULO != 0:
            continue
        
        # ── Bộ lọc 2: VOLUME SURGE ──
        prev_vols = [candles_2m[i - j]["v"] for j in range(1, VOLUME_LOOKBACK + 1)]
        avg_vol = sum(prev_vols) / len(prev_vols) if prev_vols else 0
        if avg_vol <= 0:
            continue
        vol_ratio = candle["v"] / avg_vol
        if vol_ratio < VOLUME_MULTIPLIER:
            continue
        
        # ── Bộ lọc 3: THÂN NẾN ĐẦY ──
        body = abs(candle["c"] - candle["o"])
        body_pct = body / candle["c"] if candle["c"] > 0 else 0
        if body_pct < MIN_BODY_PCT:
            continue
        
        # ── Bộ lọc 4: HƯỚNG ──
        if candle["c"] > candle["o"]:
            direction = "LONG"
        elif candle["c"] < candle["o"]:
            direction = "SHORT"
        else:
            continue
        
        # ── Bộ lọc 5: EMA TREND ──
        idx_30m = bisect.bisect_right(ema_30m_times, candle["t"]) - 1
        idx_1h = bisect.bisect_right(ema_1h_times, candle["t"]) - 1
        if idx_30m < 0 or idx_1h < 0:
            continue
        
        ema_30m = ema_30m_lookup[ema_30m_times[idx_30m]]
        ema_1h = ema_1h_lookup[ema_1h_times[idx_1h]]
        price = candle["c"]
        
        if direction == "LONG" and not (price > ema_30m and price > ema_1h):
            continue
        if direction == "SHORT" and not (price < ema_30m and price < ema_1h):
            continue
        
        # ✅ CẢ 5 BỘ LỌC ĐỀU QUA → Tín hiệu!
        
        # Tìm nến 5m tương ứng để xác định WIN/LOSE
        # Nến 5m bắt đầu tại: phút chia hết cho 5
        five_min_start = candle["t"] - (dt.minute % 5) * 60_000
        candle_5m = candle_5m_lookup.get(five_min_start)
        
        if candle_5m is None:
            # Tìm nến 5m gần nhất
            for offset in range(0, 300_000, 60_000):
                c5 = candle_5m_lookup.get(five_min_start + offset)
                if c5:
                    candle_5m = c5
                    break
        
        if candle_5m is None:
            continue
        
        # Xác định kết quả: nến 5m đóng cùng hướng = WIN
        five_min_direction = "UP" if candle_5m["c"] > candle_5m["o"] else "DOWN"
        
        if direction == "LONG":
            win = five_min_direction == "UP"
        else:
            win = five_min_direction == "DOWN"
        
        is_ny = NY_START_UTC <= dt.hour < NY_END_UTC
        
        signals.append({
            "timestamp": candle["t"],
            "datetime": dt.isoformat(),
            "direction": direction,
            "price": price,
            "vol_ratio": round(vol_ratio, 2),
            "body_pct": round(body_pct, 6),
            "win": win,
            "is_ny_session": is_ny,
            "ema_30m": round(ema_30m, 2),
            "ema_1h": round(ema_1h, 2),
        })
    
    return signals

# ═══════════════════════════════════════════════════════════════
# BƯỚC 3: Tính toán metrics & Equity Curve
# ═══════════════════════════════════════════════════════════════

def calculate_metrics(signals, fill_price=0.80):
    """Tính tất cả 6 chỉ số Phase 1."""
    if not signals:
        return {}
    
    # Tách LONG/SHORT
    longs = [s for s in signals if s["direction"] == "LONG"]
    shorts = [s for s in signals if s["direction"] == "SHORT"]
    ny_signals = [s for s in signals if s["is_ny_session"]]
    
    # Win rates
    total_wins = sum(1 for s in signals if s["win"])
    long_wins = sum(1 for s in longs if s["win"])
    short_wins = sum(1 for s in shorts if s["win"])
    
    overall_wr = total_wins / len(signals) * 100 if signals else 0
    long_wr = long_wins / len(longs) * 100 if longs else 0
    short_wr = short_wins / len(shorts) * 100 if shorts else 0
    
    # Setups per week
    if signals:
        first_ts = signals[0]["timestamp"]
        last_ts = signals[-1]["timestamp"]
        weeks = max(1, (last_ts - first_ts) / (7 * 24 * 3600 * 1000))
        setups_per_week_all = len(signals) / weeks
        setups_per_week_ny = len(ny_signals) / weeks
    else:
        setups_per_week_all = 0
        setups_per_week_ny = 0
    
    # Equity curve & Max Drawdown
    balance = 10_000.0
    bet_size = 100.0
    peak = balance
    max_dd = 0
    equity_curve = [balance]
    
    for s in signals:
        if s["win"]:
            pnl = bet_size * (1.0 - fill_price) / fill_price  # lãi
        else:
            pnl = -bet_size  # mất hết tiền cược
        
        balance += pnl
        equity_curve.append(balance)
        
        if balance > peak:
            peak = balance
        dd = (peak - balance) / peak * 100
        if dd > max_dd:
            max_dd = dd
    
    return {
        "fill_price": fill_price,
        "total_signals": len(signals),
        "long_signals": len(longs),
        "short_signals": len(shorts),
        "overall_win_rate": round(overall_wr, 1),
        "long_win_rate": round(long_wr, 1),
        "short_win_rate": round(short_wr, 1),
        "setups_per_week_24_7": round(setups_per_week_all, 1),
        "setups_per_week_ny": round(setups_per_week_ny, 1),
        "max_drawdown_pct": round(max_dd, 2),
        "final_balance": round(balance, 2),
        "total_pnl": round(balance - 10_000, 2),
        "ny_signals": len(ny_signals),
    }

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 65)
    print("  PolyM Phase 1 — BACKTEST 2m Strict Strategy")
    print("  12 tháng dữ liệu BTCUSDT từ Binance")
    print("=" * 65)
    
    now = datetime.now(timezone.utc)
    end_dt = now.replace(minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=365)
    # Extra warmup for EMAs
    warmup_dt = start_dt - timedelta(days=60)
    
    start_ms = int(warmup_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    
    print(f"\n📅 Period: {start_dt.date()} → {end_dt.date()}")
    print(f"   Warmup from: {warmup_dt.date()}")
    
    # ── Cache check ──
    cache_file = CACHE_DIR / "backtest_1m_12mo.json"
    
    if cache_file.exists():
        print(f"\n📂 Loading from cache...")
        with open(cache_file) as f:
            cached = json.load(f)
        candles_1m = cached["candles_1m"]
        candles_30m = cached["candles_30m"]
        candles_1h = cached["candles_1h"]
        candles_5m = cached["candles_5m"]
        print(f"   1m: {len(candles_1m):,} | 5m: {len(candles_5m):,} | 30m: {len(candles_30m):,} | 1h: {len(candles_1h):,}")
    else:
        print(f"\n📡 Fetching data from Binance (this takes a few minutes)...")
        candles_1m = fetch_klines("BTCUSDT", "1m", start_ms, end_ms, "1m")
        candles_5m = fetch_klines("BTCUSDT", "5m", start_ms, end_ms, "5m")
        candles_30m = fetch_klines("BTCUSDT", "30m", start_ms, end_ms, "30m")
        candles_1h = fetch_klines("BTCUSDT", "1h", start_ms, end_ms, "1h")
        
        print(f"\n💾 Saving cache...")
        with open(cache_file, "w") as f:
            json.dump({
                "candles_1m": candles_1m, "candles_5m": candles_5m,
                "candles_30m": candles_30m, "candles_1h": candles_1h
            }, f)
    
    # ── Aggregate ──
    print(f"\n🔧 Aggregating 1m → 2m...")
    candles_2m = aggregate_1m_to_2m(candles_1m)
    print(f"   2m candles: {len(candles_2m):,}")
    
    # ── EMA lookups ──
    print(f"🔧 Computing EMAs...")
    ema_30m_values = compute_ema(candles_30m, EMA_30M_PERIOD)
    ema_1h_values = compute_ema(candles_1h, EMA_1H_PERIOD)
    
    ema_30m_lookup = {candles_30m[i]["t"]: ema_30m_values[i] for i in range(len(candles_30m))}
    ema_1h_lookup = {candles_1h[i]["t"]: ema_1h_values[i] for i in range(len(candles_1h))}
    
    # ── Run strategy ──
    print(f"\n🧠 Running 2m Strict strategy...")
    signals = run_strategy(candles_2m, candles_5m, ema_30m_lookup, ema_1h_lookup)
    print(f"   Total signals: {len(signals)}")
    
    # ── Calculate metrics at 3 fill prices ──
    print(f"\n{'=' * 65}")
    print(f"  BÁO CÁO BACKTEST PHASE 1")
    print(f"{'=' * 65}")
    
    for fill in [0.80, 0.82, 0.85]:
        m = calculate_metrics(signals, fill_price=fill)
        
        print(f"\n{'─' * 65}")
        print(f"  Giá khớp lệnh: {fill*100:.0f}¢")
        print(f"{'─' * 65}")
        print(f"  Tổng tín hiệu:          {m['total_signals']}")
        print(f"    LONG:                  {m['long_signals']}")
        print(f"    SHORT:                 {m['short_signals']}")
        print(f"")
        print(f"  ✅ Overall Win Rate:     {m['overall_win_rate']}%")
        print(f"  ✅ LONG Win Rate:        {m['long_win_rate']}%")
        print(f"  ✅ SHORT Win Rate:       {m['short_win_rate']}%")
        print(f"")
        print(f"  ✅ Setups/week (24/7):   {m['setups_per_week_24_7']}")
        print(f"  ✅ Setups/week (NY):     {m['setups_per_week_ny']}")
        print(f"")
        print(f"  ✅ Max Drawdown:         {m['max_drawdown_pct']}%")
        print(f"")
        print(f"  Final Balance:           ${m['final_balance']:,.2f}")
        print(f"  Total PnL:              ${m['total_pnl']:+,.2f}")
    
    print(f"\n{'=' * 65}")
    print(f"  ✅ PHASE 1 BACKTEST HOÀN TẤT")
    print(f"{'=' * 65}")
