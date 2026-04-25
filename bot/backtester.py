"""
backtester.py — Run 2m Strict Strategy Backtest
════════════════════════════════════════════════
Runs strategy on 12 months of BTC data and calculates
all metrics required by the task brief.
"""

import logging
import statistics
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from dataclasses import dataclass, asdict

from config import (
    FILL_PRICES, BET_SIZE_USD, INITIAL_BALANCE,
    NY_SESSION_START_UTC, NY_SESSION_END_UTC, BACKTEST_MONTHS,
)
from data_fetcher import fetch_all_data
from strategy import Strategy2mStrict, Signal

logger = logging.getLogger("bt.backtest")


@dataclass
class TradeResult:
    """Result of a single trade."""
    signal: Signal
    fivemin_open: float
    fivemin_close: float
    fivemin_direction: str   # "UP" or "DOWN"
    is_win: bool
    pnl_80: float
    pnl_82: float
    pnl_85: float


def _calc_pnl(is_win: bool, fill_price: float, bet_size: float = BET_SIZE_USD) -> float:
    """
    Calculate PnL for a Polymarket binary trade.
    Buy contracts at fill_price. If win → $1.00, if lose → $0.00.
    Win profit = bet_size * (1 - fill_price) / fill_price
    Lose loss  = -bet_size
    """
    if is_win:
        return round(bet_size * (1.0 - fill_price) / fill_price, 2)
    else:
        return round(-bet_size, 2)


def run_backtest(db=None, force_refresh: bool = False) -> dict:
    """
    Main backtest function.
    
    Returns dict with all metrics required by task brief.
    """
    logger.info("=" * 60)
    logger.info("  2m STRICT STRATEGY — BACKTEST START")
    logger.info("=" * 60)

    # ── Step 1: Fetch data ──
    logger.info("\n📥 Step 1: Fetching data from Binance...")
    data = fetch_all_data(force_refresh=force_refresh)

    candles_2m = data["candles_2m"]
    candles_5m = data["candles_5m"]
    candles_30m = data["candles_30m"]
    candles_1h = data["candles_1h"]

    # Build 5m candle lookup: open_time_ms → candle
    fivemin_lookup = {c["t"]: c for c in candles_5m}

    # ── Step 2: Initialize strategy ──
    logger.info("\n🧠 Step 2: Initializing strategy engine...")
    strategy = Strategy2mStrict(candles_30m, candles_1h)

    # ── Step 3: Determine backtest window ──
    # Skip first 60 days (EMA warm-up) and use remaining as backtest period
    if not candles_2m:
        logger.error("No 2m candle data!")
        return {}

    all_start_ms = candles_2m[0]["t"]
    all_end_ms = candles_2m[-1]["t"]
    warmup_ms = 60 * 24 * 3600 * 1000  # 60 days in ms
    backtest_start_ms = all_start_ms + warmup_ms

    backtest_start_dt = datetime.fromtimestamp(backtest_start_ms / 1000, tz=timezone.utc)
    backtest_end_dt = datetime.fromtimestamp(all_end_ms / 1000, tz=timezone.utc)

    logger.info(f"   Backtest window: {backtest_start_dt.date()} → {backtest_end_dt.date()}")
    logger.info(f"   ({(backtest_end_dt - backtest_start_dt).days} days)")

    # ── Step 4: Run strategy on each candle ──
    logger.info("\n🔍 Step 3: Scanning for signals...")
    signals: list[Signal] = []
    trades: list[TradeResult] = []

    for i in range(len(candles_2m)):
        candle = candles_2m[i]
        if candle["t"] < backtest_start_ms:
            continue

        signal = strategy.evaluate(candles_2m, i)
        if signal is None:
            continue

        signals.append(signal)

        # ── Find corresponding 5m candle ──
        # The 2m candle opens at the start of a 5m window
        # So the 5m candle has the same open time
        fivemin = fivemin_lookup.get(signal.timestamp_ms)
        if fivemin is None:
            continue

        # Determine 5m direction
        if fivemin["c"] > fivemin["o"]:
            fivemin_dir = "UP"
        elif fivemin["c"] < fivemin["o"]:
            fivemin_dir = "DOWN"
        else:
            fivemin_dir = "FLAT"

        # Determine win/loss
        is_win = (
            (signal.signal_type == "LONG" and fivemin_dir == "UP") or
            (signal.signal_type == "SHORT" and fivemin_dir == "DOWN")
        )

        trade = TradeResult(
            signal=signal,
            fivemin_open=fivemin["o"],
            fivemin_close=fivemin["c"],
            fivemin_direction=fivemin_dir,
            is_win=is_win,
            pnl_80=_calc_pnl(is_win, 0.80),
            pnl_82=_calc_pnl(is_win, 0.82),
            pnl_85=_calc_pnl(is_win, 0.85),
        )
        trades.append(trade)

    logger.info(f"   → {len(signals)} signals generated")
    logger.info(f"   → {len(trades)} trades evaluated")

    if not trades:
        logger.warning("No trades found!")
        return {"error": "No trades found in backtest period"}

    # ── Step 5: Calculate metrics ──
    logger.info("\n📊 Step 4: Calculating metrics...")
    metrics = _calculate_metrics(trades, backtest_start_dt, backtest_end_dt)

    # ── Step 6: Store results in DB ──
    if db:
        logger.info("\n💾 Step 5: Storing results in database...")
        _store_results(db, metrics, trades)

    # ── Step 7: Print report ──
    report = _format_report(metrics)
    logger.info(report)

    return metrics


def _calculate_metrics(trades: list[TradeResult],
                       start_dt: datetime, end_dt: datetime) -> dict:
    """Calculate all metrics required by the task brief."""
    total = len(trades)
    wins = [t for t in trades if t.is_win]
    losses = [t for t in trades if not t.is_win]

    longs = [t for t in trades if t.signal.signal_type == "LONG"]
    shorts = [t for t in trades if t.signal.signal_type == "SHORT"]
    long_wins = [t for t in longs if t.is_win]
    short_wins = [t for t in shorts if t.is_win]

    ny_trades = [t for t in trades if t.signal.is_ny_session]
    ny_wins = [t for t in ny_trades if t.is_win]

    # Win rates
    win_rate = len(wins) / total * 100 if total > 0 else 0
    long_wr = len(long_wins) / len(longs) * 100 if longs else 0
    short_wr = len(short_wins) / len(shorts) * 100 if shorts else 0
    ny_wr = len(ny_wins) / len(ny_trades) * 100 if ny_trades else 0

    # Setups per week
    days = max((end_dt - start_dt).days, 1)
    weeks = days / 7
    setups_per_week_24_7 = total / weeks if weeks > 0 else 0
    setups_per_week_ny = len(ny_trades) / weeks if weeks > 0 else 0

    # PnL and drawdown for each fill price
    fill_results = {}
    for fp in FILL_PRICES:
        fp_key = str(int(fp * 100))
        pnl_list = [_calc_pnl(t.is_win, fp) for t in trades]
        cumulative = []
        running = 0
        peak = 0
        max_dd = 0
        max_dd_pct = 0

        for p in pnl_list:
            running += p
            cumulative.append(running)
            if running > peak:
                peak = running
            dd = peak - running
            if dd > max_dd:
                max_dd = dd
            balance_here = INITIAL_BALANCE + running
            peak_balance = INITIAL_BALANCE + peak
            dd_pct = dd / peak_balance * 100 if peak_balance > 0 else 0
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

        fill_results[fp_key] = {
            "fill_price": fp,
            "total_pnl": round(running, 2),
            "final_balance": round(INITIAL_BALANCE + running, 2),
            "roi_pct": round(running / INITIAL_BALANCE * 100, 2),
            "max_drawdown_usd": round(max_dd, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "cumulative_pnl": cumulative,
        }

    # Daily breakdown
    daily = defaultdict(lambda: {"total": 0, "wins": 0, "longs": 0,
                                  "shorts": 0, "long_wins": 0, "short_wins": 0,
                                  "pnl_80": 0, "pnl_82": 0, "pnl_85": 0})
    for t in trades:
        dt = datetime.fromtimestamp(t.signal.timestamp_ms / 1000, tz=timezone.utc)
        d = dt.strftime("%Y-%m-%d")
        daily[d]["total"] += 1
        if t.is_win:
            daily[d]["wins"] += 1
        if t.signal.signal_type == "LONG":
            daily[d]["longs"] += 1
            if t.is_win:
                daily[d]["long_wins"] += 1
        else:
            daily[d]["shorts"] += 1
            if t.is_win:
                daily[d]["short_wins"] += 1
        daily[d]["pnl_80"] += t.pnl_80
        daily[d]["pnl_82"] += t.pnl_82
        daily[d]["pnl_85"] += t.pnl_85

    # Weekly breakdown
    weekly = defaultdict(lambda: {"total": 0, "wins": 0, "ny_total": 0})
    for t in trades:
        dt = datetime.fromtimestamp(t.signal.timestamp_ms / 1000, tz=timezone.utc)
        week = dt.strftime("%Y-W%U")
        weekly[week]["total"] += 1
        if t.is_win:
            weekly[week]["wins"] += 1
        if t.signal.is_ny_session:
            weekly[week]["ny_total"] += 1

    return {
        "strategy": "2m Strict",
        "period_start": start_dt.isoformat(),
        "period_end": end_dt.isoformat(),
        "period_days": (end_dt - start_dt).days,
        "total_signals": total,
        "total_longs": len(longs),
        "total_shorts": len(shorts),
        "total_wins": len(wins),
        "total_losses": len(losses),
        "win_rate": round(win_rate, 2),
        "long_win_rate": round(long_wr, 2),
        "short_win_rate": round(short_wr, 2),
        "ny_session_trades": len(ny_trades),
        "ny_session_win_rate": round(ny_wr, 2),
        "setups_per_week_24_7": round(setups_per_week_24_7, 1),
        "setups_per_week_ny": round(setups_per_week_ny, 1),
        "fill_results": fill_results,
        "daily": dict(daily),
        "weekly": dict(weekly),
        "initial_balance": INITIAL_BALANCE,
        "bet_size": BET_SIZE_USD,
        "trades_data": [
            {
                "time": t.signal.timestamp_ms,
                "type": t.signal.signal_type,
                "btc_price": t.signal.candle_close,
                "vol_ratio": t.signal.volume_ratio,
                "body_pct": t.signal.body_pct,
                "ema_30m": t.signal.ema_30m_20,
                "ema_1h": t.signal.ema_1h_50,
                "fivemin_dir": t.fivemin_direction,
                "is_win": t.is_win,
                "is_ny": t.signal.is_ny_session,
                "pnl_80": t.pnl_80,
                "pnl_82": t.pnl_82,
                "pnl_85": t.pnl_85,
            }
            for t in trades
        ],
    }


def _store_results(db, metrics: dict, trades: list[TradeResult]):
    """Store backtest results in Neon PostgreSQL."""
    try:
        fr = metrics["fill_results"]
        run_id = db.insert_backtest_run({
            "name": metrics["strategy"],
            "start_date": metrics["period_start"][:10],
            "end_date": metrics["period_end"][:10],
            "total_signals": metrics["total_signals"],
            "total_longs": metrics["total_longs"],
            "total_shorts": metrics["total_shorts"],
            "win_rate": metrics["win_rate"],
            "long_win_rate": metrics["long_win_rate"],
            "short_win_rate": metrics["short_win_rate"],
            "setups_per_week_all": metrics["setups_per_week_24_7"],
            "setups_per_week_ny": metrics["setups_per_week_ny"],
            "max_dd_80": fr["80"]["max_drawdown_pct"],
            "max_dd_82": fr["82"]["max_drawdown_pct"],
            "max_dd_85": fr["85"]["max_drawdown_pct"],
            "final_pnl_80": fr["80"]["total_pnl"],
            "final_pnl_82": fr["82"]["total_pnl"],
            "final_pnl_85": fr["85"]["total_pnl"],
        })

        # Store individual trades (BATCH insert — 1 connection for all)
        signals_batch = []
        for t in trades:
            signals_batch.append({
                "run_id": run_id,
                "signal_time": datetime.fromtimestamp(
                    t.signal.timestamp_ms / 1000, tz=timezone.utc
                ).isoformat(),
                "signal_type": t.signal.signal_type,
                "btc_price": t.signal.candle_close,
                "candle_open": t.signal.candle_open,
                "candle_close": t.signal.candle_close,
                "candle_volume": t.signal.candle_volume,
                "volume_ratio": t.signal.volume_ratio,
                "body_pct": round(t.signal.body_pct * 100, 4),
                "ema_30m_20": t.signal.ema_30m_20,
                "ema_1h_50": t.signal.ema_1h_50,
                "fivemin_open": t.fivemin_open,
                "fivemin_close": t.fivemin_close,
                "fivemin_direction": t.fivemin_direction,
                "is_win": t.is_win,
                "pnl_80": t.pnl_80,
                "pnl_82": t.pnl_82,
                "pnl_85": t.pnl_85,
                "is_ny_session": t.signal.is_ny_session,
            })
        db.batch_insert_signals(signals_batch)
        logger.info(f"   -> Inserted {len(signals_batch)} signals (batch)")

        # Store daily summaries (BATCH)
        daily_batch = []
        cum_80, cum_82, cum_85 = 0, 0, 0
        for date_str in sorted(metrics["daily"].keys()):
            d = metrics["daily"][date_str]
            cum_80 += d["pnl_80"]
            cum_82 += d["pnl_82"]
            cum_85 += d["pnl_85"]
            wr = d["wins"] / d["total"] * 100 if d["total"] > 0 else 0
            daily_batch.append({
                "run_id": run_id,
                "date": date_str,
                "total_signals": d["total"],
                "wins": d["wins"],
                "losses": d["total"] - d["wins"],
                "win_rate": round(wr, 1),
                "long_signals": d["longs"],
                "short_signals": d["shorts"],
                "long_wins": d["long_wins"],
                "short_wins": d["short_wins"],
                "pnl_80": round(d["pnl_80"], 2),
                "pnl_82": round(d["pnl_82"], 2),
                "pnl_85": round(d["pnl_85"], 2),
                "cum_pnl_80": round(cum_80, 2),
                "cum_pnl_82": round(cum_82, 2),
                "cum_pnl_85": round(cum_85, 2),
            })
        db.batch_insert_daily_summaries(daily_batch)
        logger.info(f"   -> Inserted {len(daily_batch)} daily summaries (batch)")

        logger.info(f"   ✅ Stored run #{run_id}: {len(trades)} trades, "
                    f"{len(metrics['daily'])} daily summaries")

    except Exception as e:
        logger.error(f"   ❌ DB store failed: {e}", exc_info=True)


def _format_report(m: dict) -> str:
    """Format metrics into a clean text report."""
    fr = m["fill_results"]
    lines = [
        "",
        "═" * 64,
        "  2m STRICT STRATEGY — BACKTEST RESULTS",
        "═" * 64,
        f"  Period: {m['period_start'][:10]} → {m['period_end'][:10]} ({m['period_days']} days)",
        "",
        "  📊 SIGNAL STATISTICS",
        "  ─────────────────────────────────",
        f"  Total Signals:        {m['total_signals']:,}",
        f"  LONG Signals:         {m['total_longs']:,}",
        f"  SHORT Signals:        {m['total_shorts']:,}",
        f"  NY Session Signals:   {m['ny_session_trades']:,}",
        "",
        f"  Setups/Week (24/7):   {m['setups_per_week_24_7']:.1f}",
        f"  Setups/Week (NY):     {m['setups_per_week_ny']:.1f}",
        "",
        "  🎯 WIN RATES",
        "  ─────────────────────────────────",
        f"  Overall Win Rate:     {m['win_rate']:.1f}%",
        f"  LONG Win Rate:        {m['long_win_rate']:.1f}%",
        f"  SHORT Win Rate:       {m['short_win_rate']:.1f}%",
        f"  NY Session Win Rate:  {m['ny_session_win_rate']:.1f}%",
        "",
        "  💰 FILL PRICE SENSITIVITY",
        "  ─────────────────────────────────",
    ]

    for fp_key in ["80", "82", "85"]:
        r = fr[fp_key]
        lines.extend([
            f"  Fill @ {r['fill_price']*100:.0f}¢:",
            f"    Total PnL:      ${r['total_pnl']:+,.2f}",
            f"    Final Balance:  ${r['final_balance']:,.2f}",
            f"    ROI:            {r['roi_pct']:+.2f}%",
            f"    Max Drawdown:   {r['max_drawdown_pct']:.2f}% (${r['max_drawdown_usd']:,.2f})",
            "",
        ])

    lines.extend([
        "═" * 64,
    ])

    return "\n".join(lines)


# ── CLI Entry Point ──────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    force = "--force" in sys.argv
    use_db = "--no-db" not in sys.argv

    db = None
    if use_db:
        try:
            from db import Database
            db = Database()
            db.create_tables()
        except Exception as e:
            logger.warning(f"DB not available, running without DB: {e}")
            db = None

    results = run_backtest(db=db, force_refresh=force)

    if results and "error" not in results:
        print(f"\n✅ Backtest complete! {results['total_signals']} signals found.")
    else:
        print(f"\n❌ Backtest failed: {results.get('error', 'unknown')}")
