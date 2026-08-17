/**
 * script.js — NIFTY Market Analysis Dashboard
 * Handles API calls, DOM rendering, animations, tab switching,
 * and intraday prediction rendering.
 * News items are sorted by published date/time (most recent first).
 */

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// State
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

let analysisData = null;
let currentFilter = "ALL";
let activeTab = "btst";

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// DOM Refs
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const btnAnalyze = document.getElementById("btn-analyze");
const btnAnalyzeText = document.getElementById("btn-analyze-text");
const loadingOverlay = document.getElementById("loading-overlay");
const loadingText = document.getElementById("loading-text");
const loadingSubtext = document.getElementById("loading-subtext");
const dashboard = document.getElementById("dashboard");
const errorContainer = document.getElementById("error-container");

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Tab Navigation
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function initTabs() {
    document.querySelectorAll(".tab-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            const tab = btn.dataset.tab;
            switchTab(tab);
        });
    });
}

function switchTab(tab) {
    activeTab = tab;

    // Update buttons
    document.querySelectorAll(".tab-btn").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.tab === tab);
    });

    // Update content
    document.querySelectorAll(".tab-content").forEach((content) => {
        content.classList.toggle("active", content.id === `content-${tab}`);
    });

    if (tab === "history") {
        loadHistoryList();
    }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Loading Messages (cycle through while scraping)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const LOADING_MESSAGES = [
    { text: "Connecting to news sources...", sub: "Fetching RSS feeds from Google News, Livemint, Economic Times" },
    { text: "Scraping Indian market news...", sub: "Collecting NIFTY, Sensex, RBI, and market updates" },
    { text: "Fetching global macro data...", sub: "US Fed, inflation, crude oil, and geopolitical news" },
    { text: "Scanning corporate earnings...", sub: "Banking, IT, Pharma, and other sector results" },
    { text: "Classifying news by sector...", sub: "Banking, IT, Pharma, Auto, Energy, FMCG, Metals..." },
    { text: "Running sentiment analysis...", sub: "Evaluating bullish vs bearish signals with weighted scoring" },
    { text: "Generating intraday prediction...", sub: "Analyzing patterns, volatility, and market phase for today" },
    { text: "Computing BTST prediction...", sub: "Generating GAP UP / GAP DOWN / FLAT forecast" },
    { text: "Finalising analysis...", sub: "Preparing your market intelligence report" },
];

let loadingInterval = null;

function startLoadingMessages() {
    let idx = 0;
    updateLoadingMessage(idx);
    loadingInterval = setInterval(() => {
        idx = (idx + 1) % LOADING_MESSAGES.length;
        updateLoadingMessage(idx);
    }, 3000);
}

function updateLoadingMessage(idx) {
    if (loadingText) loadingText.textContent = LOADING_MESSAGES[idx].text;
    if (loadingSubtext) loadingSubtext.textContent = LOADING_MESSAGES[idx].sub;
}

function stopLoadingMessages() {
    if (loadingInterval) {
        clearInterval(loadingInterval);
        loadingInterval = null;
    }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Date Parsing & News Sorting
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/**
 * Parse a date string like "08 Apr 2026, 10:30 AM" into a Date object.
 * Falls back to current time if parsing fails.
 */
function parseNewsDate(dateStr) {
    if (!dateStr) return new Date(0);
    try {
        // Strip commas for strict WebKit/Safari Date parser compatibility
        const cleaned = String(dateStr).replace(/,/g, "");
        const d = new Date(cleaned);
        if (!isNaN(d.getTime())) return d;
    } catch (e) {}
    try {
        const d = new Date(dateStr);
        if (!isNaN(d.getTime())) return d;
    } catch (e) {}
    return new Date(0);
}

/**
 * Sort news items by published_date descending (most recent first).
 */
function sortNewsByDate(newsArray) {
    if (!newsArray || newsArray.length === 0) return newsArray;
    return [...newsArray].sort((a, b) => {
        const dateA = parseNewsDate(a.published_date);
        const dateB = parseNewsDate(b.published_date);
        const timeA = dateA ? dateA.getTime() || 0 : 0;
        const timeB = dateB ? dateB.getTime() || 0 : 0;
        return timeB - timeA;
    });
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// API Call
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async function startAnalysis() {
    // UI: show loading
    btnAnalyze.disabled = true;
    btnAnalyzeText.textContent = "Analysing...";
    dashboard.classList.remove("active");
    errorContainer.innerHTML = "";
    loadingOverlay.classList.add("active");
    startLoadingMessages();

    try {
        const response = await fetch("/api/analyze", {
            method: "POST",
            headers: {
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ timestamp: Date.now() }),
        });

        const json = await response.json();

        if (json.status === "error") {
            throw new Error(json.message || "Unknown server error");
        }

        analysisData = json.data;

        // Sort all news arrays by date (most recent first)
        if (analysisData.all_news) {
            analysisData.all_news = sortNewsByDate(analysisData.all_news);
        }
        if (analysisData.major_news) {
            analysisData.major_news = sortNewsByDate(analysisData.major_news);
        }

        renderDashboard(analysisData);
    } catch (err) {
        console.error("Analysis failed:", err);
        let msg = err.message || "Unknown error";
        if (msg.includes("pattern") || msg.includes("Failed to fetch") || msg.includes("NetworkError") || msg.includes("Load failed")) {
            msg = "Render free server cold-start or network timeout. Please tap 'Re-Analyse Market' again — the instance is now warm!";
        }
        renderError(msg);
    } finally {
        stopLoadingMessages();
        loadingOverlay.classList.remove("active");
        btnAnalyze.disabled = false;
        btnAnalyzeText.textContent = "Re-Analyse Market";
    }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Render Dashboard
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderDashboard(data) {
    analysisData = data;
    // BTST Tab
    renderPredictionHero(data);
    renderInfoStrip(data);
    renderScoreBar(data);
    renderSummary(data);
    renderSignalsTable(data);
    renderEventRisk(data);
    renderKeyDrivers(data);
    renderFactors(data);
    renderSectorSummary(data);

    // Intraday Tab
    renderIntradayPrediction(data);

    // Common: News
    renderTopBullishBearishNews(data);
    renderNewsCards(data);

    dashboard.classList.add("active");

    // Scroll to dashboard
    setTimeout(() => {
        dashboard.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 200);
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Prediction Hero (BTST)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderPredictionHero(data) {
    const pred = data.prediction;
    const conf = data.confidence;
    const btst = data.btst_bias;

    // Prediction card
    const predCard = document.getElementById("prediction-card");
    const predValue = document.getElementById("prediction-value");
    const predSentiment = document.getElementById("prediction-sentiment");

    predCard.className = "card prediction-card " + predClassKey(pred);
    predValue.className = "prediction-value " + predClassKey(pred);
    predValue.textContent = pred;

    const sentimentEmoji = { BULLISH: "🟢", BEARISH: "🔴", MIXED: "🟡" };
    predSentiment.textContent = `${sentimentEmoji[data.news_sentiment] || "⚪"} Sentiment: ${data.news_sentiment}`;

    // Confidence gauge
    animateGauge(conf, "gauge-fill", "gauge-number");

    // BTST badge
    const btstBadge = document.getElementById("btst-badge");
    const btstIcon = document.getElementById("btst-icon");
    btstBadge.className = "btst-badge " + btstClassKey(btst);
    btstBadge.querySelector("span:last-child").textContent = btst;

    if (btst === "BUY CE") {
        btstIcon.textContent = "📈";
    } else if (btst === "BUY PE") {
        btstIcon.textContent = "📉";
    } else {
        btstIcon.textContent = "⏸️";
    }
}

function predClassKey(pred) {
    if (pred === "GAP UP") return "gap-up";
    if (pred === "GAP DOWN") return "gap-down";
    return "flat";
}

function btstClassKey(btst) {
    if (btst === "BUY CE") return "buy-ce";
    if (btst === "BUY PE") return "buy-pe";
    return "no-trade";
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Confidence Gauge Animation
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function animateGauge(value, fillId, numberId) {
    const gaugeFill = document.getElementById(fillId);
    const gaugeNumber = document.getElementById(numberId);
    const circumference = 2 * Math.PI * 54; // radius = 54

    // Set initial state
    gaugeFill.style.strokeDasharray = circumference;
    gaugeFill.style.strokeDashoffset = circumference;

    // Determine color
    let color;
    if (value >= 65) color = "var(--bullish)";
    else if (value >= 40) color = "var(--neutral)";
    else color = "var(--bearish)";

    gaugeFill.style.stroke = color;

    // Animate after a small delay
    setTimeout(() => {
        const offset = circumference - (value / 100) * circumference;
        gaugeFill.style.strokeDashoffset = offset;
    }, 100);

    // Animate number
    animateNumber(gaugeNumber, 0, value, 1200);
}

function animateNumber(element, start, end, duration) {
    const startTime = performance.now();
    function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3); // easeOutCubic
        const current = Math.round(start + (end - start) * eased);
        element.textContent = current;
        if (progress < 1) requestAnimationFrame(update);
    }
    requestAnimationFrame(update);
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Info Strip
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderInfoStrip(data) {
    const container = document.getElementById("info-strip");
    const scores = data.scores;
    const netClass = scores.net_score >= 0 ? "positive" : "negative";
    const netPrefix = scores.net_score >= 0 ? "+" : "";

    container.innerHTML = `
        <div class="info-chip">
            🟢 Bullish Score: <span class="info-chip__value positive">${scores.total_bullish}</span>
        </div>
        <div class="info-chip">
            🔴 Bearish Score: <span class="info-chip__value negative">${scores.total_bearish}</span>
        </div>
        <div class="info-chip">
            📊 Net Score: <span class="info-chip__value ${netClass}">${netPrefix}${scores.net_score}</span>
        </div>
        <div class="info-chip">
            📰 News Analyzed: <span class="info-chip__value">${data.total_news_analyzed}</span>
        </div>
        <div class="info-chip">
            🕐 ${data.analysis_timestamp}
        </div>
    `;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Score Bar
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderScoreBar(data) {
    const scores = data.scores;
    const total = scores.total_bullish + scores.total_bearish;
    const bullPct = total > 0 ? (scores.total_bullish / total) * 100 : 50;
    const bearPct = total > 0 ? (scores.total_bearish / total) * 100 : 50;

    const bullBar = document.getElementById("score-bar-bull");
    const bearBar = document.getElementById("score-bar-bear");
    const bullLabel = document.getElementById("score-label-bull");
    const bearLabel = document.getElementById("score-label-bear");

    // Animate after a small delay
    setTimeout(() => {
        bullBar.style.width = bullPct + "%";
        bearBar.style.width = bearPct + "%";
    }, 300);

    bullLabel.textContent = `Bullish ${Math.round(bullPct)}%`;
    bearLabel.textContent = `Bearish ${Math.round(bearPct)}%`;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Summary
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderSummary(data) {
    document.getElementById("summary-text").textContent = data.final_summary;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Live Microstructure Signals Table (GIFT Nifty, FII, DII, VIX, PCR, Global)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderSignalsTable(data) {
    const tbody = document.getElementById("signals-table-body");
    if (!tbody) return;

    const ms = data.market_signals || data.market_signals_detail || {};
    const fiiDii = data.fii_dii || {};
    const globalMkts = ms.global_markets || {};

    const rows = [];

    // 1. GIFT Nifty
    const giftPct = ms.gift_nifty_change_pct;
    if (giftPct !== null && giftPct !== undefined) {
        const valStr = giftPct >= 0 ? `+${giftPct.toFixed(2)}%` : `${giftPct.toFixed(2)}%`;
        const cls = giftPct > 0.2 ? "positive" : (giftPct < -0.2 ? "negative" : "neutral");
        const status = giftPct > 0.2 ? "🟢 GAP UP (Positive Opening Bias)" : (giftPct < -0.2 ? "🔴 GAP DOWN (Negative Opening Bias)" : "🟡 FLAT (No Directional Gap)");
        rows.push({ name: "🎁 GIFT Nifty", value: valStr, category: "Overnight Gap Indicator", status, cls });
    }

    // 2. FII Flow
    const fiiNet = fiiDii.fii_net !== undefined ? fiiDii.fii_net : (fiiDii.fii_net_crores !== undefined ? fiiDii.fii_net_crores : (fiiDii.fii ? fiiDii.fii.net : null));
    if (fiiNet !== null && fiiNet !== undefined) {
        const valStr = `₹${formatCrore(fiiNet)} Cr`;
        const cls = fiiNet >= 0 ? "positive" : "negative";
        const status = fiiNet >= 0 ? "🟢 NET BUYERS (Foreign Institutional Inflows)" : "🔴 NET SELLERS (Foreign Institutional Outflows)";
        rows.push({ name: "🏦 FII Cash Flow", value: valStr, category: "Institutional Flow", status, cls });
    }

    // 3. DII Flow
    const diiNet = fiiDii.dii_net !== undefined ? fiiDii.dii_net : (fiiDii.dii_net_crores !== undefined ? fiiDii.dii_net_crores : (fiiDii.dii ? fiiDii.dii.net : null));
    if (diiNet !== null && diiNet !== undefined) {
        const valStr = `₹${formatCrore(diiNet)} Cr`;
        const cls = diiNet >= 0 ? "positive" : "negative";
        const status = diiNet >= 0 ? "🟢 NET BUYERS (Domestic Institutional Support)" : "🔴 NET SELLERS (Domestic Outflows)";
        rows.push({ name: "🏛️ DII Cash Flow", value: valStr, category: "Institutional Flow", status, cls });
    }

    // 4. India VIX
    const vix = ms.india_vix;
    const vixChg = ms.india_vix_change_pct;
    if (vix !== null && vix !== undefined) {
        const chgStr = vixChg !== null && vixChg !== undefined ? ` (${vixChg >= 0 ? "+" : ""}${vixChg.toFixed(2)}%)` : "";
        const valStr = `${vix.toFixed(2)}${chgStr}`;
        const cls = vix < 16 ? "positive" : (vix > 20 ? "negative" : "neutral");
        const status = vix < 16 ? "🟢 LOW VOLATILITY (Safe Option Premium Regime)" : (vix > 20 ? "🔴 HIGH VOLATILITY (Extreme Premium Risk)" : "🟡 MODERATE VOLATILITY");
        rows.push({ name: "📈 India VIX", value: valStr, category: "Volatility Index", status, cls });
    }

    // 5. Put-Call Ratio
    const pcr = ms.pcr;
    if (pcr !== null && pcr !== undefined) {
        const valStr = `${pcr.toFixed(2)}`;
        const cls = pcr > 1.2 ? "positive" : (pcr < 0.8 ? "negative" : "neutral");
        const status = pcr > 1.2 ? "🟢 BULLISH SUPPORT (Call Writers Trapped)" : (pcr < 0.8 ? "🔴 BEARISH RESISTANCE (Put Writers Trapped)" : "🟡 NEUTRAL (Balanced Open Interest)");
        rows.push({ name: "🎯 Put-Call Ratio (PCR)", value: valStr, category: "Options Open Interest", status, cls });
    }

    // 6. Regional & Global Markets Configuration
    const MARKET_META = {
        sp500: {
            name: "🇺🇸 S&P 500 Index",
            region: "US Broad Market (Wall Street)",
            cueRegion: "US CUE"
        },
        nasdaq: {
            name: "🇺🇸 NASDAQ Index",
            region: "US Tech Sector (Wall Street)",
            cueRegion: "US TECH CUE"
        },
        dow: {
            name: "🇺🇸 DOW Jones Index",
            region: "US Bluechips (NYSE)",
            cueRegion: "US DOW CUE"
        },
        nikkei: {
            name: "🇯🇵 NIKKEI 225 Index",
            region: "Asia / Japan (Tokyo)",
            cueRegion: "ASIAN CUE"
        },
        hangseng: {
            name: "🇭🇰 HANG SENG Index",
            region: "Asia / Hong Kong & China",
            cueRegion: "ASIAN CUE"
        },
        dax: {
            name: "🇩🇪 DAX 40 Index",
            region: "Europe / Germany (Frankfurt)",
            cueRegion: "EUROPEAN CUE"
        }
    };

    Object.entries(globalMkts).forEach(([symbol, pct]) => {
        if (pct !== null && pct !== undefined) {
            const key = symbol.toLowerCase();
            const meta = MARKET_META[key] || {
                name: `🌐 ${symbol.toUpperCase()} Index`,
                region: "Global Equity Market",
                cueRegion: "GLOBAL CUE"
            };

            const valStr = pct >= 0 ? `+${pct.toFixed(2)}%` : `${pct.toFixed(2)}%`;
            const cls = pct > 0.2 ? "positive" : (pct < -0.2 ? "negative" : "neutral");
            const status = pct > 0.2 ? `🟢 POSITIVE ${meta.cueRegion}` : (pct < -0.2 ? `🔴 NEGATIVE ${meta.cueRegion}` : `🟡 NEUTRAL ${meta.cueRegion}`);

            rows.push({
                name: meta.name,
                value: valStr,
                category: meta.region,
                status: status,
                cls
            });
        }
    });

    if (rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding: 24px; color: var(--text-muted);">No live microstructure signals available</td></tr>';
        return;
    }

    tbody.innerHTML = rows.map(r => `
        <tr>
            <td style="font-weight: 700; padding: 14px 16px;">${escapeHtml(r.name)}</td>
            <td class="${r.cls}" style="font-family: 'JetBrains Mono', monospace; font-weight: 800; font-size: 1.05rem; padding: 14px 16px;">${escapeHtml(r.value)}</td>
            <td style="color: var(--text-muted); font-size: 0.82rem; padding: 14px 16px;">${escapeHtml(r.category)}</td>
            <td class="${r.cls}" style="font-weight: 600; font-size: 0.85rem; padding: 14px 16px;">${escapeHtml(r.status)}</td>
        </tr>
    `).join("");
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Event Risk
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderEventRisk(data) {
    const container = document.getElementById("event-risk");
    const risk = data.event_risk;
    const icons = { HIGH: "🚨", MEDIUM: "⚠️", LOW: "✅" };
    const messages = {
        HIGH: "HIGH EVENT RISK — Major economic event imminent. Consider avoiding BTST trades.",
        MEDIUM: "MODERATE EVENT RISK — Potential volatility ahead. Trade with caution.",
        LOW: "LOW EVENT RISK — No major events detected. Normal trading conditions expected.",
    };

    container.className = "event-risk-strip " + risk.toLowerCase();
    container.innerHTML = `
        <span>${icons[risk]}</span>
        <span>Event Risk: ${risk}</span>
        <span style="margin-left: auto; font-weight: 400; font-size: 0.82rem; opacity: 0.8;">${messages[risk]}</span>
    `;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Key Drivers
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderKeyDrivers(data) {
    const container = document.getElementById("key-drivers");
    container.innerHTML = data.key_drivers
        .map(
            (driver) => `
        <div class="driver-item">
            <span class="driver-item__icon"></span>
            <span>${escapeHtml(driver)}</span>
        </div>
    `
        )
        .join("");
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Factors (Bullish vs Bearish)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderFactors(data) {
    const bullContainer = document.getElementById("bullish-factors");
    const bearContainer = document.getElementById("bearish-factors");

    bullContainer.innerHTML = data.bullish_factors.length
        ? data.bullish_factors
              .map(
                  (f) => `
            <div class="factor-item">
                <span class="factor-bullet"></span>
                <span>${escapeHtml(f)}</span>
            </div>
        `
              )
              .join("")
        : '<div class="factor-item" style="color: var(--text-muted);">No strong bullish signals detected</div>';

    bearContainer.innerHTML = data.bearish_factors.length
        ? data.bearish_factors
              .map(
                  (f) => `
            <div class="factor-item">
                <span class="factor-bullet"></span>
                <span>${escapeHtml(f)}</span>
            </div>
        `
              )
              .join("")
        : '<div class="factor-item" style="color: var(--text-muted);">No strong bearish signals detected</div>';
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Sector Summary
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderSectorSummary(data) {
    const container = document.getElementById("sector-grid");

    if (!data.sector_summary || data.sector_summary.length === 0) {
        container.innerHTML = '<div style="color: var(--text-muted); padding: 16px;">No sector data available</div>';
        return;
    }

    container.innerHTML = data.sector_summary
        .map(
            (sec) => `
        <div class="sector-card">
            <div>
                <div class="sector-card__name">${escapeHtml(sec.sector)}</div>
                <div class="sector-card__count">${sec.news_count} article${sec.news_count !== 1 ? "s" : ""} · Bull: ${sec.bullish_score} / Bear: ${sec.bearish_score}</div>
            </div>
            <div class="sector-card__badge ${sec.sentiment.toLowerCase()}">${sec.sentiment}</div>
        </div>
    `
        )
        .join("");
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Intraday Prediction Rendering
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderIntradayPrediction(data) {
    if (!data.intraday) return;

    const intraday = data.intraday;
    const bias = intraday.intraday_bias;
    const pattern = intraday.intraday_pattern;
    const phase = intraday.market_phase;
    const vol = intraday.volatility;

    // ── Intraday Bias Card ──
    const biasValueEl = document.getElementById("intraday-bias-value");
    biasValueEl.textContent = bias.bias;
    biasValueEl.className = `intraday-bias-value ${getIntradayBiasClass(bias.bias)}`;

    document.getElementById("intraday-bias-icon").textContent = bias.icon;
    document.getElementById("intraday-confidence-text").textContent = `Confidence: ${bias.confidence}%`;

    const biasCard = document.getElementById("intraday-bias-card");
    biasCard.className = `card intraday-bias-card ${getIntradayBiasClass(bias.bias)}`;

    // ── Intraday Gauge ──
    animateGauge(bias.confidence, "intraday-gauge-fill", "intraday-gauge-number");

    // ── Volatility Card ──
    const volBadge = document.getElementById("volatility-badge");
    volBadge.textContent = vol.level;
    volBadge.className = `volatility-badge vol-${vol.level.toLowerCase()}`;

    document.getElementById("volatility-range").textContent = vol.expected_range;
    document.getElementById("volatility-pct").textContent = `~${vol.nifty_range_pct}`;

    // ── Market Phase ──
    const phaseStrip = document.getElementById("market-phase-strip");
    phaseStrip.innerHTML = `
        <span>${phase.icon}</span>
        <span class="market-phase-name">${phase.phase}</span>
        <span class="market-phase-desc">${phase.description}</span>
    `;

    // ── Intraday Pattern ──
    const patternName = document.getElementById("intraday-pattern-name");
    patternName.textContent = pattern.pattern;
    patternName.className = `intraday-pattern-name ${getPatternClass(pattern.pattern)}`;

    document.getElementById("intraday-pattern-desc").textContent = pattern.description;
    document.getElementById("intraday-strategy-text").textContent = pattern.strategy;
    document.getElementById("intraday-option-strategy-text").textContent = pattern.option_strategy;

    const riskLevel = document.getElementById("intraday-risk-level");
    riskLevel.textContent = `⚠️ Risk Level: ${pattern.risk_level}`;
    riskLevel.className = `intraday-risk-level risk-${pattern.risk_level.toLowerCase().replace(" ", "-")}`;

    // ── Strategies ──
    const strategiesContainer = document.getElementById("intraday-strategies");
    strategiesContainer.innerHTML = bias.strategies
        .map(
            (s) => `
        <div class="driver-item strategy-item">
            <span class="driver-item__icon"></span>
            <span>${escapeHtml(s)}</span>
        </div>
    `
        )
        .join("");

    // ── Intraday Drivers ──
    const driversContainer = document.getElementById("intraday-drivers");
    driversContainer.innerHTML = intraday.intraday_drivers
        .map(
            (d) => `
        <div class="driver-item">
            <span class="driver-item__icon"></span>
            <span>${escapeHtml(d)}</span>
        </div>
    `
        )
        .join("");

    // ── Intraday Summary ──
    document.getElementById("intraday-summary-text").textContent = intraday.intraday_summary;
}

function getIntradayBiasClass(bias) {
    if (bias.includes("BULLISH")) return "bias-bullish";
    if (bias.includes("BEARISH")) return "bias-bearish";
    if (bias.includes("AVOID")) return "bias-avoid";
    return "bias-neutral";
}

function getPatternClass(pattern) {
    if (pattern.includes("UP") || pattern.includes("BULLISH")) return "pattern-bullish";
    if (pattern.includes("DOWN") || pattern.includes("BEARISH")) return "pattern-bearish";
    if (pattern.includes("RANGE") || pattern.includes("DRIFT")) return "pattern-neutral";
    return "pattern-volatile";
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Top Bullish & Bearish News Columns (Descending Order by Impact)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderTopBullishBearishNews(data) {
    const bullList = document.getElementById("top-bullish-news-list");
    const bearList = document.getElementById("top-bearish-news-list");
    const bullCount = document.getElementById("top-bullish-count");
    const bearCount = document.getElementById("top-bearish-count");

    if (!bullList || !bearList) return;

    const allNews = data.all_news || data.major_news || [];

    // Filter Bullish news & sort descending by impact_score / bullish_score
    const bullishNews = allNews
        .filter((n) => n.impact === "BULLISH")
        .sort((a, b) => (b.impact_score || b.bullish_score || 0) - (a.impact_score || a.bullish_score || 0));

    // Filter Bearish news & sort descending by impact_score / bearish_score
    const bearishNews = allNews
        .filter((n) => n.impact === "BEARISH")
        .sort((a, b) => (b.impact_score || b.bearish_score || 0) - (a.impact_score || a.bearish_score || 0));

    if (bullCount) bullCount.textContent = `${bullishNews.length} article${bullishNews.length !== 1 ? "s" : ""}`;
    if (bearCount) bearCount.textContent = `${bearishNews.length} article${bearishNews.length !== 1 ? "s" : ""}`;

    // Render Bullish Column
    if (bullishNews.length === 0) {
        bullList.innerHTML = '<div class="top-news-empty">No bullish news headlines detected</div>';
    } else {
        bullList.innerHTML = bullishNews
            .map(
                (n) => `
            <div class="top-news-item bullish">
                <div class="top-news-item__header">
                    <a href="${escapeHtml(n.link)}" target="_blank" rel="noopener noreferrer" class="top-news-item__title">
                        ${escapeHtml(n.headline)}
                    </a>
                    <span class="news-card__strength bullish">
                        ${escapeHtml(n.strength_badge || `🔥 High Impact (+${n.bullish_score || n.impact_score})`)}
                    </span>
                </div>
                <div class="top-news-item__meta">
                    <span class="sector-tag">${escapeHtml(n.sector)}</span>
                    <span>•</span>
                    <span>${escapeHtml(n.source)}</span>
                    <span>•</span>
                    <span>🕐 ${escapeHtml(n.published_date)}</span>
                </div>
            </div>
        `
            )
            .join("");
    }

    // Render Bearish Column
    if (bearishNews.length === 0) {
        bearList.innerHTML = '<div class="top-news-empty">No bearish news headlines detected</div>';
    } else {
        bearList.innerHTML = bearishNews
            .map(
                (n) => `
            <div class="top-news-item bearish">
                <div class="top-news-item__header">
                    <a href="${escapeHtml(n.link)}" target="_blank" rel="noopener noreferrer" class="top-news-item__title">
                        ${escapeHtml(n.headline)}
                    </a>
                    <span class="news-card__strength bearish">
                        ${escapeHtml(n.strength_badge || `🔥 High Impact (-${n.bearish_score || n.impact_score})`)}
                    </span>
                </div>
                <div class="top-news-item__meta">
                    <span class="sector-tag">${escapeHtml(n.sector)}</span>
                    <span>•</span>
                    <span>${escapeHtml(n.source)}</span>
                    <span>•</span>
                    <span>🕐 ${escapeHtml(n.published_date)}</span>
                </div>
            </div>
        `
            )
            .join("");
    }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// News Cards (sorted by date — most recent first)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderNewsCards(data) {
    const filterContainer = document.getElementById("news-filters");
    const newsGrid = document.getElementById("news-grid");

    // Build filter buttons from sectors
    const sectors = new Set(["ALL"]);
    const allNews = data.all_news || data.major_news || [];
    allNews.forEach((n) => sectors.add(n.sector || "General"));

    // Also add impact filters
    const impactFilters = ["BULLISH", "BEARISH", "NEUTRAL"];

    filterContainer.innerHTML = "";

    // Sector filters
    sectors.forEach((sec) => {
        const btn = document.createElement("button");
        btn.className = "filter-btn" + (sec === currentFilter ? " active" : "");
        btn.textContent = sec;
        btn.addEventListener("click", () => {
            currentFilter = sec;
            renderNewsCards(data);
        });
        filterContainer.appendChild(btn);
    });

    // Divider
    const divider = document.createElement("span");
    divider.style.cssText = "width:1px;height:24px;background:var(--border-subtle);margin:0 4px;";
    filterContainer.appendChild(divider);

    // Impact filters
    impactFilters.forEach((impact) => {
        const btn = document.createElement("button");
        btn.className = "filter-btn" + (impact === currentFilter ? " active" : "");
        btn.textContent = impact;
        btn.style.borderColor =
            impact === "BULLISH"
                ? "rgba(0,230,118,0.3)"
                : impact === "BEARISH"
                ? "rgba(255,23,68,0.3)"
                : "rgba(255,171,64,0.3)";
        btn.addEventListener("click", () => {
            currentFilter = impact;
            renderNewsCards(data);
        });
        filterContainer.appendChild(btn);
    });

    // Filter news
    let filtered = allNews;
    if (currentFilter !== "ALL") {
        filtered = allNews.filter(
            (n) => n.sector === currentFilter || n.impact === currentFilter
        );
    }

    // News are already sorted by date (most recent first) from startAnalysis()

    // Render
    if (filtered.length === 0) {
        newsGrid.innerHTML = `
            <div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--text-muted);">
                No news items match the selected filter.
            </div>
        `;
        return;
    }

    newsGrid.innerHTML = filtered
        .map(
            (n, i) => `
        <div class="news-card animate-in" style="animation-delay: ${Math.min(i * 0.05, 0.5)}s;">
            <div class="news-card__header">
                <div class="news-card__headline">
                    <a href="${escapeHtml(n.link)}" target="_blank" rel="noopener noreferrer">
                        ${escapeHtml(n.headline)}
                    </a>
                </div>
                <div class="news-card__badges">
                    <span class="news-card__impact ${n.impact.toLowerCase()}">
                        ${impactIcon(n.impact)} ${n.impact}
                    </span>
                    ${n.strength_badge ? `<span class="news-card__strength ${n.impact.toLowerCase()}">${escapeHtml(n.strength_badge)}</span>` : ""}
                </div>
            </div>
            <div class="news-card__meta">
                <span class="news-card__tag sector-tag">${escapeHtml(n.sector)}</span>
                <span class="news-card__tag importance-${n.importance.toLowerCase()}">${n.importance}</span>
                <span class="news-card__tag">${escapeHtml(n.category)}</span>
                <span class="news-card__divider">•</span>
                <span>${escapeHtml(n.source)}</span>
                <span class="news-card__divider">•</span>
                <span>🕐 ${escapeHtml(n.published_date)}</span>
            </div>
        </div>
    `
        )
        .join("");
}

function impactIcon(impact) {
    if (impact === "BULLISH") return "▲";
    if (impact === "BEARISH") return "▼";
    return "●";
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Error Rendering
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderError(message) {
    errorContainer.innerHTML = `
        <div class="card error-card animate-in">
            <div class="error-card__title">⚠️ Analysis Failed</div>
            <div class="error-card__message">${escapeHtml(message)}</div>
            <div style="margin-top: 16px; color: var(--text-muted); font-size: 0.82rem;">
                Please check your internet connection and try again.
            </div>
        </div>
    `;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Utilities
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function formatCrore(value) {
    if (value === undefined || value === null) return "0";
    const num = parseFloat(value);
    const prefix = num >= 0 ? "+" : "";
    return prefix + Math.abs(num).toLocaleString("en-IN", {
        maximumFractionDigits: 0,
    });
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Event Listeners
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

btnAnalyze.addEventListener("click", startAnalysis);

const btnViewHistory = document.getElementById("btn-view-history");
if (btnViewHistory) {
    btnViewHistory.addEventListener("click", () => {
        dashboard.classList.add("active");
        switchTab("history");
        const historySection = document.getElementById("content-history");
        if (historySection) {
            historySection.scrollIntoView({ behavior: "smooth" });
        }
    });
}

// Keyboard shortcut: Enter to start
document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !btnAnalyze.disabled && !dashboard.classList.contains("active")) {
        startAnalysis();
    }
});

// Initialize tabs
initTabs();

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Analysis History Implementation
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const refreshHistoryBtn = document.getElementById("refresh-history-btn");
if (refreshHistoryBtn) {
    refreshHistoryBtn.addEventListener("click", loadHistoryList);
}

async function loadHistoryList() {
    const scheduledGrid = document.getElementById("scheduled-runs-grid");
    const manualGrid = document.getElementById("manual-runs-grid");
    if (!scheduledGrid || !manualGrid) return;

    scheduledGrid.innerHTML = `<div style="text-align: center; padding: 24px; color: var(--text-muted);">🔄 Loading scheduled runs...</div>`;
    manualGrid.innerHTML = `<div style="text-align: center; padding: 24px; color: var(--text-muted);">🔄 Loading manual runs...</div>`;

    try {
        const res = await fetch("/api/history");
        const json = await res.json();

        if (json.status !== "success") {
            scheduledGrid.innerHTML = `<div style="text-align: center; padding: 24px; color: var(--bearish);">Error fetching history</div>`;
            manualGrid.innerHTML = `<div style="text-align: center; padding: 24px; color: var(--bearish);">Error fetching history</div>`;
            return;
        }

        const renderRunCard = (run) => {
            const pred = run.prediction || "FLAT";
            const predClass = pred === "GAP UP" ? "positive" : (pred === "GAP DOWN" ? "negative" : "neutral");
            const icon = pred === "GAP UP" ? "🟢" : (pred === "GAP DOWN" ? "🔴" : "🟡");
            const fiiStr = run.fii_net !== undefined && run.fii_net !== null ? `FII: ${formatCrore(run.fii_net)} Cr` : "";
            const diiStr = run.dii_net !== undefined && run.dii_net !== null ? `DII: ${formatCrore(run.dii_net)} Cr` : "";
            const flowStr = fiiStr || diiStr ? `${fiiStr} | ${diiStr}` : "Institutional Flow Captured";

            return `
                <div class="history-item-card">
                    <div class="history-item-card__header">
                        <div class="history-item-card__title">${escapeHtml(run.run_name || "Run")}</div>
                        <div class="history-item-badge ${predClass}">${icon} ${pred} (${run.confidence}%)</div>
                    </div>
                    <div class="history-item-card__time">⏰ Executed at: <strong>${escapeHtml(run.executed_at_ist || run.filename)}</strong></div>
                    <div class="history-item-card__subtext">${escapeHtml(flowStr)}</div>
                    <button type="button" class="btn btn-secondary history-load-btn" data-filename="${escapeHtml(run.filename)}">
                        👁️ Load Full Snapshot
                    </button>
                </div>
            `;
        };

        // Scheduled Column Render
        const scheduledRuns = json.scheduled || [];
        if (scheduledRuns.length === 0) {
            scheduledGrid.innerHTML = `
                <div class="history-empty-box">
                    <div style="font-size: 1.5rem; margin-bottom: 4px;">⏰</div>
                    <div style="font-weight: 600; font-size: 0.85rem;">No scheduled runs yet</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 4px;">Triggers Mon–Fri at 08:30, 09:45, 13:30, 15:15, and 17:30 IST</div>
                </div>
            `;
        } else {
            scheduledGrid.innerHTML = scheduledRuns.map(renderRunCard).join("");
        }

        // Manual Column Render
        const manualRuns = json.manual || [];
        if (manualRuns.length === 0) {
            manualGrid.innerHTML = `
                <div class="history-empty-box">
                    <div style="font-size: 1.5rem; margin-bottom: 4px;">⚡</div>
                    <div style="font-weight: 600; font-size: 0.85rem;">No manual runs yet</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 4px;">Click "Start Analysing" to run on-demand</div>
                </div>
            `;
        } else {
            manualGrid.innerHTML = manualRuns.map(renderRunCard).join("");
        }

    } catch (e) {
        console.error("History fetch error:", e);
        scheduledGrid.innerHTML = `<div style="text-align: center; padding: 24px; color: var(--bearish);">Failed to load history</div>`;
        manualGrid.innerHTML = `<div style="text-align: center; padding: 24px; color: var(--bearish);">Failed to load history</div>`;
    }
}

async function loadHistorySnapshot(filename) {
    console.log("Loading history snapshot:", filename);

    // Show loading overlay (same as startAnalysis)
    loadingOverlay.classList.add("active");
    if (loadingText) loadingText.textContent = "Loading historical snapshot...";
    if (loadingSubtext) loadingSubtext.textContent = "Restoring prediction and market signals from: " + filename;

    try {
        const res = await fetch(`/api/history/${encodeURIComponent(filename)}`);
        const json = await res.json();

        // Hide loading overlay
        loadingOverlay.classList.remove("active");

        if (json.status === "success" && json.data) {
            try {
                renderDashboard(json.data);

                // Show Snapshot Active Banner
                const banner = document.getElementById("snapshot-banner");
                const bannerTitle = document.getElementById("snapshot-banner-title");
                const bannerExit = document.getElementById("snapshot-banner-exit");
                if (banner && bannerTitle) {
                    const meta = json.data.run_metadata || {};
                    bannerTitle.textContent = `${meta.run_name || "Historical Snapshot"} (${meta.executed_at_ist || filename})`;
                    banner.style.display = "block";
                }
                if (bannerExit) {
                    bannerExit.onclick = () => {
                        banner.style.display = "none";
                        switchTab("history");
                    };
                }

                switchTab("btst");
                const targetEl = document.getElementById("snapshot-banner") || document.getElementById("tab-nav");
                if (targetEl) {
                    targetEl.scrollIntoView({ behavior: "smooth" });
                }
            } catch (renderErr) {
                console.error("Dashboard render error on snapshot:", renderErr);
                renderError("Failed to render snapshot: " + renderErr.message);
            }
        } else {
            renderError("Failed to load historical snapshot: " + (json.message || "Unknown error"));
        }
    } catch (e) {
        loadingOverlay.classList.remove("active");
        console.error("Snapshot fetch error:", e);
        renderError("Error loading snapshot: " + e.message);
    }
}

// Global Event Listener for History Load Buttons (Event Delegation)
document.addEventListener("click", (e) => {
    const btn = e.target.closest(".history-load-btn");
    if (btn) {
        e.preventDefault();
        e.stopPropagation();
        const filename = btn.getAttribute("data-filename");
        console.log("History load button clicked for filename:", filename);
        if (filename) {
            loadHistorySnapshot(filename);
        }
    }
});

// Expose loadHistorySnapshot globally
window.loadHistorySnapshot = loadHistorySnapshot;
