import dns_bypass  # Bypass DNS nhà mạng VN

"""
demo_polymarket_api.py — Demo kéo dữ liệu thật từ sàn Polymarket
═══════════════════════════════════════════════════════════════════
Không cần API key, không cần đăng ký, hoàn toàn miễn phí.
"""

import requests
import json
from datetime import datetime, timezone

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

print("=" * 65)
print("  DEMO: Kéo dữ liệu THẬT từ sàn Polymarket")
print("=" * 65)

# ═══════════════════════════════════════════════════════════════
# 1. TÌM THỊ TRƯỜNG BTC UP/DOWN ĐANG MỞ
# ═══════════════════════════════════════════════════════════════
print("\n📡 [1] Đang gọi Gamma API để tìm thị trường BTC...")

resp = requests.get(f"{GAMMA_API}/events", params={
    "closed": "false",
    "limit": 5,
    "tag": "crypto",
}, timeout=15)

events = resp.json()
print(f"    → Tìm thấy {len(events)} sự kiện crypto đang mở\n")

btc_markets = []
for event in events:
    title = event.get("title", "")
    markets = event.get("markets", [])
    for m in markets:
        question = m.get("question", "")
        if "bitcoin" in question.lower() or "btc" in question.lower():
            btc_markets.append(m)
            cond_id = m.get("conditionId", "N/A")
            yes_price = m.get("outcomePrices", "N/A")
            end_date = m.get("endDate", "N/A")
            print(f"    🔸 {question[:70]}")
            print(f"       ID: {cond_id[:20]}...")
            print(f"       Giá: {yes_price}")
            print(f"       Hết hạn: {end_date}")
            print()

if not btc_markets:
    # Tìm bất kỳ thị trường nào để demo
    print("    (Không có thị trường BTC lúc này, lấy thị trường khác để demo)\n")
    for event in events[:3]:
        title = event.get("title", "")
        print(f"    🔸 {title[:70]}")
        markets = event.get("markets", [])
        if markets:
            m = markets[0]
            btc_markets.append(m)
            print(f"       Câu hỏi: {m.get('question', '')[:60]}")
            print(f"       Giá YES/NO: {m.get('outcomePrices', 'N/A')}")
            print()

# ═══════════════════════════════════════════════════════════════
# 2. LẤY ORDERBOOK (BẢNG GIÁ MUA BÁN)
# ═══════════════════════════════════════════════════════════════
if btc_markets:
    market = btc_markets[0]
    token_id = market.get("clobTokenIds", "")
    
    if token_id and isinstance(token_id, str):
        try:
            token_ids = json.loads(token_id)
            if token_ids:
                token_id = token_ids[0]
        except:
            pass
    
    if token_id and token_id != "":
        print(f"📡 [2] Đang lấy Orderbook cho token: {str(token_id)[:20]}...")
        
        try:
            ob_resp = requests.get(f"{CLOB_API}/book", params={
                "token_id": token_id,
            }, timeout=15)
            
            if ob_resp.status_code == 200:
                book = ob_resp.json()
                bids = book.get("bids", [])
                asks = book.get("asks", [])
                
                print(f"\n    📊 ORDERBOOK THẬT (real-time):")
                print(f"    {'─' * 50}")
                print(f"    BÊN BÁN (Ask)          │  BÊN MUA (Bid)")
                print(f"    Giá      Số lượng       │  Giá      Số lượng")
                print(f"    {'─' * 50}")
                
                max_rows = min(5, max(len(asks), len(bids)))
                for i in range(max_rows):
                    ask_str = ""
                    bid_str = ""
                    if i < len(asks):
                        a = asks[i]
                        ask_str = f"${float(a['price']):.2f}    {float(a['size']):>8.1f}"
                    if i < len(bids):
                        b = bids[i]
                        bid_str = f"${float(b['price']):.2f}    {float(b['size']):>8.1f}"
                    print(f"    {ask_str:<23} │  {bid_str}")
                
                print(f"    {'─' * 50}")
                if asks and bids:
                    spread = float(asks[0]['price']) - float(bids[0]['price'])
                    print(f"    Spread: ${spread:.4f}")
            else:
                print(f"    Orderbook status: {ob_resp.status_code}")
        except Exception as e:
            print(f"    Lỗi lấy orderbook: {e}")

# ═══════════════════════════════════════════════════════════════
# 3. LẤY LỊCH SỬ GIÁ (PRICE HISTORY)
# ═══════════════════════════════════════════════════════════════
print(f"\n📡 [3] Đang lấy danh sách thị trường đã kết thúc gần đây...")

try:
    closed_resp = requests.get(f"{GAMMA_API}/events", params={
        "closed": "true",
        "limit": 5,
        "tag": "crypto",
    }, timeout=15)
    
    closed_events = closed_resp.json()
    print(f"    → Tìm thấy {len(closed_events)} sự kiện crypto đã đóng\n")
    
    for event in closed_events[:3]:
        title = event.get("title", "")
        markets = event.get("markets", [])
        print(f"    📜 {title[:65]}")
        if markets:
            m = markets[0]
            outcome = m.get("outcome", "N/A")
            print(f"       Kết quả: {outcome}")
            print(f"       Câu hỏi: {m.get('question', '')[:55]}")
        print()
except Exception as e:
    print(f"    Lỗi: {e}")

# ═══════════════════════════════════════════════════════════════
# TÓM TẮT
# ═══════════════════════════════════════════════════════════════
print("=" * 65)
print("  TÓM TẮT: 3 nguồn dữ liệu thật từ Polymarket")
print("=" * 65)
print("""
  ✅ Gamma API  → Tìm thị trường đang mở/đã đóng
  ✅ CLOB API   → Lấy orderbook (ai mua/bán ở giá nào)  
  ✅ WebSocket  → Nhận giá real-time (bot đã dùng khi chạy)
  
  Tất cả MIỄN PHÍ, KHÔNG cần API key, KHÔNG cần đăng ký.
  Bot PolyM của bạn đã tự động kéo dữ liệu này mỗi 60 giây.
""")
