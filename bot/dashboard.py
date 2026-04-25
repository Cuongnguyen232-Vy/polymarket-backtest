"""
dashboard.py — Module 4: Reporting & CSV Export
═══════════════════════════════════════════════════════════════
Generates daily text reports and CSV trade logs for the client.

Output formats:
  1. Text-based daily summary → send to client
  2. CSV trade log → attach for audit
  3. Multi-day performance report → 14-day summary

Usage:
  python dashboard.py                  # Today's report
  python dashboard.py --all            # Full history report  
  python dashboard.py --csv            # Export CSV only
  python dashboard.py --date 2026-04-01  # Specific date
═══════════════════════════════════════════════════════════════
"""

import os
import sys
import csv
import statistics
from datetime import datetime, timezone, timedelta, date
from collections import defaultdict

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import Database
from config import PAPER_INITIAL_BALANCE


class Dashboard:
    """Report generator for PolyM Paper Trading Bot."""

    def __init__(self, db: Database = None):
        self.db = db or Database()
        self.output_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "reports"
        )
        os.makedirs(self.output_dir, exist_ok=True)

    # ─── Daily Text Report ───────────────────────────────────

    def daily_report(self, target_date: date = None) -> str:
        """
        Generate a clean daily report.
        Designed to be copy-pasted into messages.
        """
        if target_date is None:
            target_date = datetime.now(timezone.utc).date()

        # Ensure summary is up-to-date
        balance = float(self.db.get_config("balance") or PAPER_INITIAL_BALANCE)
        self.db.update_daily_summary(target_date, balance)

        summary = None
        summaries = self.db.get_daily_summaries()
        for s in summaries:
            if s["date"] == target_date:
                summary = s
                break

        if not summary:
            return f"No trading data for {target_date}"

        # Get today's trades for detail section
        trades = self.db.get_trades_for_date(target_date)

        report = []
        report.append("━" * 50)
        report.append("  PolyM BOT — DAILY PERFORMANCE REPORT")
        report.append(f"  Date: {target_date}")
        report.append(f"  Generated: {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
        report.append("━" * 50)
        report.append("")

        # Key metrics
        report.append("📊 PERFORMANCE")
        report.append(f"  Trades:     {summary['total_trades']}")
        report.append(f"  Winners:    {summary['winners']} "
                      f"({float(summary['win_rate']):.1f}%)")
        report.append(f"  Losers:     {summary['losers']}")
        report.append(f"  Breakeven:  {summary['breakeven']}")
        report.append("")

        report.append("💰 P&L")
        net = float(summary['net_pnl'])
        cum = float(summary['cumulative_pnl'])
        report.append(f"  Today:      ${net:+,.2f}")
        report.append(f"  Cumulative: ${cum:+,.2f}")
        report.append(f"  Balance:    ${float(summary['balance']):,.2f}")
        report.append("")

        report.append("⚖️ RISK")
        report.append(f"  Avg Win:    ${float(summary['avg_win']):,.2f}")
        report.append(f"  Avg Loss:   ${float(summary['avg_loss']):,.2f}")
        report.append(f"  R:R Ratio:  {float(summary['rr_ratio']):.2f}")
        report.append(f"  Best:       ${float(summary['best_trade']):+,.2f}")
        report.append(f"  Worst:      ${float(summary['worst_trade']):+,.2f}")
        report.append("")

        report.append("⏱️ TIMING")
        report.append(f"  Avg Hold:   {float(summary['avg_hold_minutes']):.1f} min")
        report.append("")

        # Top 5 trades detail
        if trades:
            report.append("📋 TOP TRADES (by PnL)")
            sorted_trades = sorted(
                trades, key=lambda t: abs(float(t['pnl'] or 0)), reverse=True
            )
            for t in sorted_trades[:5]:
                pnl = float(t['pnl'] or 0)
                emoji = "🟢" if pnl >= 0 else "🔴"
                report.append(
                    f"  {emoji} {t['asset']} {t['side']} "
                    f"${float(t['entry_price']):.3f}→"
                    f"${float(t['exit_price'] or 0):.3f} "
                    f"| ${pnl:+,.2f} | {t['status']}"
                )
            report.append("")

        report.append("━" * 50)
        return "\n".join(report)

    # ─── Multi-Day Performance Report ────────────────────────

    def full_report(self) -> str:
        """
        Generate comprehensive multi-day performance report.
        Used for 14-day paper trading summary.
        """
        summaries = self.db.get_daily_summaries()
        stats = self.db.get_stats()

        if not summaries:
            return "No trading data available."

        report = []
        report.append("═" * 60)
        report.append("  PolyM PAPER TRADING BOT — FULL PERFORMANCE REPORT")
        report.append(f"  Period: {summaries[0]['date']} → {summaries[-1]['date']}")
        report.append(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        report.append("═" * 60)
        report.append("")

        # Overall stats
        total_trades = int(stats['total_trades'])
        total_pnl = float(stats['total_pnl'])
        balance = float(self.db.get_config("balance") or PAPER_INITIAL_BALANCE)
        roi = (balance - PAPER_INITIAL_BALANCE) / PAPER_INITIAL_BALANCE * 100

        report.append("📈 OVERALL PERFORMANCE")
        report.append(f"  Starting Balance: ${PAPER_INITIAL_BALANCE:,.2f}")
        report.append(f"  Current Balance:  ${balance:,.2f}")
        report.append(f"  Total PnL:        ${total_pnl:+,.2f}")
        report.append(f"  ROI:              {roi:+.2f}%")
        report.append(f"  Total Trades:     {total_trades:,}")
        report.append(f"  Trading Days:     {len(summaries)}")
        report.append("")

        # Aggregate win/loss
        all_wins = sum(int(s['winners']) for s in summaries)
        all_losses = sum(int(s['losers']) for s in summaries)
        all_be = sum(int(s['breakeven']) for s in summaries)
        total_closed = all_wins + all_losses
        agg_wr = (all_wins / total_closed * 100) if total_closed > 0 else 0

        report.append("🎯 AGGREGATED METRICS")
        report.append(f"  Win Rate:    {agg_wr:.1f}% ({all_wins}W / {all_losses}L / {all_be}BE)")

        # Average R:R across days
        rr_values = [float(s['rr_ratio']) for s in summaries if float(s['rr_ratio']) > 0]
        avg_rr = statistics.mean(rr_values) if rr_values else 0
        report.append(f"  Avg R:R:     {avg_rr:.2f}")

        # Daily PnL stats
        daily_pnls = [float(s['net_pnl']) for s in summaries]
        profit_days = sum(1 for p in daily_pnls if p > 0)
        loss_days = sum(1 for p in daily_pnls if p < 0)
        report.append(f"  Profit Days: {profit_days}/{len(summaries)} "
                      f"({profit_days/len(summaries)*100:.0f}%)")
        report.append(f"  Loss Days:   {loss_days}/{len(summaries)}")

        if daily_pnls:
            report.append(f"  Avg Daily:   ${statistics.mean(daily_pnls):+,.2f}")
            report.append(f"  Best Day:    ${max(daily_pnls):+,.2f}")
            report.append(f"  Worst Day:   ${min(daily_pnls):+,.2f}")

        # Drawdown
        peak = PAPER_INITIAL_BALANCE
        max_dd = 0
        cumulative = PAPER_INITIAL_BALANCE
        for s in summaries:
            cumulative += float(s['net_pnl'])
            peak = max(peak, cumulative)
            dd = (peak - cumulative) / peak * 100
            max_dd = max(max_dd, dd)
        report.append(f"  Max Drawdown: {max_dd:.2f}%")
        report.append("")

        # Daily breakdown table
        report.append("📅 DAILY BREAKDOWN")
        report.append(f"  {'Date':<12} {'Trades':>7} {'W/L':>7} "
                      f"{'WR%':>6} {'Net PnL':>12} {'Cum PnL':>12} {'Balance':>12}")
        report.append("  " + "─" * 72)

        for s in summaries:
            net = float(s['net_pnl'])
            cum = float(s['cumulative_pnl'])
            bal = float(s['balance'])
            wr = float(s['win_rate'])
            w = int(s['winners'])
            l = int(s['losers'])
            emoji = "🟢" if net >= 0 else "🔴"

            report.append(
                f"  {s['date']} "
                f"{int(s['total_trades']):>7} "
                f"{w:>3}/{l:<3} "
                f"{wr:>5.1f}% "
                f"${net:>+11,.2f} "
                f"${cum:>+11,.2f} "
                f"${bal:>11,.2f} {emoji}"
            )

        report.append("  " + "─" * 72)
        report.append("")

        # Consistency check vs PolyM targets
        report.append("🎯 vs PolyM BENCHMARK")
        report.append(f"  PolyM Win Rate:  51.6%  | Bot: {agg_wr:.1f}%")
        report.append(f"  PolyM R:R:       1.20   | Bot: {avg_rr:.2f}")
        report.append(f"  PolyM Profit%:   91.8%  | Bot: "
                      f"{profit_days/len(summaries)*100:.1f}%")
        report.append("")
        report.append("═" * 60)

        return "\n".join(report)

    # ─── CSV Export ──────────────────────────────────────────

    def export_trades_csv(self, filepath: str = None) -> str:
        """Export all trades to CSV for audit."""
        trades = self.db.get_all_trades()
        if not trades:
            print("⚠️  No trades to export")
            return None

        if filepath is None:
            today = datetime.now(timezone.utc).strftime("%Y%m%d")
            filepath = os.path.join(self.output_dir, f"PolyM_trades_{today}.csv")

        # Define clean column order for export
        columns = [
            "id", "market_title", "asset", "side",
            "entry_price", "exit_price", "size_usd", "shares",
            "pnl", "status", "entry_reason", "exit_reason",
            "tp_target", "sl_target", "entry_time", "exit_time",
            "hold_minutes", "fill_type",
        ]

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()

            for trade in trades:
                row = {}
                for col in columns:
                    val = trade.get(col, "")
                    if isinstance(val, datetime):
                        row[col] = val.strftime("%Y-%m-%d %H:%M:%S")
                    elif val is None:
                        row[col] = ""
                    else:
                        row[col] = val
                writer.writerow(row)

        print(f"📁 Exported {len(trades)} trades → {filepath}")
        return filepath

    def export_daily_csv(self, filepath: str = None) -> str:
        """Export daily summaries to CSV."""
        summaries = self.db.get_daily_summaries()
        if not summaries:
            print("⚠️  No daily summaries to export")
            return None

        if filepath is None:
            today = datetime.now(timezone.utc).strftime("%Y%m%d")
            filepath = os.path.join(self.output_dir, f"PolyM_daily_{today}.csv")

        columns = [
            "date", "total_trades", "winners", "losers", "breakeven",
            "win_rate", "gross_profit", "gross_loss", "net_pnl",
            "cumulative_pnl", "avg_win", "avg_loss", "rr_ratio",
            "avg_hold_minutes", "balance", "best_trade", "worst_trade",
        ]

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for s in summaries:
                row = {col: s.get(col, "") for col in columns}
                writer.writerow(row)

        print(f"📁 Exported {len(summaries)} daily summaries → {filepath}")
        return filepath

    # ─── Console Print ───────────────────────────────────────

    def print_status(self):
        """Print current bot status to console."""
        stats = self.db.get_stats()
        balance = float(self.db.get_config("balance") or PAPER_INITIAL_BALANCE)
        pnl = float(stats['total_pnl'])
        roi = (balance - PAPER_INITIAL_BALANCE) / PAPER_INITIAL_BALANCE * 100

        print(f"\n💼 PolyM Bot Status")
        print(f"   Balance:    ${balance:,.2f}")
        print(f"   Total PnL:  ${pnl:+,.2f} ({roi:+.1f}%)")
        print(f"   Trades:     {stats['total_trades']} "
              f"({stats['open_trades']} open)")
        print(f"   Positions:  {stats['open_positions']} active")
        print()


# ─── CLI Entry Point ─────────────────────────────────────────

if __name__ == "__main__":
    dashboard = Dashboard()

    if "--csv" in sys.argv:
        dashboard.export_trades_csv()
        dashboard.export_daily_csv()

    elif "--all" in sys.argv:
        report = dashboard.full_report()
        print(report)

        # Also save to file
        filepath = os.path.join(
            dashboard.output_dir,
            f"full_report_{datetime.now(timezone.utc).strftime('%Y%m%d')}.txt"
        )
        with open(filepath, "w") as f:
            f.write(report)
        print(f"\n📁 Report saved → {filepath}")

    elif "--date" in sys.argv:
        idx = sys.argv.index("--date")
        if idx + 1 < len(sys.argv):
            d = date.fromisoformat(sys.argv[idx + 1])
            report = dashboard.daily_report(d)
            print(report)
        else:
            print("Usage: python dashboard.py --date 2026-04-01")

    else:
        # Default: today's report + status
        dashboard.print_status()
        report = dashboard.daily_report()
        print(report)
