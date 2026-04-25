/**
 * app.js — K9 Dashboard Frontend Logic
 * ═══════════════════════════════════════════
 * Fetches data from Flask API and renders:
 *   - Profile stats
 *   - Equity curve chart (Chart.js)
 *   - Positions table (active / closed)
 *   - Activity log
 *   - Benchmark comparison
 *
 * Auto-refreshes every 30 seconds.
 */

// ─── Configuration ──────────────────────────────────────────
const API_BASE = "";  // Same origin
const REFRESH_INTERVAL = 30_000;  // 30s
const INITIAL_BALANCE = 3_000;

// ─── State ──────────────────────────────────────────────────
let equityChart = null;
let currentTab = "positions";
let currentFilter = "active";
let currentLogLevel = "";  // empty = ALL
let refreshTimer = null;

// ─── Initialization ─────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    initTabsAndFilters();
    fetchAll();
    refreshTimer = setInterval(fetchAll, REFRESH_INTERVAL);
});

function initTabsAndFilters() {
    // Tab switching
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentTab = btn.dataset.tab;
            togglePanels();
        });
    });

    // Filter switching (Active / Closed)
    document.querySelectorAll(".filter-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentFilter = btn.dataset.filter;
            fetchPositions();
            fetchTrades();
        });
    });

    // Time filter buttons (1D/1W/1M/ALL)
    document.querySelectorAll(".time-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".time-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            fetchEquityChart(btn.dataset.range);
        });
    });

    // Search
    const searchInput = document.getElementById("search-positions");
    if (searchInput) {
        searchInput.addEventListener("input", () => filterTableBySearch(searchInput.value));
    }

    // Log level filter buttons
    document.querySelectorAll(".log-level-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".log-level-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentLogLevel = btn.dataset.level;
            fetchLogs();
        });
    });
}

function togglePanels() {
    const posPanel = document.getElementById("positions-panel");
    const actPanel = document.getElementById("activity-panel");
    const logPanel = document.getElementById("logs-panel");
    const filterBar = document.querySelector(".filter-bar");

    posPanel.classList.add("hidden");
    actPanel.classList.add("hidden");
    logPanel.classList.add("hidden");

    if (currentTab === "positions") {
        posPanel.classList.remove("hidden");
        if (filterBar) filterBar.classList.remove("hidden");
    } else if (currentTab === "activity") {
        actPanel.classList.remove("hidden");
        if (filterBar) filterBar.classList.remove("hidden");
    } else if (currentTab === "logs") {
        logPanel.classList.remove("hidden");
        if (filterBar) filterBar.classList.add("hidden");
        fetchLogs();
    }
}

// ─── Fetch All Data ─────────────────────────────────────────
async function fetchAll() {
    try {
        await Promise.all([
            fetchStats(),
            fetchStatus(),
            fetchPositions(),
            fetchTrades(),
            fetchEquityChart(),
            fetchBenchmark(),
        ]);
        updateLastUpdated();
    } catch (err) {
        console.error("Fetch error:", err);
    }
}

// ─── Stats ──────────────────────────────────────────────────
async function fetchStats() {
    const data = await apiGet("/api/stats");
    if (!data) return;

    setText("stat-balance", formatUSD(data.balance, 0));
    setText("stat-best-trade", formatUSD(data.best_trade, 0));
    setText("stat-total-trades", formatNumber(data.total_trades));

    // PnL header
    const pnlVal = data.total_pnl;
    const pnlEl = document.getElementById("pnl-big-value");
    const arrowEl = document.getElementById("pnl-arrow");
    if (pnlEl) {
        pnlEl.textContent = formatUSD(pnlVal, 2);
        pnlEl.className = "pnl-big-value " + (pnlVal >= 0 ? "profit" : "loss");
    }
    if (arrowEl) {
        arrowEl.textContent = pnlVal >= 0 ? "▲" : "▼";
        arrowEl.className = "pnl-arrow " + (pnlVal >= 0 ? "" : "loss");
    }

    // Join date
    const joinEl = document.getElementById("join-date");
    if (joinEl) {
        if (data.started_at) {
            try {
                const d = new Date(data.started_at);
                const options = { year: 'numeric', month: 'short', day: 'numeric' };
                joinEl.textContent = `Started ${d.toLocaleDateString('en-US', options)} · ${formatNumber(data.total_trades)} trades`;
            } catch {
                joinEl.textContent = `Paper Trading · ${formatNumber(data.total_trades)} trades`;
            }
        } else {
            joinEl.textContent = `Paper Trading · ${formatNumber(data.total_trades)} trades`;
        }
    }
}

// ─── Bot Status ─────────────────────────────────────────────
async function fetchStatus() {
    const data = await apiGet("/api/status");
    if (!data) return;

    const badge = document.getElementById("bot-status-badge");
    if (!badge) return;

    let lastSeenStr = "";
    if (data.last_seen) {
        try {
            const diff = Math.floor((Date.now() - new Date(data.last_seen)) / 60000);
            lastSeenStr = diff < 1 ? " · just now" : ` · ${diff}m ago`;
        } catch {}
    }

    if (data.running) {
        badge.className = "status-badge online";
        badge.querySelector(".status-text").textContent = "Running" + lastSeenStr;
    } else {
        badge.className = "status-badge offline";
        badge.querySelector(".status-text").textContent = lastSeenStr
            ? "Offline" + lastSeenStr
            : "Offline";
    }
}

// ─── Positions ──────────────────────────────────────────────
async function fetchPositions() {
    const data = await apiGet("/api/positions");
    const body = document.getElementById("positions-body");
    const emptyState = document.getElementById("positions-empty");
    if (!body) return;

    // Clear previous rows (keep empty state)
    body.querySelectorAll(".position-row").forEach(r => r.remove());

    if (!data || data.length === 0) {
        if (emptyState) emptyState.classList.remove("hidden");
        return;
    }

    if (emptyState) emptyState.classList.add("hidden");

    // Filter by active/closed
    let filtered = data;
    if (currentFilter === "active") {
        filtered = data.filter(p => p.status === "OPEN");
    } else {
        filtered = data.filter(p => p.status !== "OPEN");
    }

    for (const pos of filtered) {
        const row = createPositionRow(pos);
        body.appendChild(row);
    }
}

function createPositionRow(pos) {
    const row = document.createElement("div");
    row.className = "position-row";

    const asset = (pos.asset || "").toUpperCase();
    const iconClass = getAssetIconClass(asset);
    const side = pos.side || "YES";
    const sideClass = side.toUpperCase() === "YES" ? "yes" : "no";
    const avgPrice = pos.entry_price || 0;
    const currentPrice = pos.current_price || avgPrice;
    const value = pos.size_usd || 0;
    const pnl = pos.unrealized_pnl || 0;
    const pnlPct = pos.pnl_percent || 0;
    const shares = pos.shares || 0;

    row.innerHTML = `
        <div class="market-cell">
            <div class="market-icon ${iconClass}">${asset.slice(0,3)}</div>
            <div class="market-details">
                <div class="market-name" title="${pos.market_title || ''}">${pos.market_title || "Unknown Market"}</div>
                <div class="market-meta">
                    <span class="side-badge ${sideClass}">${side} ${formatPrice(avgPrice)}</span>
                    <span class="shares-text">${formatNumber(shares)} shares</span>
                </div>
            </div>
        </div>
        <div class="avg-cell">${formatPrice(avgPrice)}</div>
        <div class="current-cell">${formatPrice(currentPrice)}</div>
        <div class="value-cell">
            <span class="value-main">${formatUSD(value)}</span>
            <span class="value-pnl ${pnl >= 0 ? 'profit' : 'loss'}">${formatUSD(pnl)} (${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%)</span>
        </div>
    `;

    return row;
}

// ─── Trades / Activity ──────────────────────────────────────
async function fetchTrades() {
    const tab = currentFilter === "active" ? "active" : "closed";
    const data = await apiGet(`/api/trades?tab=${tab}&per_page=50`);
    const body = document.getElementById("activity-body");
    const emptyState = document.getElementById("activity-empty");
    if (!body) return;

    body.querySelectorAll(".activity-row").forEach(r => r.remove());

    const trades = data?.trades || [];
    if (trades.length === 0) {
        if (emptyState) emptyState.classList.remove("hidden");
        return;
    }

    if (emptyState) emptyState.classList.add("hidden");

    for (const t of trades) {
        const row = createActivityRow(t);
        body.appendChild(row);
    }
}

function createActivityRow(t) {
    const row = document.createElement("div");
    row.className = "activity-row";

    const pnl = t.pnl || 0;
    const statusClass = getStatusClass(t.exit_reason || t.status);

    row.innerHTML = `
        <div class="market-cell">
            <div class="market-icon ${getAssetIconClass(t.asset)}">${(t.asset || "?").slice(0,3)}</div>
            <div class="market-details">
                <div class="market-name" title="${t.market_title || ''}">${t.market_title || "Unknown"}</div>
            </div>
        </div>
        <div class="side-cell">
            <span class="side-badge ${(t.side || '').toLowerCase() === 'yes' ? 'yes' : 'no'}">${t.side || "-"}</span>
        </div>
        <div class="prices-cell">${formatPrice(t.entry_price)} → ${formatPrice(t.exit_price)}</div>
        <div class="size-cell">${formatUSD(t.size_usd, 0)}</div>
        <div class="pnl-cell">
            <span class="value-pnl ${pnl >= 0 ? 'profit' : 'loss'}">${formatUSD(pnl)}</span>
        </div>
        <div class="status-cell">
            <span class="status-badge-small ${statusClass}">${t.exit_reason || t.status || "-"}</span>
        </div>
        <div class="time-cell" style="color: var(--text-secondary); font-size: 0.78rem;">
            ${t.hold_minutes ? t.hold_minutes.toFixed(0) + "m" : "-"}
        </div>
    `;
    return row;
}

// ─── Equity Chart ───────────────────────────────────────────
async function fetchEquityChart(range = "all") {
    const data = await apiGet("/api/equity");
    if (!data || data.length === 0) {
        // Show flat line if no data
        renderEquityChart(
            ["Start", "Now"],
            [INITIAL_BALANCE, INITIAL_BALANCE],
            [0, 0]
        );
        return;
    }

    // Filter by time range
    let filtered = data;
    if (range !== "all" && data.length > 1) {
        const now = new Date();
        let cutoff;
        if (range === "1d") cutoff = new Date(now - 86400000);
        else if (range === "1w") cutoff = new Date(now - 7 * 86400000);
        else if (range === "1m") cutoff = new Date(now - 30 * 86400000);
        if (cutoff) {
            filtered = data.filter(d => {
                if (d.date === "Start") return true;
                try { return new Date(d.date) >= cutoff; } catch { return true; }
            });
        }
    }

    const labels = filtered.map(d => d.date === "Start" ? "Start" : formatDateShort(d.date));
    const balances = filtered.map(d => d.balance);
    const pnls = filtered.map(d => d.pnl);

    renderEquityChart(labels, balances, pnls);
}

function renderEquityChart(labels, balances, pnls) {
    const ctx = document.getElementById("equity-chart");
    if (!ctx) return;

    if (equityChart) {
        equityChart.destroy();
    }

    // Compute gradient
    const gradient = ctx.getContext("2d").createLinearGradient(0, 0, 0, ctx.clientHeight || 140);
    gradient.addColorStop(0, "rgba(59, 130, 246, 0.25)");
    gradient.addColorStop(1, "rgba(59, 130, 246, 0.01)");

    equityChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets: [{
                label: "Profit/Loss",
                data: pnls,
                borderColor: "#3b82f6",
                backgroundColor: gradient,
                borderWidth: 2,
                fill: true,
                tension: 0.35,
                pointRadius: 0,
                pointHoverRadius: 5,
                pointHoverBackgroundColor: "#3b82f6",
                pointHoverBorderColor: "#fff",
                pointHoverBorderWidth: 2,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: "index",
                intersect: false,
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    enabled: true,
                    backgroundColor: "#1c2128",
                    borderColor: "#30363d",
                    borderWidth: 1,
                    titleFont: { family: "'Inter'", size: 12, weight: "600" },
                    bodyFont: { family: "'Inter'", size: 12 },
                    padding: 10,
                    cornerRadius: 8,
                    displayColors: false,
                    callbacks: {
                        title: function(context) {
                            return context[0].label;
                        },
                        label: function(context) {
                            const idx = context.dataIndex;
                            const bal = balances[idx];
                            const pnl = pnls[idx];
                            const sign = pnl >= 0 ? "+" : "";
                            return [
                                `P/L: ${sign}${formatUSD(pnl)}`,
                                `Balance: ${formatUSD(bal)}`,
                            ];
                        },
                        labelTextColor: function(context) {
                            const idx = context.dataIndex;
                            return pnls[idx] >= 0 ? "#00d26a" : "#ff4757";
                        },
                    },
                },
            },
            scales: {
                x: {
                    display: true,
                    grid: { display: false },
                    ticks: {
                        color: "#6e7681",
                        font: { family: "'Inter'", size: 10 },
                        maxRotation: 0,
                        maxTicksLimit: 8,
                    },
                    border: { display: false },
                },
                y: {
                    display: true,
                    position: "right",
                    suggestedMin: -100,  // Give some buffer around zero
                    suggestedMax: 100,
                    grid: {
                        color: "rgba(48, 54, 61, 0.3)",
                        drawBorder: false,
                        zeroLineColor: "rgba(255, 255, 255, 0.2)",
                        zeroLineWidth: 1
                    },
                    ticks: {
                        color: "#6e7681",
                        font: { family: "'Inter'", size: 10 },
                        callback: function(v) {
                            if (v === 0) return "$0";
                            const sign = v > 0 ? "+" : "-";
                            return sign + "$" + formatCompact(Math.abs(v));
                        }
                    },
                    border: { display: false },
                },
            },
        },
    });
}

// ─── Live Logs ────────────────────────────────────────
async function fetchLogs() {
    const levelParam = currentLogLevel ? `&level=${currentLogLevel}` : "";
    const data = await apiGet(`/api/logs?limit=80${levelParam}`);
    const body = document.getElementById("logs-body");
    const emptyState = document.getElementById("logs-empty");
    if (!body) return;

    // Remove old log rows
    body.querySelectorAll(".log-row").forEach(r => r.remove());

    if (!data || data.length === 0) {
        if (emptyState) emptyState.classList.remove("hidden");
        return;
    }
    if (emptyState) emptyState.classList.add("hidden");

    // Insert newest first
    for (const log of data) {
        const row = createLogRow(log);
        body.insertBefore(row, body.firstChild);
    }
}

function createLogRow(log) {
    const row = document.createElement("div");
    const level = (log.level || "INFO").toUpperCase();
    row.className = `log-row log-level-${level.toLowerCase()}`;

    const time = log.time ? new Date(log.time).toLocaleTimeString("en-US", {
        hour: "2-digit", minute: "2-digit", second: "2-digit"
    }) : "--:--";

    const levelEmoji = {
        HEARTBEAT: "💓", TRADE: "📈", WARNING: "⚠️", ERROR: "🔴",
        CRITICAL: "🚨", INFO: "ℹ️", DISCREPANCY: "⚡"
    }[level] || "•";

    // Format data payload if present
    let dataStr = "";
    if (log.data && typeof log.data === "object" && Object.keys(log.data).length > 0) {
        const parts = Object.entries(log.data)
            .filter(([k]) => !['traceback'].includes(k))
            .map(([k, v]) => `<span class="log-key">${k}:</span><span class="log-val">${typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(4)) : v}</span>`);
        if (parts.length > 0) dataStr = `<div class="log-data">${parts.join(" &nbsp;|&nbsp; ")}</div>`;
    }

    row.innerHTML = `
        <div class="log-header">
            <span class="log-time">${time}</span>
            <span class="log-level-tag ${level.toLowerCase()}">${levelEmoji} ${level}</span>
            <span class="log-module">${log.module || "?"}</span>
            <span class="log-message">${log.message || ""}</span>
        </div>
        ${dataStr}
    `;
    return row;
}

// ─── Benchmark ──────────────────────────────────────────────
async function fetchBenchmark() {
    const data = await apiGet("/api/benchmark");
    if (!data) return;

    const bot = data.bot || {};
    const k9 = data.k9_benchmark || {};

    setText("m-winrate", `${bot.win_rate || 0}%`);
    setText("m-rr", `${bot.rr_ratio || 0}`);
    setText("m-profitdays", `${bot.profit_days_pct || 0}%`);
    setText("m-accuracy", `${k9.accuracy_match || 91}%`);

    // Animate bars
    animateBar("bar-winrate", Math.min((bot.win_rate || 0) / 100 * 100, 100));
    animateBar("bar-rr", Math.min((bot.rr_ratio || 0) / 2 * 100, 100));
    animateBar("bar-profitdays", Math.min((bot.profit_days_pct || 0), 100));
    animateBar("bar-accuracy", k9.accuracy_match || 91);
}

// ─── Utilities ──────────────────────────────────────────────
async function apiGet(path) {
    try {
        const resp = await fetch(API_BASE + path);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
    } catch (err) {
        console.warn(`API ${path}:`, err.message);
        return null;
    }
}

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function formatUSD(value, decimals = 2) {
    if (value === null || value === undefined) return "$0";
    const v = Number(value);
    if (isNaN(v)) return "$0";
    const prefix = v >= 0 ? "$" : "-$";
    const abs = Math.abs(v);
    if (decimals === 0) {
        if (abs >= 1_000_000) return prefix + (abs / 1_000_000).toFixed(1) + "M";
        if (abs >= 1_000) return prefix + (abs / 1_000).toFixed(1) + "K";
        return prefix + abs.toFixed(0);
    }
    return prefix + abs.toLocaleString("en-US", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });
}

function formatPrice(v) {
    if (!v && v !== 0) return "-";
    const cents = (Number(v) * 100).toFixed(0);
    return cents + "¢";
}

function formatNumber(n) {
    if (!n && n !== 0) return "0";
    const v = Number(n);
    if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + "M";
    if (v >= 1_000) return (v / 1_000).toFixed(1) + "K";
    return v.toLocaleString("en-US");
}

function formatCompact(v) {
    if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + "M";
    if (v >= 1_000) return (v / 1_000).toFixed(1) + "K";
    return v.toFixed(0);
}

function formatDateShort(dateStr) {
    try {
        const d = new Date(dateStr);
        return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    } catch {
        return dateStr;
    }
}

function getAssetIconClass(asset) {
    const a = (asset || "").toLowerCase();
    if (a === "btc" || a === "bitcoin") return "btc";
    if (a === "eth" || a === "ethereum") return "eth";
    if (a === "sol" || a === "solana") return "sol";
    if (a === "xrp") return "xrp";
    return "default";
}

function getStatusClass(reason) {
    if (!reason) return "";
    const r = reason.toUpperCase();
    if (r.includes("TP") || r.includes("PROFIT")) return "tp";
    if (r.includes("SL") || r.includes("STOP") || r.includes("LOSS")) return "sl";
    if (r.includes("TIMEOUT") || r.includes("EXPIR")) return "timeout";
    if (r === "OPEN") return "open";
    return "";
}

function animateBar(id, pct) {
    const el = document.getElementById(id);
    if (el) {
        setTimeout(() => {
            el.style.width = Math.max(0, Math.min(pct, 100)) + "%";
        }, 300);
    }
}

function filterTableBySearch(query) {
    const q = query.toLowerCase().trim();
    const rows = document.querySelectorAll(".position-row, .activity-row");
    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(q) ? "" : "none";
    });
}

function updateLastUpdated() {
    const el = document.getElementById("last-updated");
    if (el) {
        const now = new Date();
        el.textContent = `Last updated: ${now.toLocaleTimeString()}`;
    }
}
