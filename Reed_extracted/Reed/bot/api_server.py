"""
api_server.py — REST API for PolyM Trading Dashboard
═══════════════════════════════════════════════════
Flask server that exposes bot data to the web dashboard.
Reuses existing db.py Database class.

Endpoints:
  GET /api/stats       → Overall stats (balance, PnL, ROI, etc.)
  GET /api/positions   → Open positions with unrealized PnL
  GET /api/trades      → Closed trades (paginated)
  GET /api/daily       → Daily summary data for charts
  GET /api/equity      → Equity curve data points
  GET /api/benchmark   → PolyM benchmark comparison
  GET /api/status      → Bot running status

Usage:
  python api_server.py          # Start on port 5000
  python api_server.py --port 8080
═══════════════════════════════════════════════════
"""

import os
import sys
import json
import mimetypes
import subprocess
from datetime import datetime, timezone, date
from decimal import Decimal
from flask import Flask, jsonify, request, send_from_directory

# Fix MIME types (Render/Linux may not detect correctly)
mimetypes.add_type('text/css', '.css')
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('image/svg+xml', '.svg')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import Database
from config import PAPER_INITIAL_BALANCE

app = Flask(__name__, static_folder="web", static_url_path="")
db = Database()


# ─── JSON Encoder for Decimal/date types ─────────────────────

class BotEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

app.json_provider_class = None  # Use custom encoder


def _jsonify(data):
    """JSON response with proper Decimal/date handling."""
    return app.response_class(
        response=json.dumps(data, cls=BotEncoder),
        status=200,
        mimetype="application/json",
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

@app.route("/api/stats")
def api_stats():
    """Overall bot statistics."""
    stats = db.get_stats()
    balance = float(db.get_config("balance") or PAPER_INITIAL_BALANCE)
    total_pnl = float(stats["total_pnl"])
    roi = (balance - PAPER_INITIAL_BALANCE) / PAPER_INITIAL_BALANCE * 100

    # Get best trade
    trades = db.get_all_trades()
    best_trade = 0
    total_volume = 0
    for t in trades:
        pnl = float(t.get("pnl") or 0)
        size = float(t.get("size_usd") or 0)
        total_volume += size
        if pnl > best_trade:
            best_trade = pnl

    # Get bot start time
    started_at = db.get_config("bot_started_at")

    # Calculate total equity (cash + open positions)
    positions = db.get_open_positions()
    positions_invested = sum(float(p.get("size_usd") or 0) for p in positions)
    unrealized = sum(float(p.get("unrealized_pnl") or 0) for p in positions)
    total_equity = balance + positions_invested + unrealized
    total_pnl_real = total_equity - PAPER_INITIAL_BALANCE

    return _jsonify({
        "balance": round(total_equity, 2),
        "initial_balance": PAPER_INITIAL_BALANCE,
        "total_pnl": round(total_pnl_real, 2),
        "roi_percent": round((total_equity - PAPER_INITIAL_BALANCE) / PAPER_INITIAL_BALANCE * 100, 2),
        "total_trades": int(stats["total_trades"]),
        "open_trades": int(stats["open_trades"]),
        "closed_trades": int(stats["closed_trades"]),
        "open_positions": int(stats["open_positions"]),
        "eligible_markets": int(stats["eligible_markets"]),
        "best_trade": best_trade,
        "positions_value": round(positions_invested + unrealized, 2),
        "total_volume": total_volume,
        "started_at": started_at,
    })


@app.route("/api/positions")
def api_positions():
    """Open positions with current data."""
    positions = db.get_open_positions()
    result = []
    for p in positions:
        size_usd = float(p.get("size_usd") or 1)
        unrealized = float(p.get("unrealized_pnl") or 0)
        pnl_pct = (unrealized / size_usd * 100) if size_usd > 0 else 0

        result.append({
            "id": p.get("id"),
            "market_id": p.get("market_id"),
            "market_title": p.get("market_title", ""),
            "asset": p.get("asset", ""),
            "side": p.get("side", ""),
            "entry_price": float(p.get("entry_price") or 0),
            "current_price": float(p.get("current_price") or 0),
            "size_usd": size_usd,
            "shares": float(p.get("shares") or 0),
            "unrealized_pnl": unrealized,
            "pnl_percent": round(pnl_pct, 2),
            "status": p.get("status", "OPEN"),
            "entry_time": p.get("entry_time"),
        })
    return _jsonify(result)


@app.route("/api/trades")
def api_trades():
    """Closed trades - paginated."""
    tab = request.args.get("tab", "all")  # all, winners, losers
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))

    all_trades = db.get_all_trades()

    # Filter by tab
    if tab == "winners":
        all_trades = [t for t in all_trades if float(t.get("pnl") or 0) > 0]
    elif tab == "losers":
        all_trades = [t for t in all_trades if float(t.get("pnl") or 0) < 0]
    elif tab == "active":
        all_trades = [t for t in all_trades if t.get("status") == "OPEN"]
    elif tab == "closed":
        all_trades = [t for t in all_trades if t.get("status") != "OPEN"]

    # Sort by entry_time desc
    all_trades.sort(
        key=lambda t: t.get("entry_time") or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    total = len(all_trades)
    start = (page - 1) * per_page
    end = start + per_page
    trades_page = all_trades[start:end]

    # Build position lookup for OPEN trades (current price + unrealized PnL)
    positions = db.get_open_positions()
    pos_by_trade = {}
    for p in positions:
        tid = p.get("trade_id")
        if tid:
            pos_by_trade[tid] = p

    result = []
    for t in trades_page:
        trade_id = t.get("id")
        status = t.get("status", "")
        entry_price = float(t.get("entry_price") or 0)
        exit_price = float(t.get("exit_price") or 0)
        pnl = float(t.get("pnl") or 0)

        # For OPEN trades: use live position data
        if status == "OPEN" and trade_id in pos_by_trade:
            pos = pos_by_trade[trade_id]
            exit_price = float(pos.get("current_price") or entry_price)
            pnl = float(pos.get("unrealized_pnl") or 0)

        result.append({
            "id": trade_id,
            "market_title": t.get("market_title", ""),
            "asset": t.get("asset", ""),
            "side": t.get("side", ""),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "size_usd": float(t.get("size_usd") or 0),
            "shares": float(t.get("shares") or 0),
            "pnl": pnl,
            "status": status,
            "exit_reason": t.get("exit_reason", ""),
            "entry_time": t.get("entry_time"),
            "exit_time": t.get("exit_time"),
            "hold_minutes": float(t.get("hold_minutes") or 0),
        })

    return _jsonify({
        "trades": result,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    })


@app.route("/api/daily")
def api_daily():
    """Daily summaries for charts."""
    summaries = db.get_daily_summaries()
    result = []
    for s in summaries:
        result.append({
            "date": s["date"].isoformat() if isinstance(s["date"], date) else str(s["date"]),
            "total_trades": int(s.get("total_trades") or 0),
            "winners": int(s.get("winners") or 0),
            "losers": int(s.get("losers") or 0),
            "breakeven": int(s.get("breakeven") or 0),
            "win_rate": float(s.get("win_rate") or 0),
            "net_pnl": float(s.get("net_pnl") or 0),
            "cumulative_pnl": float(s.get("cumulative_pnl") or 0),
            "balance": float(s.get("balance") or 0),
            "avg_win": float(s.get("avg_win") or 0),
            "avg_loss": float(s.get("avg_loss") or 0),
            "rr_ratio": float(s.get("rr_ratio") or 0),
            "best_trade": float(s.get("best_trade") or 0),
            "worst_trade": float(s.get("worst_trade") or 0),
            "avg_hold_minutes": float(s.get("avg_hold_minutes") or 0),
        })
    return _jsonify(result)


@app.route("/api/equity")
def api_equity():
    """Equity curve — always includes today's real-time point."""
    summaries = db.get_daily_summaries()
    today = datetime.now(timezone.utc).date()
    today_str = today.isoformat()

    # Build equity points from historical summaries
    # FIX: Use PAPER_INITIAL_BALANCE + cumulative_pnl for balance
    # instead of daily_summary.balance which may be corrupted by restarts
    points = [{"date": "Start", "balance": PAPER_INITIAL_BALANCE, "pnl": 0}]
    for s in summaries:
        d = s["date"].isoformat() if isinstance(s["date"], date) else str(s["date"])
        cum_pnl = float(s.get("cumulative_pnl") or 0)
        # Derive balance from initial + cumulative PnL (never trust stored balance)
        derived_balance = PAPER_INITIAL_BALANCE + cum_pnl
        points.append({
            "date": d,
            "balance": round(derived_balance, 2),
            "pnl": cum_pnl,
        })

    # Always inject today's live point
    current_balance = float(db.get_config("balance") or PAPER_INITIAL_BALANCE)
    positions = db.get_open_positions()
    positions_invested = sum(float(p.get("size_usd") or 0) for p in positions)
    unrealized = sum(float(p.get("unrealized_pnl") or 0) for p in positions)
    total_equity = current_balance + positions_invested + unrealized
    current_pnl = round(total_equity - PAPER_INITIAL_BALANCE, 2)

    if not any(p.get("date") == today_str for p in points):
        points.append({
            "date": today_str,
            "balance": round(total_equity, 2),
            "pnl": current_pnl,
        })
    else:
        # Patch today's point with live equity
        for p in points:
            if p.get("date") == today_str:
                p["balance"] = round(total_equity, 2)
                p["pnl"] = current_pnl
                break

    return _jsonify(points)


@app.route("/api/benchmark")
def api_benchmark():
    """PolyM benchmark comparison."""
    trades = db.get_all_trades()
    closed_trades = [t for t in trades if t.get("status") != "OPEN"]
    
    winners = [t for t in closed_trades if float(t.get("pnl") or 0) > 0]
    losers = [t for t in closed_trades if float(t.get("pnl") or 0) < 0]
    
    total_closed = len(closed_trades)
    win_rate = (len(winners) / total_closed * 100) if total_closed > 0 else 0
    
    avg_win = sum(float(t.get("pnl") or 0) for t in winners) / len(winners) if winners else 0
    avg_loss = abs(sum(float(t.get("pnl") or 0) for t in losers) / len(losers)) if losers else 0
    
    avg_rr = (avg_win / avg_loss) if avg_loss > 0 else 0
    
    # Calculate profit_days from trades (grouping by date)
    daily_pnls = {}
    for t in closed_trades:
        exit_time = t.get("exit_time")
        if exit_time:
            # handle iso format assuming string starts with YYYY-MM-DD
            date_str = str(exit_time)[:10]
            daily_pnls[date_str] = daily_pnls.get(date_str, 0) + float(t.get("pnl") or 0)

    # Include today as a day if there are open or closed trades today but no exit_time yet
    # Or just rely on dates that have closed trades
    if not daily_pnls:
        total_days = 1
        profit_days = 0 
    else:
        total_days = len(daily_pnls)
        profit_days = sum(1 for pnl in daily_pnls.values() if pnl > 0)
        
    profit_days_pct = (profit_days / total_days * 100) if total_days > 0 else 0

    return _jsonify({
        "bot": {
            "win_rate": round(win_rate, 1),
            "rr_ratio": round(avg_rr, 2),
            "profit_days_pct": round(profit_days_pct, 1),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "total_trades": len(trades),
            "total_days": total_days,
        },
        "PolyM_benchmark": {
            "win_rate": 51.6,
            "rr_ratio": 1.20,
            "profit_days_pct": 91.8,
            "accuracy_match": 91,
        },
    })


@app.route("/api/status")
def api_status():
    """Bot running status — checks DB heartbeat (works across Render services)."""
    now = datetime.now(timezone.utc)
    running = False
    last_seen = None

    try:
        # Primary: check for recent HEARTBEAT log (every 5 min)
        hb_logs = db.get_recent_logs(level="HEARTBEAT", limit=1)
        if hb_logs:
            t = hb_logs[0].get("created_at")
            if t:
                if isinstance(t, str):
                    t = datetime.fromisoformat(t.replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                age_min = (now - t).total_seconds() / 60
                last_seen = t.isoformat()
                running = age_min < 10  # online if heartbeat < 10 min ago

        # Fallback: any recent log (bot just started, no heartbeat yet)
        if not running:
            any_logs = db.get_recent_logs(limit=1)
            if any_logs:
                t = any_logs[0].get("created_at")
                if t:
                    if isinstance(t, str):
                        t = datetime.fromisoformat(t.replace("Z", "+00:00"))
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=timezone.utc)
                    age_min = (now - t).total_seconds() / 60
                    last_seen = t.isoformat()
                    running = age_min < 10  # online if any log < 10 min ago
    except Exception as e:
        pass

    return _jsonify({
        "running": running,
        "last_seen": last_seen,
        "checked_at": now.isoformat(),
    })


# ─── Diagnostic Endpoints (for remote monitoring) ────────────

@app.route("/api/logs")
def api_logs():
    """Get recent logs, optionally filtered by level."""
    level = request.args.get("level", None)
    limit = min(int(request.args.get("limit", 50)), 200)

    logs = db.get_recent_logs(level=level, limit=limit)
    return _jsonify([{
        "id": log["id"],
        "level": log["level"],
        "module": log["module"],
        "message": log["message"],
        "data": log["data"],
        "time": log["created_at"],
    } for log in logs])


@app.route("/api/health")
def api_health():
    """Full health report for remote diagnosis."""
    report = db.get_health_report()

    # Also include trade performance vs PolyM benchmark
    stats = db.get_stats()
    daily = db.get_daily_summaries()

    win_days = sum(1 for d in daily if float(d.get("pnl", 0)) > 0)
    total_days = max(len(daily), 1)

    report["performance"] = {
        "balance": float(stats.get("balance", 0)),
        "total_pnl": float(stats.get("total_pnl", 0)),
        "total_trades": stats.get("total_trades", 0),
        "win_rate_bot": 0,
        "win_rate_PolyM": 51.6,
        "profit_days_bot": round(win_days / total_days * 100, 1),
        "profit_days_PolyM": 91.8,
    }

    # Calculate win rate if trades exist
    closed = stats.get("closed_trades", 0)
    if closed > 0:
        all_trades = db.get_all_trades()
        wins = sum(1 for t in all_trades
                   if t.get("status") == "CLOSED"
                   and float(t.get("pnl", 0)) > 0)
        report["performance"]["win_rate_bot"] = round(
            wins / closed * 100, 1
        )

    return _jsonify(report)


# ─── Live Polymarket Data Check ──────────────────────────────

@app.route("/api/polymarket-live")
def api_polymarket_live():
    """Kéo dữ liệu THẬT từ Polymarket để kiểm tra API."""
    import dns_bypass
    import requests as req

    results = {"status": "error", "polymarket": [], "binance": {}}

    # 1. Polymarket Gamma API
    try:
        r = req.get("https://gamma-api.polymarket.com/events",
                     params={"closed": "false", "limit": 10, "tag": "crypto"},
                     timeout=15)
        events = r.json()
        markets = []
        for event in events:
            for m in event.get("markets", []):
                prices = m.get("outcomePrices", "")
                try:
                    price_list = json.loads(prices) if isinstance(prices, str) else prices
                except Exception:
                    price_list = prices
                markets.append({
                    "question": m.get("question", ""),
                    "yes_price": price_list[0] if isinstance(price_list, list) and len(price_list) > 0 else "?",
                    "no_price": price_list[1] if isinstance(price_list, list) and len(price_list) > 1 else "?",
                    "volume": m.get("volume", 0),
                    "end_date": m.get("endDate", ""),
                })
        results["polymarket"] = markets
        results["polymarket_count"] = len(markets)
        results["status"] = "ok"
    except Exception as e:
        results["polymarket_error"] = str(e)

    # 2. Binance BTC price
    try:
        r2 = req.get("https://api.binance.com/api/v3/ticker/price",
                      params={"symbol": "BTCUSDT"}, timeout=10)
        results["binance"] = r2.json()
    except Exception as e:
        results["binance_error"] = str(e)

    results["checked_at"] = datetime.now(timezone.utc).isoformat()
    return _jsonify(results)


@app.route("/check")
def check_page():
    """Trang kiểm tra API trực quan."""
    html = """<!DOCTYPE html>
<html><head>
<title>PolyM - API Check</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',sans-serif;background:#0d1117;color:#e6edf3;padding:40px}
h1{color:#2A59FA;margin-bottom:10px}
h2{color:#58a6ff;margin:30px 0 15px}
.ok{background:#238636;color:white;padding:4px 12px;border-radius:12px;font-weight:bold}
.err{background:#da3633;color:white;padding:4px 12px;border-radius:12px;font-weight:bold}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:20px;margin:10px 0}
table{width:100%;border-collapse:collapse;margin-top:10px}
th{text-align:left;color:#8b949e;padding:8px;border-bottom:1px solid #30363d}
td{padding:8px;border-bottom:1px solid #21262d}
.price{color:#3fb950;font-weight:bold;font-size:22px}
.yes{color:#3fb950} .no{color:#f85149}
a{color:#58a6ff}
</style>
</head><body>
<h1>PolyM - Kiem Tra Ket Noi API</h1>
<p style="color:#8b949e">Trang nay keo du lieu THAT tu Polymarket + Binance.</p>
<div id="c"><p style="color:#8b949e">Dang keo du lieu...</p></div>
<script>
fetch('/api/polymarket-live').then(r=>r.json()).then(d=>{
let h='';
h+='<h2>Binance - Gia BTC</h2><div class="card">';
if(d.binance&&d.binance.price){
h+='<p>BTCUSDT: <span class="price">$'+parseFloat(d.binance.price).toLocaleString()+'</span></p>';
}else{h+='<p class="err">Loi ket noi Binance</p>';}
h+='</div>';
h+='<h2>Polymarket - Thi Truong Crypto</h2><div class="card">';
if(d.polymarket&&d.polymarket.length>0){
h+='<p>Tim thay <strong>'+d.polymarket.length+'</strong> thi truong <span class="ok">API OK</span></p>';
h+='<table><tr><th>Thi truong</th><th>YES</th><th>NO</th><th>Het han</th></tr>';
d.polymarket.forEach(m=>{
let y=parseFloat(m.yes_price),n=parseFloat(m.no_price);
let ys=isNaN(y)?m.yes_price:(y*100).toFixed(1)+'c';
let ns=isNaN(n)?m.no_price:(n*100).toFixed(1)+'c';
let e=m.end_date?m.end_date.split('T')[0]:'-';
h+='<tr><td>'+m.question.substring(0,65)+'</td><td class="yes">'+ys+'</td><td class="no">'+ns+'</td><td>'+e+'</td></tr>';
});
h+='</table>';
}else{h+='<p class="err">Khong keo duoc</p>';}
h+='</div>';
h+='<p style="margin-top:20px;color:#8b949e">Checked: '+d.checked_at+'</p>';
h+='<p style="margin-top:10px"><a href="/">Dashboard</a></p>';
document.getElementById('c').innerHTML=h;
}).catch(e=>{document.getElementById('c').innerHTML='Loi: '+e;});
</script>
</body></html>"""
    return html


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5050)))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print(f"🌐 PolyM Dashboard API starting on http://{args.host}:{args.port}")
    print(f"   Open http://localhost:{args.port} in your browser")
    app.run(host=args.host, port=args.port, debug=args.debug)
