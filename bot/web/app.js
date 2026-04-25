/**
 * app.js — 2m Strict Backtest Dashboard Client
 * Fetches data from Flask API and renders charts + tables.
 */

const API = '';  // Same origin
let currentPage = 1;
let currentFilter = 'all';
let equityData = [];
let dailyData = [];
let selectedFill = '80';

// ─── Init ───────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    loadOverview();
    loadEquity();
    loadDaily();
    loadSignals();
});

// ─── Overview ───────────────────────────────────────────────

async function loadOverview() {
    try {
        const res = await fetch(`${API}/api/overview`);
        const data = await res.json();

        if (data.error) {
            document.getElementById('period').textContent = data.error;
            return;
        }

        document.getElementById('period').textContent = data.period;
        document.getElementById('win-rate').textContent = data.win_rate + '%';
        document.getElementById('long-wr').textContent = data.long_win_rate + '%';
        document.getElementById('short-wr').textContent = data.short_win_rate + '%';
        document.getElementById('total-signals').textContent = data.total_signals.toLocaleString();
        document.getElementById('setups-24-7').textContent = data.setups_per_week_all.toFixed(1);
        document.getElementById('setups-ny').textContent = data.setups_per_week_ny.toFixed(1);

        // Color win rate
        colorMetric('win-rate', data.win_rate, 80);
        colorMetric('long-wr', data.long_win_rate, 80);
        colorMetric('short-wr', data.short_win_rate, 80);

        // Fill sensitivity cards
        for (const fp of ['80', '82', '85']) {
            const f = data.fill_sensitivity[fp];
            document.getElementById(`pnl-${fp}`).textContent = fmtPnl(f.final_pnl);
            document.getElementById(`roi-${fp}`).textContent = f.roi.toFixed(2) + '%';
            document.getElementById(`bal-${fp}`).textContent = '$' + f.final_balance.toLocaleString();
            document.getElementById(`dd-${fp}`).textContent = f.max_drawdown.toFixed(2) + '%';

            // Color PnL
            const pnlEl = document.getElementById(`pnl-${fp}`);
            pnlEl.className = f.final_pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
        }

        // Breakdown bars
        const total = data.total_longs + data.total_shorts;
        if (total > 0) {
            document.getElementById('long-bar').style.width = (data.total_longs / total * 100) + '%';
            document.getElementById('short-bar').style.width = (data.total_shorts / total * 100) + '%';
            document.getElementById('long-count').textContent = `${data.total_longs} (${(data.total_longs/total*100).toFixed(1)}%)`;
            document.getElementById('short-count').textContent = `${data.total_shorts} (${(data.total_shorts/total*100).toFixed(1)}%)`;
        }

        document.getElementById('run-status').textContent = '✓ Data loaded';

    } catch (err) {
        console.error('Overview load failed:', err);
        document.getElementById('period').textContent = 'Failed to load data';
    }
}

// ─── Equity Chart ───────────────────────────────────────────

async function loadEquity() {
    try {
        const res = await fetch(`${API}/api/equity`);
        equityData = await res.json();
        drawEquityChart();
    } catch (err) {
        console.error('Equity load failed:', err);
    }
}

function drawEquityChart() {
    const canvas = document.getElementById('equity-chart');
    if (!canvas || !equityData.length) return;
    const ctx = canvas.getContext('2d');

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = 300 * dpr;
    ctx.scale(dpr, dpr);

    const W = rect.width;
    const H = 300;
    const pad = { top: 20, right: 20, bottom: 40, left: 70 };

    ctx.clearRect(0, 0, W, H);

    const key = `bal_${selectedFill}`;
    const values = equityData.map(d => d[key]);
    const labels = equityData.map(d => d.date);

    const min = Math.min(...values) * 0.995;
    const max = Math.max(...values) * 1.005;

    const xScale = (i) => pad.left + (i / (values.length - 1)) * (W - pad.left - pad.right);
    const yScale = (v) => H - pad.bottom - ((v - min) / (max - min)) * (H - pad.top - pad.bottom);

    // Grid lines
    ctx.strokeStyle = 'rgba(255,255,255,0.05)';
    ctx.lineWidth = 1;
    for (let i = 0; i < 5; i++) {
        const y = pad.top + i * (H - pad.top - pad.bottom) / 4;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(W - pad.right, y);
        ctx.stroke();

        const val = max - (i / 4) * (max - min);
        ctx.fillStyle = 'rgba(255,255,255,0.3)';
        ctx.font = '11px Inter';
        ctx.textAlign = 'right';
        ctx.fillText('$' + val.toFixed(0), pad.left - 8, y + 4);
    }

    // Line + gradient fill
    const gradient = ctx.createLinearGradient(0, pad.top, 0, H - pad.bottom);
    const lastVal = values[values.length - 1];
    const startVal = values[0];
    if (lastVal >= startVal) {
        gradient.addColorStop(0, 'rgba(34, 197, 94, 0.3)');
        gradient.addColorStop(1, 'rgba(34, 197, 94, 0.0)');
        ctx.strokeStyle = '#22c55e';
    } else {
        gradient.addColorStop(0, 'rgba(239, 68, 68, 0.3)');
        gradient.addColorStop(1, 'rgba(239, 68, 68, 0.0)');
        ctx.strokeStyle = '#ef4444';
    }

    // Fill area
    ctx.beginPath();
    ctx.moveTo(xScale(0), H - pad.bottom);
    for (let i = 0; i < values.length; i++) {
        ctx.lineTo(xScale(i), yScale(values[i]));
    }
    ctx.lineTo(xScale(values.length - 1), H - pad.bottom);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    // Line
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let i = 0; i < values.length; i++) {
        if (i === 0) ctx.moveTo(xScale(i), yScale(values[i]));
        else ctx.lineTo(xScale(i), yScale(values[i]));
    }
    ctx.stroke();

    // X-axis labels (every ~30 days)
    ctx.fillStyle = 'rgba(255,255,255,0.3)';
    ctx.font = '10px Inter';
    ctx.textAlign = 'center';
    const step = Math.max(1, Math.floor(labels.length / 8));
    for (let i = 0; i < labels.length; i += step) {
        ctx.fillText(labels[i].substring(5), xScale(i), H - 10);
    }
}

function setFillTab(fill, el) {
    selectedFill = fill;
    document.querySelectorAll('.chart-tabs .tab').forEach(t => t.classList.remove('active'));
    el.classList.add('active');
    drawEquityChart();
}

// ─── Daily Win Rate Chart ───────────────────────────────────

async function loadDaily() {
    try {
        const res = await fetch(`${API}/api/daily`);
        dailyData = await res.json();
        drawWinRateChart();
    } catch (err) {
        console.error('Daily load failed:', err);
    }
}

function drawWinRateChart() {
    const canvas = document.getElementById('winrate-chart');
    if (!canvas || !dailyData.length) return;
    const ctx = canvas.getContext('2d');

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = 250 * dpr;
    ctx.scale(dpr, dpr);

    const W = rect.width;
    const H = 250;
    const pad = { top: 20, right: 20, bottom: 40, left: 50 };

    ctx.clearRect(0, 0, W, H);

    const barW = Math.max(2, (W - pad.left - pad.right) / dailyData.length - 1);
    const maxSignals = Math.max(...dailyData.map(d => d.signals), 1);

    for (let i = 0; i < dailyData.length; i++) {
        const d = dailyData[i];
        const x = pad.left + i * (W - pad.left - pad.right) / dailyData.length;
        const h = (d.signals / maxSignals) * (H - pad.top - pad.bottom);
        const y = H - pad.bottom - h;

        const wr = d.win_rate;
        if (wr >= 80) ctx.fillStyle = 'rgba(34, 197, 94, 0.8)';
        else if (wr >= 50) ctx.fillStyle = 'rgba(245, 158, 11, 0.7)';
        else ctx.fillStyle = 'rgba(239, 68, 68, 0.6)';

        ctx.fillRect(x, y, barW, h);
    }

    // 80% line (break-even for 80¢ fill)
    const y80 = H - pad.bottom - (0 * (H - pad.top - pad.bottom));
    ctx.strokeStyle = 'rgba(239, 68, 68, 0.4)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(pad.left, H - pad.bottom - (H - pad.top - pad.bottom) * 0.8);
    ctx.lineTo(W - pad.right, H - pad.bottom - (H - pad.top - pad.bottom) * 0.8);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = 'rgba(239,68,68,0.5)';
    ctx.font = '10px Inter';
    ctx.fillText('80% BE', W - pad.right - 40, H - pad.bottom - (H - pad.top - pad.bottom) * 0.8 - 4);

    // Y-axis
    ctx.fillStyle = 'rgba(255,255,255,0.3)';
    ctx.font = '10px Inter';
    ctx.textAlign = 'right';
    for (let i = 0; i <= 4; i++) {
        const val = Math.round(maxSignals * i / 4);
        const y = H - pad.bottom - (i / 4) * (H - pad.top - pad.bottom);
        ctx.fillText(val, pad.left - 8, y + 4);
    }
}

// ─── Signals Table ──────────────────────────────────────────

async function loadSignals(page = 1) {
    currentPage = page;
    try {
        let url = `${API}/api/signals?page=${page}&per_page=30`;
        if (currentFilter === 'LONG') url += '&type=LONG';
        else if (currentFilter === 'SHORT') url += '&type=SHORT';
        else if (currentFilter === 'wins') url += '&wins=true';
        else if (currentFilter === 'losses') url += '&wins=false';

        const res = await fetch(url);
        const data = await res.json();

        const tbody = document.getElementById('signals-body');
        tbody.innerHTML = '';

        for (const s of data.signals) {
            const tr = document.createElement('tr');
            const time = new Date(s.time).toISOString().replace('T', ' ').substring(0, 16);
            const typeClass = s.type === 'LONG' ? 'tag-long' : 'tag-short';
            const resultIcon = s.is_win ? '✅' : '❌';
            const pnlClass = s.pnl_80 >= 0 ? 'pnl-positive' : 'pnl-negative';

            tr.innerHTML = `
                <td>${time}</td>
                <td><span class="tag ${typeClass}">${s.type}</span></td>
                <td>$${s.btc_price.toLocaleString()}</td>
                <td>${s.volume_ratio}x</td>
                <td>${s.fivemin_dir}</td>
                <td>${resultIcon}</td>
                <td class="${pnlClass}">${fmtPnl(s.pnl_80)}</td>
                <td>${s.is_ny ? '<span class="tag tag-ny">NY</span>' : ''}</td>
            `;
            tbody.appendChild(tr);
        }

        // Pagination
        const pag = document.getElementById('pagination');
        pag.innerHTML = '';

        const prevBtn = document.createElement('button');
        prevBtn.textContent = '← Prev';
        prevBtn.disabled = page <= 1;
        prevBtn.onclick = () => loadSignals(page - 1);
        pag.appendChild(prevBtn);

        const info = document.createElement('span');
        info.style.color = 'var(--text-muted)';
        info.style.fontSize = '0.8rem';
        info.textContent = `Page ${data.page} / ${data.pages} (${data.total} signals)`;
        pag.appendChild(info);

        const nextBtn = document.createElement('button');
        nextBtn.textContent = 'Next →';
        nextBtn.disabled = page >= data.pages;
        nextBtn.onclick = () => loadSignals(page + 1);
        pag.appendChild(nextBtn);

    } catch (err) {
        console.error('Signals load failed:', err);
    }
}

function filterSignals(filter, el) {
    currentFilter = filter;
    document.querySelectorAll('.table-filters .tab').forEach(t => t.classList.remove('active'));
    el.classList.add('active');
    loadSignals(1);
}

// ─── Run Backtest ───────────────────────────────────────────

async function runBacktest() {
    const btn = document.getElementById('btn-run');
    const status = document.getElementById('run-status');
    btn.disabled = true;
    btn.textContent = '⏳ Running...';
    status.textContent = 'Running...';
    status.style.background = 'rgba(245, 158, 11, 0.1)';
    status.style.color = '#f59e0b';

    try {
        await fetch(`${API}/api/run-backtest`, { method: 'POST' });
        status.textContent = '⏳ Backtest started — refresh in a few minutes';

        // Poll for completion
        let attempts = 0;
        const poll = setInterval(async () => {
            attempts++;
            try {
                const res = await fetch(`${API}/api/overview`);
                const data = await res.json();
                if (!data.error && data.total_signals > 0) {
                    clearInterval(poll);
                    btn.disabled = false;
                    btn.textContent = '▶ Run Backtest';
                    status.textContent = '✓ Complete';
                    status.style.background = 'rgba(34, 197, 94, 0.1)';
                    status.style.color = '#22c55e';
                    loadOverview();
                    loadEquity();
                    loadDaily();
                    loadSignals();
                }
            } catch (e) {}
            if (attempts > 60) {
                clearInterval(poll);
                btn.disabled = false;
                btn.textContent = '▶ Run Backtest';
                status.textContent = '⚠ Timeout — check logs';
            }
        }, 10000);

    } catch (err) {
        btn.disabled = false;
        btn.textContent = '▶ Run Backtest';
        status.textContent = '❌ Failed';
        status.style.color = '#ef4444';
    }
}

// ─── Helpers ────────────────────────────────────────────────

function fmtPnl(val) {
    const prefix = val >= 0 ? '+$' : '-$';
    return prefix + Math.abs(val).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function colorMetric(id, value, threshold) {
    const el = document.getElementById(id);
    if (value >= threshold) el.classList.add('positive');
    else el.classList.add('negative');
}

// Redraw charts on resize
window.addEventListener('resize', () => {
    drawEquityChart();
    drawWinRateChart();
});
