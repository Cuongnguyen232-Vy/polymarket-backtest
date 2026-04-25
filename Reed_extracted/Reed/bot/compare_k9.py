#!/usr/bin/env python3
"""Quick comparison: Bot Clone vs K9 Original at Day 3"""

# K9 Original benchmark (from 104,388 positions over 102 days)
k9_total_pnl = 2_063_096
k9_total_trades = 100_345
k9_trading_days = 97
k9_avg_daily_trades = k9_total_trades / k9_trading_days
k9_avg_daily_pnl = k9_total_pnl / k9_trading_days
k9_ev_per_trade = 26.71

# Our bot data (from API - live)
bot_day1_trades = 88
bot_day1_pnl = 114.67
bot_day2_trades = 242
bot_day2_pnl = -4.43
bot_day3_trades = 10  # closed today
bot_day3_pnl_closed = -8.58

bot_total_trades = 392
bot_total_pnl = 470.25  # including unrealized
bot_total_closed_pnl = 114.67 + (-4.43) + (-8.58)  # = 101.66
bot_total_volume = 51245
bot_avg_size = bot_total_volume / bot_total_trades

# K9 volume estimate
k9_avg_size = 365
k9_total_volume = k9_total_trades * k9_avg_size

# PnL per dollar traded
k9_pnl_rate = k9_total_pnl / k9_total_volume * 100
our_pnl_rate = bot_total_pnl / bot_total_volume * 100

print("=" * 70)
print("  BOT CLONE vs K9 GOC - SO SANH NGAY THU 3")
print("=" * 70)

print(f"""
+-------------------------------------------------------------------+
|                    BOT CLONE (3 ngay)                              |
+-------------------------------------------------------------------+
|  Ngay bat dau:       April 3, 2026                                |
|  Von ban dau:        $3,000                                       |
|  Tong lenh:          {bot_total_trades}                                        |
|  Lenh/ngay (TB):     {bot_total_trades / 3:.0f}                                       |
|                                                                   |
|  PnL theo ngay:                                                   |
|    Day 1 (Apr 3):    +${bot_day1_pnl:.2f}  ({bot_day1_trades} trades, WR 51.1%)        |
|    Day 2 (Apr 4):    -${abs(bot_day2_pnl):.2f}   ({bot_day2_trades} trades, WR 47.5%)       |
|    Day 3 (Apr 5):    -${abs(bot_day3_pnl_closed):.2f}   ({bot_day3_trades} closed + 10 open)      |
|                                                                   |
|  Tong PnL (da chot): +${bot_total_closed_pnl:.2f}                             |
|  PnL + Unrealized:   +${bot_total_pnl:.2f}                             |
|  ROI:                +{bot_total_pnl / 3000 * 100:.2f}%                                |
|  Win Rate:           49.0%                                        |
|  R:R Ratio:          1.16                                         |
|  Profit days:        1/3 (33.3%)                                  |
+-------------------------------------------------------------------+

+-------------------------------------------------------------------+
|              K9 GOC (benchmark 102 ngay)                          |
+-------------------------------------------------------------------+
|  Ngay bat dau:       Dec 18, 2025                                 |
|  Von su dung:        ~$500K+ (position size TB $365)              |
|  Tong lenh:          104,388                                      |
|  Lenh/ngay (TB):     {k9_avg_daily_trades:.0f}                                      |
|                                                                   |
|  Metrics toan ky:                                                 |
|    Win Rate:         51.6%                                        |
|    R:R Ratio:        1.20                                         |
|    EV/lenh:          +$26.71                                      |
|    Profit days:      91.8% (89/97)                                |
|    PnL trung binh/ngay: +${k9_avg_daily_pnl:,.0f}                        |
|                                                                   |
|  Uoc tinh K9 after 3 ngay dau:                                   |
|    PnL (3 ngay):     ~+${k9_avg_daily_pnl * 3:,.0f}                       |
+-------------------------------------------------------------------+
""")

print("-" * 70)
print("  PHAN TICH SO SANH:")
print("-" * 70)

ratio_trades = k9_avg_daily_trades / (bot_total_trades / 3)
ratio_size = k9_avg_size / bot_avg_size
ratio_pnl = our_pnl_rate / k9_pnl_rate

print(f"""
  1. QUY MO: K9 goc trade ~{k9_avg_daily_trades:.0f} lenh/ngay vs Bot {bot_total_trades / 3:.0f} lenh/ngay
     -> Bot dang trade IT HON {ratio_trades:.0f}x so voi K9 goc

  2. SIZE: K9 avg ${k9_avg_size}/lenh vs Bot avg ${bot_avg_size:.0f}/lenh
     -> Bot dung size NHO HON ~{ratio_size:.0f}x

  3. WIN RATE: K9 = 51.6% vs Bot = 49.0%
     -> Bot THAP HON 2.6% (van trong khoang chap nhan duoc)

  4. R:R RATIO: K9 = 1.20 vs Bot = 1.16
     -> Bot THAP HON 3.3% (tot, gan khop)

  5. PROFIT DAYS: K9 = 91.8% vs Bot = 33.3%
     -> Bot CHI LAI 1/3 ngay (KHAC K9 nhung 3 ngay qua it de ket luan)

  6. ROI NORMALIZED (tren moi $ traded):
     K9:  {k9_pnl_rate:.3f}% PnL / $1 volume
     Bot: {our_pnl_rate:.3f}% PnL / $1 volume
     -> Bot hieu qua HON K9 tren moi dong! ({ratio_pnl:.1f}x tot hon)
""")

print("-" * 70)
print("  KET LUAN:")
print("-" * 70)
print("""
  [OK] Bot DANG HOAT DONG DUNG - PnL duong $470 sau 3 ngay
  [OK] Win rate (49%) va R:R (1.16) GAN KHOP K9 benchmark
  [OK] Hieu suat moi dong traded VUOT K9 goc
  
  [!!] Bot trade IT HON nhieu so voi K9 (131 vs 1034 lenh/ngay)
       -> K9 goc chay HFT chuyen nghiep, scan hang ngan 
          thi truong moi phut. Bot clone bi gioi han boi Render.
  
  [!!] Profit days = 33% (chi 1/3 ngay lai) 
       -> Qua som de danh gia (can 20+ ngay)
       -> K9 cung co ~8% ngay lo tren 97 ngay
  
  => Neu bot giu duoc win rate ~51% va R:R ~1.2 trong 2 tuan toi,
     thi bot clone dang replicate K9 dung cach.
""")
