"""
data_fetcher.py — Fetch BTC candle data from Binance
═════════════════════════════════════════════════════
Fetches 1m, 5m, 30m, 1h candles and aggregates 1m → 2m.
Caches to disk to avoid re-fetching.
"""

import os
import json
import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

from config import BINANCE_BASE_URL, SYMBOL, DATA_CACHE_DIR, BACKTEST_MONTHS

logger = logging.getLogger("bt.data")

CACHE_DIR = Path(__file__).parent / DATA_CACHE_DIR
CACHE_DIR.mkdir(exist_ok=True)


def fetch_klines(symbol: str, interval: str, start_ts: int, end_ts: int,
                 label: str = "") -> list[dict]:
    """
    Fetch klines from Binance public API with pagination.
    Returns list of candle dicts: {t, o, h, l, c, v, ct}
    """
    url = f"{BINANCE_BASE_URL}/klines"
    all_candles = []
    current_start = start_ts

    total_expected = (end_ts - start_ts) / _interval_ms(interval)
    logger.info(f"Fetching {label or interval} — ~{total_expected:.0f} candles expected")

    while current_start < end_ts:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "endTime": end_ts,
            "limit": 1000,
        }

        for attempt in range(5):
            try:
                resp = requests.get(url, params=params, timeout=30)
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 10))
                    logger.warning(f"Rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                logger.warning(f"Fetch attempt {attempt+1} failed: {e}")
                time.sleep(2 ** attempt)
        else:
            logger.error(f"Failed to fetch after 5 attempts at {current_start}")
            break

        if not data:
            break

        for row in data:
            all_candles.append({
                "t": int(row[0]),       # open time ms
                "o": float(row[1]),     # open
                "h": float(row[2]),     # high
                "l": float(row[3]),     # low
                "c": float(row[4]),     # close
                "v": float(row[5]),     # volume
                "ct": int(row[6]),      # close time ms
            })

        current_start = int(data[-1][6]) + 1  # after last close time

        if len(data) < 1000:
            break

        time.sleep(0.15)  # rate limit courtesy

    logger.info(f"  → Fetched {len(all_candles)} {label or interval} candles")
    return all_candles


def _interval_ms(interval: str) -> int:
    """Convert interval string to milliseconds."""
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}
    num = int(interval[:-1])
    unit = interval[-1]
    return num * units.get(unit, 60_000)


def aggregate_1m_to_2m(candles_1m: list[dict]) -> list[dict]:
    """Aggregate 1-minute candles into 2-minute candles."""
    candles_2m = []
    i = 0
    while i + 1 < len(candles_1m):
        c1, c2 = candles_1m[i], candles_1m[i + 1]

        # Verify they are consecutive minutes
        expected_next = c1["t"] + 60_000
        if c2["t"] != expected_next:
            i += 1
            continue

        candles_2m.append({
            "t": c1["t"],
            "o": c1["o"],
            "h": max(c1["h"], c2["h"]),
            "l": min(c1["l"], c2["l"]),
            "c": c2["c"],
            "v": c1["v"] + c2["v"],
            "ct": c2["ct"],
        })
        i += 2

    return candles_2m


def compute_ema(candles: list[dict], period: int) -> list[float]:
    """Compute EMA on close prices. Returns list same length as candles."""
    if not candles:
        return []
    k = 2.0 / (period + 1)
    ema_values = [candles[0]["c"]]  # seed with first close

    for i in range(1, len(candles)):
        new_ema = candles[i]["c"] * k + ema_values[-1] * (1 - k)
        ema_values.append(new_ema)

    return ema_values


def _cache_path(label: str) -> Path:
    return CACHE_DIR / f"{SYMBOL}_{label}.json"


def _save_cache(label: str, data: list[dict]):
    path = _cache_path(label)
    with open(path, "w") as f:
        json.dump(data, f)
    logger.info(f"  → Cached {len(data)} candles → {path.name}")


def _load_cache(label: str) -> list[dict] | None:
    path = _cache_path(label)
    if path.exists():
        with open(path) as f:
            data = json.load(f)
        logger.info(f"  → Loaded {len(data)} candles from cache ({path.name})")
        return data
    return None


def fetch_all_data(force_refresh: bool = False) -> dict:
    """
    Fetch all required data for the backtest.
    Returns dict with keys: candles_2m, candles_5m, candles_30m, candles_1h
    """
    now = datetime.now(timezone.utc)
    end_dt = now.replace(minute=0, second=0, microsecond=0)
    # Extra 60 days for EMA warm-up
    start_dt = end_dt - timedelta(days=BACKTEST_MONTHS * 30 + 60)

    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    result = {}

    # 1. Fetch 1m candles → aggregate to 2m
    cached = None if force_refresh else _load_cache("1m")
    if cached:
        candles_1m = cached
    else:
        candles_1m = fetch_klines(SYMBOL, "1m", start_ms, end_ms, "1m candles")
        _save_cache("1m", candles_1m)

    result["candles_2m"] = aggregate_1m_to_2m(candles_1m)
    logger.info(f"  → Aggregated to {len(result['candles_2m'])} 2m candles")

    # 2. Fetch 5m candles (for outcome verification)
    cached = None if force_refresh else _load_cache("5m")
    if cached:
        result["candles_5m"] = cached
    else:
        result["candles_5m"] = fetch_klines(SYMBOL, "5m", start_ms, end_ms, "5m candles")
        _save_cache("5m", result["candles_5m"])

    # 3. Fetch 30m candles (for EMA 20)
    cached = None if force_refresh else _load_cache("30m")
    if cached:
        result["candles_30m"] = cached
    else:
        result["candles_30m"] = fetch_klines(SYMBOL, "30m", start_ms, end_ms, "30m candles")
        _save_cache("30m", result["candles_30m"])

    # 4. Fetch 1h candles (for EMA 50)
    cached = None if force_refresh else _load_cache("1h")
    if cached:
        result["candles_1h"] = cached
    else:
        result["candles_1h"] = fetch_klines(SYMBOL, "1h", start_ms, end_ms, "1h candles")
        _save_cache("1h", result["candles_1h"])

    logger.info(
        f"\n📊 Data Summary:\n"
        f"   2m candles:  {len(result['candles_2m']):,}\n"
        f"   5m candles:  {len(result['candles_5m']):,}\n"
        f"   30m candles: {len(result['candles_30m']):,}\n"
        f"   1h candles:  {len(result['candles_1h']):,}\n"
        f"   Period: {start_dt.date()} → {end_dt.date()}"
    )

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    data = fetch_all_data()
    print(f"\n✅ Data fetch complete!")
    print(f"   2m: {len(data['candles_2m']):,}")
    print(f"   5m: {len(data['candles_5m']):,}")
    print(f"   30m: {len(data['candles_30m']):,}")
    print(f"   1h: {len(data['candles_1h']):,}")
