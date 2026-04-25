"""
api_server.py — REST API + Dashboard for 2m Strict Backtest
═══════════════════════════════════════════════════════════
Flask server exposing backtest results to web dashboard.
"""

import os
import sys
import json
import mimetypes
import threading
from datetime import datetime, timezone, date
from decimal import Decimal
from flask import Flask, jsonify, request, send_from_directory

mimetypes.add_type('text/css', '.css')
mimetypes.add_type('application/javascript', '.js')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import Database
from config import INITIAL_BALANCE, FILL_PRICES

app = Flask(__name__, static_folder="web", static_url_path="")
db = Database()


class BotEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


def _jsonify(data):
    return app.response_class(
        response=json.dumps(data, cls=BotEncoder),
        status=200, mimetype="application/json",
    )


# ─── Static Frontend ─────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("web", "index.html")

@app.route("/style.css")
def serve_css():
    return send_from_directory("web", "style.css", mimetype="text/css")

@app.route("/app.js")
def serve_js():
    return send_from_directory("web", "app.js", mimetype="application/javascript")


# ─── API Endpoints ───────────────────────────────────────────

@app.route("/api/overview")
def api_overview():
    """Main overview stats for the latest backtest run."""
    run = db.get_latest_run()
    if not run:
        return _jsonify({"error": "No backtest data. Run the backtester first."})

    return _jsonify({
        "run_id": run["id"],
        "strategy": run["name"],
        "period": f"{run['start_date']} → {run['end_date']}",
        "total_signals": int(run["total_signals"]),
        "total_longs": int(run["total_longs"]),
        "total_shorts": int(run["total_shorts"]),
        "win_rate": float(run["win_rate"]),
        "long_win_rate": float(run["long_win_rate"]),
        "short_win_rate": float(run["short_win_rate"]),
        "setups_per_week_all": float(run["setups_per_week_all"]),
        "setups_per_week_ny": float(run["setups_per_week_ny"]),
        "fill_sensitivity": {
            "80": {
                "max_drawdown": float(run["max_dd_80"]),
                "final_pnl": float(run["final_pnl_80"]),
                "final_balance": INITIAL_BALANCE + float(run["final_pnl_80"]),
                "roi": round(float(run["final_pnl_80"]) / INITIAL_BALANCE * 100, 2),
            },
            "82": {
                "max_drawdown": float(run["max_dd_82"]),
                "final_pnl": float(run["final_pnl_82"]),
                "final_balance": INITIAL_BALANCE + float(run["final_pnl_82"]),
                "roi": round(float(run["final_pnl_82"]) / INITIAL_BALANCE * 100, 2),
            },
            "85": {
                "max_drawdown": float(run["max_dd_85"]),
                "final_pnl": float(run["final_pnl_85"]),
                "final_balance": INITIAL_BALANCE + float(run["final_pnl_85"]),
                "roi": round(float(run["final_pnl_85"]) / INITIAL_BALANCE * 100, 2),
            },
        },
        "initial_balance": INITIAL_BALANCE,
        "created_at": run["created_at"],
    })


@app.route("/api/signals")
def api_signals():
    """Paginated signals list."""
    run = db.get_latest_run()
    if not run:
        return _jsonify({"signals": [], "total": 0})

    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    sig_type = request.args.get("type")  # LONG, SHORT, or None
    wins = request.args.get("wins")  # true, false, or None

    wins_bool = None
    if wins == "true":
        wins_bool = True
    elif wins == "false":
        wins_bool = False

    offset = (page - 1) * per_page
    signals = db.get_signals(run["id"], limit=per_page, offset=offset,
                             signal_type=sig_type, wins_only=wins_bool)
    total = db.count_signals(run["id"])

    result = []
    for s in signals:
        result.append({
            "id": s["id"],
            "time": s["signal_time"],
            "type": s["signal_type"],
            "btc_price": float(s["btc_price"]),
            "volume_ratio": float(s["volume_ratio"]),
            "body_pct": float(s["body_pct"]),
            "ema_30m": float(s["ema_30m_20"]),
            "ema_1h": float(s["ema_1h_50"]),
            "fivemin_dir": s["fivemin_direction"],
            "is_win": s["is_win"],
            "is_ny": s["is_ny_session"],
            "pnl_80": float(s["pnl_80"]),
            "pnl_82": float(s["pnl_82"]),
            "pnl_85": float(s["pnl_85"]),
        })

    return _jsonify({
        "signals": result,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    })


@app.route("/api/daily")
def api_daily():
    """Daily summaries for charts."""
    run = db.get_latest_run()
    if not run:
        return _jsonify([])

    summaries = db.get_daily_summaries(run["id"])
    result = []
    for s in summaries:
        result.append({
            "date": s["date"].isoformat() if isinstance(s["date"], date) else str(s["date"]),
            "signals": int(s["total_signals"]),
            "wins": int(s["wins"]),
            "losses": int(s["losses"]),
            "win_rate": float(s["win_rate"]),
            "longs": int(s["long_signals"]),
            "shorts": int(s["short_signals"]),
            "pnl_80": float(s["pnl_80"]),
            "pnl_82": float(s["pnl_82"]),
            "pnl_85": float(s["pnl_85"]),
            "cum_pnl_80": float(s["cum_pnl_80"]),
            "cum_pnl_82": float(s["cum_pnl_82"]),
            "cum_pnl_85": float(s["cum_pnl_85"]),
        })
    return _jsonify(result)


@app.route("/api/equity")
def api_equity():
    """Equity curve for all 3 fill prices."""
    run = db.get_latest_run()
    if not run:
        return _jsonify([])

    summaries = db.get_daily_summaries(run["id"])
    points = [{"date": "Start", "bal_80": INITIAL_BALANCE,
               "bal_82": INITIAL_BALANCE, "bal_85": INITIAL_BALANCE}]
    for s in summaries:
        d = s["date"].isoformat() if isinstance(s["date"], date) else str(s["date"])
        points.append({
            "date": d,
            "bal_80": round(INITIAL_BALANCE + float(s["cum_pnl_80"]), 2),
            "bal_82": round(INITIAL_BALANCE + float(s["cum_pnl_82"]), 2),
            "bal_85": round(INITIAL_BALANCE + float(s["cum_pnl_85"]), 2),
        })
    return _jsonify(points)


@app.route("/api/stats")
def api_stats():
    """Detailed stats from signals table."""
    run = db.get_latest_run()
    if not run:
        return _jsonify({})

    stats = db.get_run_stats(run["id"])
    if not stats:
        return _jsonify({})

    total = int(stats["total"] or 0)
    wins = int(stats["wins"] or 0)
    longs = int(stats["longs"] or 0)
    shorts = int(stats["shorts"] or 0)
    long_wins = int(stats["long_wins"] or 0)
    short_wins = int(stats["short_wins"] or 0)

    return _jsonify({
        "total": total,
        "wins": wins,
        "losses": int(stats["losses"] or 0),
        "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
        "longs": longs,
        "shorts": shorts,
        "long_win_rate": round(long_wins / longs * 100, 1) if longs > 0 else 0,
        "short_win_rate": round(short_wins / shorts * 100, 1) if shorts > 0 else 0,
        "ny_total": int(stats["ny_total"] or 0),
        "ny_wins": int(stats["ny_wins"] or 0),
        "total_pnl_80": float(stats["total_pnl_80"] or 0),
        "total_pnl_82": float(stats["total_pnl_82"] or 0),
        "total_pnl_85": float(stats["total_pnl_85"] or 0),
    })


@app.route("/api/health")
def api_health():
    return _jsonify({"status": "ok", "time": datetime.now(timezone.utc).isoformat()})


@app.route("/api/run-backtest", methods=["POST"])
def api_run_backtest():
    """Trigger a new backtest run (async)."""
    def _run():
        from backtester import run_backtest
        run_backtest(db=db, force_refresh=False)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return _jsonify({"status": "started", "message": "Backtest running in background"})


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5050)))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    db.create_tables()
    print(f"🌐 2m Strict Dashboard on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)
