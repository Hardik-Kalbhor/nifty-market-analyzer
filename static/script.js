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

        if (!response.ok) {
            let errorMsg = `Server error (${response.status})`;
            try {
                const errJson = await response.json();
                if (errJson && errJson.message) errorMsg = errJson.message;
            } catch (e) {
                // Fallback for HTML 500/502 error pages
            }
            throw new Error(errorMsg);
        }

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

function _safeNum(val) {
    if (val === null || val === undefined || val === "") return null;
    const n = Number(val);
    return isNaN(n) ? null : n;
}

function renderDashboard(data) {
    if (!data || typeof data !== "object") return;
    analysisData = data;

    const safeExec = (fn, name) => {
        try {
            fn(data);
        } catch (err) {
            console.error(`Error in ${name}:`, err);
        }
    };

    // BTST Tab
    safeExec(renderPredictionHero, "renderPredictionHero");
    safeExec(renderInfoStrip, "renderInfoStrip");
    safeExec(renderScoreBar, "renderScoreBar");
    safeExec(renderBtstAgentConsensus, "renderBtstAgentConsensus");
    safeExec(renderSummary, "renderSummary");
    safeExec(renderSignalsTable, "renderSignalsTable");
    safeExec(renderEventRisk, "renderEventRisk");
    safeExec(renderKeyDrivers, "renderKeyDrivers");
    safeExec(renderFactors, "renderFactors");
    safeExec(renderSectorSummary, "renderSectorSummary");

    // Intraday Tab
    safeExec(renderIntradayPrediction, "renderIntradayPrediction");

    // Common: News
    safeExec(renderTopBullishBearishNews, "renderTopBullishBearishNews");
    safeExec(renderNewsCards, "renderNewsCards");

    dashboard.classList.add("active");

    // Scroll to dashboard
    setTimeout(() => {
        dashboard.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 200);
}

const _BTST_DIM_META = {
    macro_global:  { icon: "🌍", label: "Macro & Global Cues" },
    fii_dii:       { icon: "🏛️", label: "Institutional Flow (FII/DII)" },
    oi_pcr:        { icon: "📊", label: "Option Chain & Max Pain" },
    heavyweights:  { icon: "🏢", label: "Top 5 Heavyweights (~39%)" },
    vix_regime:    { icon: "⚡", label: "Volatility & VIX Regime" },
    news_catalyst: { icon: "📰", label: "News Catalysts & Sectors" },
};

function _btstDimBg(verdict, bias) {
    const text = `${verdict || ""} ${bias || ""}`.toUpperCase();
    if (text.includes("UP") || text.includes("BULL")) return "rgba(34,197,94,0.12)";
    if (text.includes("DOWN") || text.includes("BEAR")) return "rgba(239,68,68,0.12)";
    return "rgba(100,100,100,0.10)";
}

function _btstDimBorder(verdict, bias) {
    const text = `${verdict || ""} ${bias || ""}`.toUpperCase();
    if (text.includes("UP") || text.includes("BULL")) return "rgba(34,197,94,0.35)";
    if (text.includes("DOWN") || text.includes("BEAR")) return "rgba(239,68,68,0.35)";
    return "rgba(100,100,100,0.25)";
}

function renderBtstAgentConsensus(data) {
    const section = document.getElementById("btst-consensus-section");
    const grid = document.getElementById("btst-agent-grid");
    const badge = document.getElementById("btst-confluence-badge");

    if (!section || !grid) return;

    const dims = data.dimension_scores;
    if (!dims || typeof dims !== "object" || Object.keys(dims).length === 0) {
        section.style.display = "none";
        return;
    }

    section.style.display = "block";
    grid.innerHTML = "";

    if (badge && data.weighted_confluence) {
        badge.textContent = `⚖️ ${data.weighted_confluence}`;
    }

    for (const [dimKey, meta] of Object.entries(_BTST_DIM_META)) {
        const d = dims[dimKey];
        if (!d) continue;

        const verdict = (d.verdict || "FLAT").replace(/_/g, " ");
        const bias = (d.bias || "NEUTRAL").replace(/_/g, " ");
        const note = d.note || "";
        const bg = _btstDimBg(verdict, bias);
        const border = _btstDimBorder(verdict, bias);

        const card = document.createElement("div");
        card.style.cssText = `
            padding: 10px 12px;
            border-radius: 8px;
            background: ${bg};
            border: 1px solid ${border};
            font-size: 0.78rem;
            line-height: 1.45;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        `;
        card.innerHTML = `
            <div style="font-weight:600;margin-bottom:4px;display:flex;justify-content:space-between;align-items:center;">
                <span>${meta.icon} ${meta.label}</span>
                <span style="font-size:0.72rem;font-weight:700;padding:2px 6px;border-radius:4px;background:rgba(255,255,255,0.08);">${verdict} (${bias})</span>
            </div>
            <div style="opacity:0.85;font-size:0.76rem;margin-top:2px;">${note}</div>
        `;
        grid.appendChild(card);
    }
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Prediction Hero (BTST)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// (keeps renderPredictionHero as is...)



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
    const agentBadge = data.ai_agent_provider ? ` • 🤖 ${data.ai_agent_provider}` : "";
    predSentiment.textContent = `${sentimentEmoji[data.news_sentiment] || "⚪"} Sentiment: ${data.news_sentiment}${agentBadge}`;

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
    const scores = data.scores || {
        total_bullish: data.bullish_factors ? data.bullish_factors.length : 0,
        total_bearish: data.bearish_factors ? data.bearish_factors.length : 0,
        net_score: 0
    };
    const netClass = (scores.net_score || 0) >= 0 ? "positive" : "negative";
    const netPrefix = (scores.net_score || 0) >= 0 ? "+" : "";
    const newsCount = data.total_news_analyzed ?? (data.news_items ? data.news_items.length : 70);
    const timeStr = data.analysis_timestamp || data.run_metadata?.executed_at_ist || "Latest Live Run";

    container.innerHTML = `
        <div class="info-chip">
            🟢 Bullish Score: <span class="info-chip__value positive">${scores.total_bullish || 0}</span>
        </div>
        <div class="info-chip">
            🔴 Bearish Score: <span class="info-chip__value negative">${scores.total_bearish || 0}</span>
        </div>
        <div class="info-chip">
            📊 Net Score: <span class="info-chip__value ${netClass}">${netPrefix}${scores.net_score || 0}</span>
        </div>
        <div class="info-chip">
            📰 News Analyzed: <span class="info-chip__value">${newsCount}</span>
        </div>
        <div class="info-chip">
            🕐 ${escapeHtml(timeStr)}
        </div>
    `;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Score Bar
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderScoreBar(data) {
    const scores = data.scores || {
        total_bullish: (data.bullish_factors && data.bullish_factors.length) ? data.bullish_factors.length : (data.prediction === "GAP UP" ? 7 : 3),
        total_bearish: (data.bearish_factors && data.bearish_factors.length) ? data.bearish_factors.length : (data.prediction === "GAP DOWN" ? 7 : 3)
    };
    const total = (scores.total_bullish || 0) + (scores.total_bearish || 0);
    const bullPct = total > 0 ? (scores.total_bullish / total) * 100 : 50;
    const bearPct = total > 0 ? (scores.total_bearish / total) * 100 : 50;

    const bullBar = document.getElementById("score-bar-bull");
    const bearBar = document.getElementById("score-bar-bear");
    const bullLabel = document.getElementById("score-label-bull");
    const bearLabel = document.getElementById("score-label-bear");

    if (bullBar && bearBar) {
        setTimeout(() => {
            bullBar.style.width = bullPct + "%";
            bearBar.style.width = bearPct + "%";
        }, 300);
    }

    if (bullLabel) bullLabel.textContent = `Bullish ${Math.round(bullPct)}%`;
    if (bearLabel) bearLabel.textContent = `Bearish ${Math.round(bearPct)}%`;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Summary
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderSummary(data) {
    const el = document.getElementById("summary-text");
    if (el) {
        el.textContent = data.final_summary || data.ai_reasoning || "Market analysis and AI prediction completed.";
    }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Live Microstructure Signals Table (GIFT Nifty, FII, DII, VIX, PCR, Global)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderSignalsTable(data) {
    const tbody = document.getElementById("signals-table-body");
    if (!tbody) return;

    const ms = data.market_signals || data.market_signals_detail || {};
    const fiiDii = data.fii_dii || {};
    const globalMkts = ms.global_markets || ms.global_market_changes || data.market_signals_detail?.global_market_changes || {};

    const rows = [];

    // 1. GIFT Nifty
    const giftPct = _safeNum(ms.gift_nifty_change_pct ?? data.market_signals_detail?.gift_nifty_change_pct);
    if (giftPct !== null) {
        const valStr = giftPct >= 0 ? `+${giftPct.toFixed(2)}%` : `${giftPct.toFixed(2)}%`;
        const cls = giftPct > 0.2 ? "positive" : (giftPct < -0.2 ? "negative" : "neutral");
        const status = giftPct > 0.2 ? "🟢 GAP UP (Positive Opening Bias)" : (giftPct < -0.2 ? "🔴 GAP DOWN (Negative Opening Bias)" : "🟡 FLAT (No Directional Gap)");
        rows.push({ name: "🎁 GIFT Nifty", value: valStr, category: "Overnight Gap Indicator", status, cls });
    }

    // 2. FII Flow
    const fiiNet = _safeNum(fiiDii.fii_net ?? fiiDii.fii_net_crores ?? fiiDii.fii?.net);
    if (fiiNet !== null) {
        const valStr = `₹${formatCrore(fiiNet)} Cr`;
        const cls = fiiNet >= 0 ? "positive" : "negative";
        const status = fiiNet >= 0 ? "🟢 NET BUYERS (Foreign Institutional Inflows)" : "🔴 NET SELLERS (Foreign Institutional Outflows)";
        rows.push({ name: "🏦 FII Cash Flow", value: valStr, category: "Institutional Flow", status, cls });
    }

    // 3. DII Flow
    const diiNet = _safeNum(fiiDii.dii_net ?? fiiDii.dii_net_crores ?? fiiDii.dii?.net);
    if (diiNet !== null) {
        const valStr = `₹${formatCrore(diiNet)} Cr`;
        const cls = diiNet >= 0 ? "positive" : "negative";
        const status = diiNet >= 0 ? "🟢 NET BUYERS (Domestic Institutional Support)" : "🔴 NET SELLERS (Domestic Outflows)";
        rows.push({ name: "🏛️ DII Cash Flow", value: valStr, category: "Institutional Flow", status, cls });
    }

    // 4. India VIX
    const vix = _safeNum(ms.india_vix ?? data.market_signals_detail?.india_vix);
    const vixChg = _safeNum(ms.india_vix_change_pct ?? data.market_signals_detail?.india_vix_change_pct);
    if (vix !== null) {
        const chgStr = vixChg !== null ? ` (${vixChg >= 0 ? "+" : ""}${vixChg.toFixed(2)}%)` : "";
        const valStr = `${vix.toFixed(2)}${chgStr}`;
        const cls = vix < 16 ? "positive" : (vix > 20 ? "negative" : "neutral");
        const status = vix < 16 ? "🟢 LOW VOLATILITY (Safe Option Premium Regime)" : (vix > 20 ? "🔴 HIGH VOLATILITY (Extreme Premium Risk)" : "🟡 MODERATE VOLATILITY");
        rows.push({ name: "📈 India VIX", value: valStr, category: "Volatility Index", status, cls });
    }

    // 5. Put-Call Ratio
    const pcr = _safeNum(ms.pcr ?? data.market_signals_detail?.pcr);
    if (pcr !== null) {
        const valStr = `${pcr.toFixed(2)}`;
        const cls = pcr > 1.2 ? "positive" : (pcr < 0.8 ? "negative" : "neutral");
        const status = pcr > 1.2 ? "🟢 BULLISH SUPPORT (Call Writers Trapped)" : (pcr < 0.8 ? "🔴 BEARISH RESISTANCE (Put Writers Trapped)" : "🟡 NEUTRAL (Balanced Open Interest)");
        rows.push({ name: "🎯 Put-Call Ratio (PCR)", value: valStr, category: "Options Open Interest", status, cls });
    }

    // 6. Top 5 Heavyweights (~39% Index Impact)
    if (data.heavyweights && typeof data.heavyweights === "object") {
        Object.entries(data.heavyweights).forEach(([ticker, hData]) => {
            if (hData && typeof hData === "object") {
                const name = hData.name || ticker;
                const chg = _safeNum(hData.change_pct);
                const price = _safeNum(hData.price);
                const weight = _safeNum(hData.weight) || "";
                if (chg !== null) {
                    const valStr = `${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%${price ? ` (₹${price})` : ""}`;
                    const cls = chg > 0 ? "positive" : (chg < 0 ? "negative" : "neutral");
                    const status = chg > 0.3 ? `🟢 LIFTING INDEX (${weight}% Weight)` : (chg < -0.3 ? `🔴 DRAGGING INDEX (${weight}% Weight)` : `🟡 FLAT (${weight}% Weight)`);
                    rows.push({
                        name: `🏢 ${name}`,
                        value: valStr,
                        category: `Constituent Heavyweight (~${weight}%)`,
                        status,
                        cls
                    });
                }
            }
        });
    }

    // 7. Regional & Global Markets Configuration
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

    Object.entries(globalMkts).forEach(([symbol, rawPct]) => {
        const pct = _safeNum(rawPct);
        if (pct !== null) {
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
    if (!container) return;
    const risk = data.event_risk || "LOW";
    const icons = { HIGH: "🚨", MEDIUM: "⚠️", LOW: "✅" };
    const messages = {
        HIGH: "HIGH EVENT RISK — Major economic event imminent. Consider avoiding BTST trades.",
        MEDIUM: "MODERATE EVENT RISK — Potential volatility ahead. Trade with caution.",
        LOW: "LOW EVENT RISK — No major events detected. Normal trading conditions expected.",
    };

    container.className = "event-risk-strip " + risk.toLowerCase();
    container.innerHTML = `
        <span>${icons[risk] || "ℹ️"}</span>
        <span>Event Risk: ${risk}</span>
        <span style="margin-left: auto; font-weight: 400; font-size: 0.82rem; opacity: 0.8;">${messages[risk] || ""}</span>
    `;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Key Drivers
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderKeyDrivers(data) {
    const container = document.getElementById("key-drivers");
    if (!container) return;
    const drivers = (data.key_drivers && data.key_drivers.length)
        ? data.key_drivers
        : (data.bullish_factors || []).slice(0, 3);

    if (!drivers || drivers.length === 0) {
        container.innerHTML = '<div class="driver-item" style="color: var(--text-muted);">No key macro drivers highlighted</div>';
        return;
    }

    container.innerHTML = drivers
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

    const bull = data.bullish_factors || [];
    const bear = data.bearish_factors || [];

    if (bullContainer) {
        bullContainer.innerHTML = bull.length
            ? bull.map((f) => `
                <div class="factor-item">
                    <span class="factor-bullet"></span>
                    <span>${escapeHtml(f)}</span>
                </div>
            `).join("")
            : '<div class="factor-item" style="color: var(--text-muted);">No strong bullish signals detected</div>';
    }

    if (bearContainer) {
        bearContainer.innerHTML = bear.length
            ? bear.map((f) => `
                <div class="factor-item">
                    <span class="factor-bullet"></span>
                    <span>${escapeHtml(f)}</span>
                </div>
            `).join("")
            : '<div class="factor-item" style="color: var(--text-muted);">No strong bearish signals detected</div>';
    }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Sector Summary
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderSectorSummary(data) {
    const container = document.getElementById("sector-grid");
    if (!container) return;

    if (!data.sector_summary || !Array.isArray(data.sector_summary) || data.sector_summary.length === 0) {
        container.innerHTML = '<div style="color: var(--text-muted); padding: 16px;">Sector performance summarized in AI reasoning.</div>';
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
    const volLevel = (vol?.level || "LOW").toUpperCase();
    const volBadge = document.getElementById("volatility-badge");
    if (volBadge) {
        volBadge.textContent = volLevel;
        volBadge.className = `volatility-badge vol-${volLevel.toLowerCase()}`;
    }

    const volRange = document.getElementById("volatility-range");
    if (volRange) volRange.textContent = vol?.expected_range || "30-50 pts";

    const volPct = document.getElementById("volatility-pct");
    if (volPct) volPct.textContent = vol?.nifty_range_pct ? `~${vol.nifty_range_pct}` : "~0.2%";

    // ── Market Phase ──
    const phaseStrip = document.getElementById("market-phase-strip");
    if (phaseStrip) {
        phaseStrip.innerHTML = `
            <span>${phase?.icon || "📊"}</span>
            <span class="market-phase-name">${phase?.phase || "MARKET HOURS"}</span>
            <span class="market-phase-desc">${phase?.description || "Active Trading Session"}</span>
        `;
    }

    // ── Intraday Pattern ──
    const patternName = document.getElementById("intraday-pattern-name");
    const patStr = pattern?.pattern || "RANGE-BOUND";
    if (patternName) {
        patternName.textContent = patStr;
        patternName.className = `intraday-pattern-name ${getPatternClass(patStr)}`;
    }

    const patDesc = document.getElementById("intraday-pattern-desc");
    if (patDesc) patDesc.textContent = pattern?.description || "Market structure steady.";

    const patStrat = document.getElementById("intraday-strategy-text");
    if (patStrat) patStrat.textContent = pattern?.strategy || "Trade with strict risk management.";

    const optStrat = document.getElementById("intraday-option-strategy-text");
    if (optStrat) optStrat.textContent = pattern?.option_strategy || "Monitor price action at key levels.";

    const riskLvlStr = (pattern?.risk_level || "LOW").toUpperCase();
    const riskLevel = document.getElementById("intraday-risk-level");
    if (riskLevel) {
        riskLevel.textContent = `⚠️ Risk Level: ${riskLvlStr}`;
        riskLevel.className = `intraday-risk-level risk-${riskLvlStr.toLowerCase().replace(/\s+/g, "-")}`;
    }

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
        .map((n, i) => {
            const impact = (n.impact || n.sentiment || "NEUTRAL").toUpperCase();
            const importance = (n.importance || "MEDIUM").toUpperCase();
            const impactClass = impact.toLowerCase();
            const importanceClass = importance.toLowerCase();
            const link = n.link || n.url || "#";

            return `
        <div class="news-card animate-in" style="animation-delay: ${Math.min(i * 0.05, 0.5)}s;">
            <div class="news-card__header">
                <div class="news-card__headline">
                    <a href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer">
                        ${escapeHtml(n.headline || "Market Headline")}
                    </a>
                </div>
                <div class="news-card__badges">
                    <span class="news-card__impact ${impactClass}">
                        ${impactIcon(impact)} ${impact}
                    </span>
                    ${n.strength_badge ? `<span class="news-card__strength ${impactClass}">${escapeHtml(n.strength_badge)}</span>` : ""}
                </div>
            </div>
            <div class="news-card__meta">
                <span class="news-card__tag sector-tag">${escapeHtml(n.sector || "Markets")}</span>
                <span class="news-card__tag importance-${importanceClass}">${importance}</span>
                <span class="news-card__tag">${escapeHtml(n.category || "Markets")}</span>
                <span class="news-card__divider">•</span>
                <span>${escapeHtml(n.source || "News")}</span>
                <span class="news-card__divider">•</span>
                <span>🕐 ${escapeHtml(n.published_date || "")}</span>
            </div>
        </div>
    `;
        })
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
    const isQuota = message.toLowerCase().includes("quota") || message.toLowerCase().includes("rate limit") || message.toLowerCase().includes("try again in");
    const title = isQuota ? "⏳ Gemini AI Quota Refreshing" : "⚠️ Analysis Failed";
    const subtext = isQuota
        ? "Google Gemini API free tier rate limit reached. Your quota refreshes automatically — please wait the indicated seconds and click Re-Analyse."
        : "Please check your internet connection and try again.";

    errorContainer.innerHTML = `
        <div class="card error-card animate-in" style="${isQuota ? 'border-color: #f59e0b; background: rgba(245, 158, 11, 0.08);' : ''}">
            <div class="error-card__title" style="${isQuota ? 'color: #f59e0b;' : ''}">${title}</div>
            <div class="error-card__message" style="font-size: 0.95rem; line-height: 1.5;">${escapeHtml(message)}</div>
            <div style="margin-top: 16px; color: var(--text-muted); font-size: 0.82rem;">
                ${subtext}
            </div>
        </div>
    `;
    errorContainer.scrollIntoView({ behavior: "smooth", block: "center" });
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

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 🎯 Live Position Exit Advisor Client Logic
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

let exitAutoPollTimer = null;
let lastExitVerdict = null;

function playExitChime(verdict) {
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.connect(gain);
        gain.connect(audioCtx.destination);

        if (verdict.includes("EMERGENCY") || verdict.includes("FULL_EXIT")) {
            osc.frequency.setValueAtTime(880, audioCtx.currentTime); // High pitch alarm
            osc.type = "sawtooth";
            gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
            osc.start();
            osc.stop(audioCtx.currentTime + 0.5);
        } else if (verdict.includes("PARTIAL_BOOK")) {
            osc.frequency.setValueAtTime(523.25, audioCtx.currentTime); // C5 cheerful chime
            osc.type = "sine";
            gain.gain.setValueAtTime(0.2, audioCtx.currentTime);
            osc.start();
            osc.stop(audioCtx.currentTime + 0.35);
        }
    } catch (e) {
        console.debug("Audio chime unsupported or blocked:", e);
    }
}

function initExitAdvisor() {
    const form = document.getElementById("exit-advisor-form");
    const presetBtn = document.getElementById("btn-preset-btst");
    const autoPollToggle = document.getElementById("auto-monitor-toggle");

    if (presetBtn) {
        presetBtn.addEventListener("click", () => {
            // Read latest analyzed data from global window.lastAnalysisData if available
            const bias = document.getElementById("btst-badge")?.textContent?.trim() || "";
            const sideSelect = document.getElementById("position-side");
            const tradeTypeSelect = document.getElementById("trade-type");
            const entrySpotInput = document.getElementById("entry-spot");

            if (tradeTypeSelect) tradeTypeSelect.value = "BTST";
            if (bias.includes("BUY CE") && sideSelect) sideSelect.value = "BUY_CE";
            else if (bias.includes("BUY PE") && sideSelect) sideSelect.value = "BUY_PE";

            // If spot is displayed on info strip, grab it
            const spotEl = document.querySelector("#info-strip .info-item:first-child .info-item__value");
            if (spotEl && entrySpotInput) {
                const cleanSpot = spotEl.textContent.replace(/[^0-9.]/g, "");
                if (cleanSpot) entrySpotInput.value = cleanSpot;
            }

            const strikeInput = document.getElementById("strike-name");
            if (strikeInput && !strikeInput.value && entrySpotInput?.value) {
                const rounded = Math.round(parseFloat(entrySpotInput.value) / 50) * 50;
                strikeInput.value = `${rounded} ${sideSelect.value === "BUY_PE" ? "PE" : "CE"}`;
            }

            const entryTimeInput = document.getElementById("entry-time");
            if (entryTimeInput) entryTimeInput.value = "15:15 IST (Yesterday)";
        });
    }

    if (form) {
        form.addEventListener("submit", async (e) => {
            e.preventDefault();
            await evaluateLiveExit(true);
        });
    }

    if (autoPollToggle) {
        autoPollToggle.addEventListener("change", () => {
            if (autoPollToggle.checked) {
                console.log("⏱️ Auto-monitor enabled: polling every 30s");
                evaluateLiveExit(false);
                exitAutoPollTimer = setInterval(() => evaluateLiveExit(false), 30000);
            } else {
                console.log("⏱️ Auto-monitor disabled");
                if (exitAutoPollTimer) clearInterval(exitAutoPollTimer);
                exitAutoPollTimer = null;
            }
        });
    }

    // ── Screenshot Upload & Paste Support ──
    initScreenshotUploader();
}

function initScreenshotUploader() {
    const fileInput = document.getElementById("screenshot-file-input");
    const uploadBtn = document.getElementById("btn-upload-screenshot");
    const pasteBtn = document.getElementById("btn-paste-screenshot");

    if (uploadBtn && fileInput) {
        uploadBtn.addEventListener("click", () => fileInput.click());
        fileInput.addEventListener("change", (e) => {
            if (e.target.files && e.target.files[0]) {
                processScreenshotFile(e.target.files[0]);
                fileInput.value = "";
            }
        });
    }

    if (pasteBtn) {
        pasteBtn.addEventListener("click", async () => {
            try {
                if (navigator.clipboard && navigator.clipboard.read) {
                    const items = await navigator.clipboard.read();
                    let foundImage = false;
                    for (const item of items) {
                        for (const type of item.types) {
                            if (type.startsWith("image/")) {
                                const blob = await item.getType(type);
                                processScreenshotFile(blob);
                                foundImage = true;
                                break;
                            }
                        }
                    }
                    if (!foundImage) {
                        showScreenshotBanner("📋 No image found in clipboard. Press Cmd+V (Mac) or Ctrl+V (Windows) to paste.", "loading");
                    }
                } else {
                    showScreenshotBanner("📋 Press Cmd+V or Ctrl+V anywhere to paste screenshot.", "loading");
                }
            } catch (err) {
                showScreenshotBanner("📋 Press Cmd+V or Ctrl+V anywhere on screen to paste.", "loading");
            }
        });
    }

    // Global Paste Listener (Cmd+V / Ctrl+V anywhere)
    window.addEventListener("paste", (e) => {
        const items = (e.clipboardData || e.originalEvent.clipboardData)?.items;
        if (!items) return;
        for (const item of items) {
            if (item.type.indexOf("image") !== -1) {
                const blob = item.getAsFile();
                if (blob) {
                    // Switch to Live Exit Advisor tab if not active
                    const exitTabBtn = document.querySelector('.tab-btn[data-tab="exit-advisor"]');
                    if (exitTabBtn && !exitTabBtn.classList.contains("active")) {
                        exitTabBtn.click();
                    }
                    processScreenshotFile(blob);
                    e.preventDefault();
                    break;
                }
            }
        }
    });
}

function showScreenshotBanner(message, type = "loading") {
    const banner = document.getElementById("screenshot-status-banner");
    if (!banner) return;
    banner.style.display = "flex";
    banner.className = `screenshot-status-banner ${type}`;
    
    let icon = "⏳";
    if (type === "success") icon = "✅";
    if (type === "error") icon = "⚠️";

    banner.innerHTML = `<span>${icon}</span><span>${escapeHtml(message)}</span>`;
}

async function processScreenshotFile(blob) {
    showScreenshotBanner("🔍 Analyzing broker screenshot & color badges...", "loading");

    try {
        // 1. Client-side canvas resize & color badge detection
        const { b64: resizedB64, hasRedBadge, hasGreenBadge } = await analyzeImageCanvas(blob, 1400);

        // 2. Try server-side OCR & LLM extraction
        try {
            const res = await fetch("/api/extract-screenshot", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ image_b64: resizedB64 })
            });
            const json = await res.json();

            if (json.status === "success" && json.data) {
                applyExtractedPositionData(json.data);
                return;
            }
        } catch (serverErr) {
            console.warn("Server OCR failed, trying client-side Tesseract.js:", serverErr);
        }

        // 3. Robust Client-side Tesseract.js fallback with color badge context
        if (window.Tesseract) {
            showScreenshotBanner("⚡ Reading position data with high-res OCR...", "loading");
            const ocrRes = await Tesseract.recognize(blob, "eng");
            const rawText = ocrRes?.data?.text || "";
            if (rawText.trim().length > 15) {
                const textRes = await fetch("/api/extract-ocr-text", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        raw_text: rawText,
                        has_red_badge: hasRedBadge,
                        has_green_badge: hasGreenBadge
                    })
                });
                const textJson = await textRes.json();
                if (textJson.status === "success" && textJson.data) {
                    applyExtractedPositionData(textJson.data);
                    return;
                }
            }
        }

        showScreenshotBanner("Could not detect active contract. Please enter fields manually.", "error");

    } catch (e) {
        console.error("Screenshot OCR error:", e);
        showScreenshotBanner("Failed to parse screenshot. Please verify contract visibility.", "error");
    }
}

function analyzeImageCanvas(blob, maxDim = 1400) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => {
            let w = img.width;
            let h = img.height;
            if (w > maxDim || h > maxDim) {
                if (w > h) {
                    h = Math.round((h * maxDim) / w);
                    w = maxDim;
                } else {
                    w = Math.round((w * maxDim) / h);
                    h = maxDim;
                }
            }
            const canvas = document.createElement("canvas");
            canvas.width = w;
            canvas.height = h;
            const ctx = canvas.getContext("2d");
            ctx.drawImage(img, 0, 0, w, h);

            // Color badge detection
            let hasRedBadge = false;
            let hasGreenBadge = false;
            try {
                const imgData = ctx.getImageData(0, 0, w, h).data;
                let redCount = 0;
                let greenCount = 0;
                for (let i = 0; i < imgData.length; i += 4) {
                    const r = imgData[i];
                    const g = imgData[i + 1];
                    const b = imgData[i + 2];
                    // Red badge: high R, low G/B
                    if (r > 180 && g < 115 && b < 115) redCount++;
                    // Green badge: high G, lower R
                    if (g > 150 && r < 120 && b < 140) greenCount++;
                }
                hasRedBadge = redCount > 80;
                hasGreenBadge = greenCount > 80;
            } catch (err) {
                console.debug("Canvas pixel analysis note:", err);
            }

            resolve({
                b64: canvas.toDataURL("image/jpeg", 0.88),
                hasRedBadge,
                hasGreenBadge
            });
        };
        img.onerror = reject;
        img.src = URL.createObjectURL(blob);
    });
}

function normalizePositionSide(side, strike = "") {
    if (!side) return "BUY_CE";
    const s = side.toUpperCase().replace(/\s+/g, "_");
    if (s.includes("SHORT_CE") || s.includes("SELL_CE") || s.includes("SELL_CALL")) return "SHORT_CE";
    if (s.includes("SHORT_PE") || s.includes("SELL_PE") || s.includes("SELL_PUT")) return "SHORT_PE";
    if (s.includes("BUY_CE") || s.includes("LONG_CE") || s.includes("BUY_CALL")) return "BUY_CE";
    if (s.includes("BUY_PE") || s.includes("LONG_PE") || s.includes("BUY_PUT")) return "BUY_PE";
    if (s.includes("LONG_FUT")) return "LONG_FUTURES";
    if (s.includes("SHORT_FUT")) return "SHORT_FUTURES";

    if (s.includes("SHORT") || s.includes("SELL")) {
        return (strike && strike.toUpperCase().includes("PE")) ? "SHORT_PE" : "SHORT_CE";
    }
    return "BUY_CE";
}

function applyExtractedPositionData(data) {
    const tradeTypeEl = document.getElementById("trade-type");
    const posSideEl = document.getElementById("position-side");
    const strikeEl = document.getElementById("strike-name");
    const spotEl = document.getElementById("entry-spot");
    const entryPremEl = document.getElementById("entry-premium");
    const currPremEl = document.getElementById("current-premium");

    if (data.trade_type && tradeTypeEl) tradeTypeEl.value = data.trade_type;
    
    // Normalize position side
    const normalizedSide = normalizePositionSide(data.position_side, data.strike);
    if (posSideEl) posSideEl.value = normalizedSide;

    if (data.strike && strikeEl) strikeEl.value = data.strike;
    if (data.entry_spot && spotEl) {
        spotEl.value = data.entry_spot;
    }
    if (data.entry_premium && entryPremEl) entryPremEl.value = data.entry_premium;
    if (data.current_premium && currPremEl) currPremEl.value = data.current_premium;

    let pnlMsg = "";
    if (data.pnl_pct !== null && data.pnl_pct !== undefined) {
        const pnlSign = data.pnl_pct >= 0 ? "+" : "";
        pnlMsg = ` · P&L: ${pnlSign}${data.pnl_pct}%`;
    }
    if (data.pnl_amount) {
        pnlMsg += ` (₹${Number(data.pnl_amount).toLocaleString("en-IN")})`;
    }

    const broker = data.broker_detected || "Broker";
    showScreenshotBanner(`Parsed from ${broker}: ${data.strike || "Position"} (${normalizedSide.replace("_", " ")}) · Avg: ₹${data.entry_premium || "--"} · LTP: ₹${data.current_premium || "--"}${pnlMsg}`, "success");

    // Automatically trigger evaluation for instant gratification
    evaluateLiveExit(true);
}

async function evaluateLiveExit(showLoadingState = true) {
    const submitBtn = document.getElementById("btn-evaluate-exit");
    const placeholder = document.getElementById("exit-result-placeholder");
    const content = document.getElementById("exit-result-content");

    // Show expiry day badge if today is Thursday (IST)
    const todayIST = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
    const isExpiryDay = todayIST.getDay() === 4; // 0=Sun, 4=Thu
    const expiryBadgeEl = document.getElementById("expiry-day-badge");
    if (expiryBadgeEl) expiryBadgeEl.style.display = isExpiryDay ? "block" : "none";

    const dteRaw = document.getElementById("dte-input")?.value;
    const payload = {
        trade_type: document.getElementById("trade-type")?.value || "INTRADAY",
        position_side: document.getElementById("position-side")?.value || "BUY_CE",
        strike: document.getElementById("strike-name")?.value || "",
        entry_spot: parseFloat(document.getElementById("entry-spot")?.value) || 0,
        entry_premium: parseFloat(document.getElementById("entry-premium")?.value) || 0,
        current_premium: parseFloat(document.getElementById("current-premium")?.value) || 0,
        risk_profile: document.getElementById("risk-profile")?.value || "BALANCED",
        entry_time: document.getElementById("entry-time")?.value || "",
        dte: (dteRaw !== "" && dteRaw !== undefined && dteRaw !== null) ? parseInt(dteRaw, 10) : null,
    };

    if (showLoadingState && submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<span>⏳</span><span>Running 6-Agent Analysis...</span>`;
    }

    try {
        const res = await fetch("/api/exit-advisor", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const json = await res.json();

        if (json.status === "success" && json.data) {
            renderExitAdvisorResult(json.data);
            renderDimensionScores(json.data.dimension_scores);
            renderFiiDiiContext(json.data.fii_dii_context, json.data.expiry_context);
            if (placeholder) placeholder.style.display = "none";
            if (content) content.style.display = "block";

            // Trigger chime if verdict changed to actionable exit
            if (lastExitVerdict !== json.data.verdict) {
                lastExitVerdict = json.data.verdict;
                if (!json.data.verdict.includes("HOLD")) {
                    playExitChime(json.data.verdict);
                }
            }
        } else {
            alert("Exit evaluation failed: " + (json.message || "Unknown error"));
        }
    } catch (e) {
        console.error("Exit advisor network error:", e);
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = `<span>🎯</span><span>Evaluate Exit Signal</span>`;
        }
    }
}


function renderExitAdvisorResult(data) {
    const verdictTag = document.getElementById("exit-verdict-tag");
    const engineBadge = document.getElementById("exit-engine-badge");
    const confVal = document.getElementById("exit-conf-val");
    const actionBox = document.getElementById("exit-action-box");
    const actionText = document.getElementById("exit-action-text");
    const metricSl = document.getElementById("exit-metric-sl");
    const metricHealth = document.getElementById("exit-metric-health");
    const metricLatency = document.getElementById("exit-metric-latency");
    const hwText = document.getElementById("exit-hw-text");
    const reasoningText = document.getElementById("exit-reasoning-text");

    const verdict = data.verdict || "HOLD_AND_RIDE";
    const cleanVerdict = verdict.replace(/_/g, " ");

    if (verdictTag) {
        verdictTag.textContent = cleanVerdict;
        verdictTag.className = "exit-verdict-tag " + verdict.toLowerCase();
    }

    if (engineBadge) {
        engineBadge.textContent = data.engine || "AI Evaluator";
        if (data.is_fast_path) {
            engineBadge.textContent = "⚡ Fast-Path Safety Engine (0 ms)";
        }
    }

    if (confVal) confVal.textContent = (data.confidence || 75) + "%";

    if (actionBox) {
        actionBox.className = "exit-action-box " + verdict.toLowerCase();
    }
    if (actionText) actionText.textContent = data.action || "--";

    if (metricSl) {
        metricSl.textContent = data.trailing_sl ? `₹${data.trailing_sl.toLocaleString("en-IN")}` : "Cost (Breakeven)";
    }

    if (metricHealth) {
        const health = data.thesis_status || (verdict.includes("HOLD") ? "INTACT" : verdict.includes("PARTIAL") ? "TARGET MET" : "INVALIDATED");
        metricHealth.textContent = health;
        metricHealth.className = "exit-metric-value " + (health === "INTACT" ? "bullish" : health === "TARGET MET" ? "bullish" : "bearish");
    }

    if (metricLatency) {
        metricLatency.textContent = data.latency_ms ? `${data.latency_ms} ms` : "Instant";
    }

    if (hwText) {
        if (data.heavyweight_pulse) {
            hwText.textContent = data.heavyweight_pulse;
        } else if (data.heavyweights) {
            const items = Object.values(data.heavyweights).map(h => `${h.name}: ${h.change_pct > 0 ? '+' : ''}${h.change_pct}%`);
            hwText.textContent = items.join(" | ");
        } else {
            hwText.textContent = "Tracking top 5 index constituents.";
        }
    }

    if (reasoningText) {
        reasoningText.textContent = data.reasoning || "Evaluation based on live market conditions.";
    }
}

const _DIMENSION_META = {
    greeks_decay:  { icon: "📐", label: "Greeks & Decay" },
    oi_pcr:        { icon: "📊", label: "OI / PCR" },
    heavyweights:  { icon: "🏛️", label: "Heavyweights" },
    price_action:  { icon: "📈", label: "Price Action" },
    vix_regime:    { icon: "⚡", label: "VIX Regime" },
    macro_global:  { icon: "🌍", label: "Macro & Global" },
};

function _verdictBg(v) {
    if (!v) return "rgba(100,100,100,0.1)";
    const u = v.toUpperCase();
    if (u.includes("HOLD")) return "rgba(34,197,94,0.12)";
    if (u.includes("PARTIAL")) return "rgba(234,179,8,0.12)";
    if (u.includes("TRAIL")) return "rgba(249,115,22,0.12)";
    if (u.includes("EXIT")) return "rgba(239,68,68,0.12)";
    return "rgba(100,100,100,0.1)";
}
function _verdictBorder(v) {
    if (!v) return "rgba(100,100,100,0.25)";
    const u = v.toUpperCase();
    if (u.includes("HOLD")) return "rgba(34,197,94,0.35)";
    if (u.includes("PARTIAL")) return "rgba(234,179,8,0.35)";
    if (u.includes("TRAIL")) return "rgba(249,115,22,0.35)";
    if (u.includes("EXIT")) return "rgba(239,68,68,0.35)";
    return "rgba(100,100,100,0.25)";
}

function renderDimensionScores(dimensionScores) {
    const container = document.getElementById("exit-dimension-scores");
    const grid = document.getElementById("exit-dimension-grid");
    if (!container || !grid) return;
    if (!dimensionScores || typeof dimensionScores !== "object") {
        container.style.display = "none";
        return;
    }
    grid.innerHTML = "";
    let hasAny = false;
    for (const [dim, meta] of Object.entries(_DIMENSION_META)) {
        const d = dimensionScores[dim];
        if (!d) continue;
        hasAny = true;
        const bg = _verdictBg(d.verdict);
        const border = _verdictBorder(d.verdict);
        const card = document.createElement("div");
        card.style.cssText = `padding:8px 10px;border-radius:8px;background:${bg};border:1px solid ${border};font-size:0.75rem;line-height:1.5;`;
        card.innerHTML = `
            <div style="font-weight:600;margin-bottom:2px;display:flex;justify-content:space-between;">
                <span>${meta.icon} ${meta.label}</span>
                <span style="opacity:0.65;font-size:0.7rem;">${(d.verdict || "").replace(/_/g," ")}</span>
            </div>
            <div style="opacity:0.8;">${d.note || ""}</div>
        `;
        grid.appendChild(card);
    }
    container.style.display = hasAny ? "block" : "none";
}

function renderFiiDiiContext(fiiDiiCtx, expiryCtx) {
    const row = document.getElementById("exit-fii-dii-row");
    const fiiText = document.getElementById("exit-fii-dii-text");
    const expBadge = document.getElementById("exit-expiry-badge");
    const expText = document.getElementById("exit-expiry-text");

    if (row && fiiDiiCtx) row.style.display = "flex";
    if (fiiText && fiiDiiCtx) fiiText.textContent = fiiDiiCtx;

    if (expBadge && expiryCtx) {
        const urgent = expiryCtx.includes("EXPIRY") || expiryCtx.includes("⚠️");
        expBadge.style.display = urgent ? "block" : "none";
        if (expText) expText.textContent = expiryCtx.replace(/⚠️\s?/g, "");
    }
}

// Initialize on DOM load
document.addEventListener("DOMContentLoaded", () => {
    initExitAdvisor();
});
