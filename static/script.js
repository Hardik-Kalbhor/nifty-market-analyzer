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

    const refreshIntradayBtn = document.getElementById("btn-refresh-intraday");
    if (refreshIntradayBtn) {
        refreshIntradayBtn.addEventListener("click", () => {
            startAnalysis();
        });
    }
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

    try {
        if (history.replaceState) {
            history.replaceState(null, "", `#${tab}`);
        }
    } catch (e) {}

    if (tab === "history") {
        loadHistoryList();
    } else if (tab === "btst") {
        fetchAndRenderInstitutionalRadar();
    } else if (tab === "exit-advisor") {
        // Pristine form for live user input
    } else if (tab === "cognigraph") {
        loadCogniGraphData();
        loadDreamingData();
        loadTrajectoryStats();
        loadWalkForwardSimulationData();
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
    safeExec(renderInstitutionalRadar, "renderInstitutionalRadar");
    safeExec(renderSummary, "renderSummary");

    safeExec(renderSignalsTable, "renderSignalsTable");
    safeExec(renderEventRisk, "renderEventRisk");
    safeExec(renderKeyDrivers, "renderKeyDrivers");
    safeExec(renderFactors, "renderFactors");
    safeExec(renderSectorSummary, "renderSectorSummary");
    safeExec(renderBtstDebateCommittee, "renderBtstDebateCommittee");

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
// 3-Analyst BTST Risk Debate Committee
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const _BTST_PERSONA_META = {
    aggressive:   { icon: "🚀", title: "Aggressive Analyst", sub: "Momentum & Overnight Gap" },
    conservative: { icon: "🛡️", title: "Conservative Guardian", sub: "Theta Decay & DTE Defense" },
    neutral:      { icon: "⚖️", title: "Neutral Risk Arbiter", sub: "Trade Structuring & R:R" },
};

function renderBtstDebateCommittee(data) {
    const section = document.getElementById("btst-debate-section");
    if (!section) return;

    const debate = data.debate;
    const structure = data.btst_structure;
    const consensus = data.debate_consensus || (debate ? debate.consensus : null);
    const instruction = data.trade_instruction;

    // Badges
    const structBadge = document.getElementById("btst-debate-structure-badge");
    const consBadge = document.getElementById("btst-debate-consensus-badge");
    const structLabel = document.getElementById("btst-judge-structure-label");
    const actionEl = document.getElementById("btst-judge-action");
    const ratEl = document.getElementById("btst-judge-rationale");

    if (structBadge && structure) {
        const s = structure.replace(/_/g, " ");
        structBadge.textContent = s;
        if (structLabel) structLabel.textContent = s;
        if (s.includes("FULL") || s.includes("BUY")) {
            structBadge.style.background = "rgba(34,197,94,0.15)";
            structBadge.style.color = "#4ade80";
            structBadge.style.borderColor = "rgba(34,197,94,0.3)";
        } else if (s.includes("NO TRADE") || s.includes("STRICT")) {
            structBadge.style.background = "rgba(239,68,68,0.15)";
            structBadge.style.color = "#f87171";
            structBadge.style.borderColor = "rgba(239,68,68,0.3)";
        } else {
            structBadge.style.background = "rgba(245,158,11,0.15)";
            structBadge.style.color = "#fbbf24";
            structBadge.style.borderColor = "rgba(245,158,11,0.3)";
        }
    }

    if (consBadge && consensus) {
        consBadge.textContent = consensus;
        if (consensus === "UNANIMOUS") {
            consBadge.style.background = "rgba(34,197,94,0.15)";
            consBadge.style.color = "#4ade80";
            consBadge.style.borderColor = "rgba(34,197,94,0.3)";
        } else if (consensus === "SPLIT") {
            consBadge.style.background = "rgba(239,68,68,0.15)";
            consBadge.style.color = "#f87171";
            consBadge.style.borderColor = "rgba(239,68,68,0.3)";
        } else {
            consBadge.style.background = "rgba(99,102,241,0.15)";
            consBadge.style.color = "#a5b4fc";
            consBadge.style.borderColor = "rgba(99,102,241,0.3)";
        }
    }

    if (actionEl && instruction) {
        actionEl.textContent = instruction;
    }

    if (!debate || typeof debate !== "object") return;

    if (ratEl && debate.judge_rationale) {
        ratEl.textContent = debate.judge_rationale;
    }

    for (const [key, meta] of Object.entries(_BTST_PERSONA_META)) {
        const p = debate[key];
        if (!p) continue;

        const vEl = document.getElementById(`btst-verdict-${key}`);
        const mEl = document.getElementById(`btst-meta-${key}`);
        const rEl = document.getElementById(`btst-rationale-${key}`);

        if (vEl && p.verdict) {
            const vStr = p.verdict.replace(/_/g, " ");
            vEl.textContent = vStr;
            let vColor = "#fbbf24";
            let vBg = "rgba(245,158,11,0.15)";
            if (vStr.includes("FULL")) { vColor = "#4ade80"; vBg = "rgba(34,197,94,0.15)"; }
            else if (vStr.includes("NO TRADE")) { vColor = "#f87171"; vBg = "rgba(239,68,68,0.15)"; }
            vEl.style.color = vColor;
            vEl.style.background = vBg;
            vEl.style.borderColor = `${vColor}44`;
        }

        if (mEl) {
            mEl.textContent = `${meta.sub} · ${p.confidence || 75}% Conf`;
        }

        if (rEl && p.rationale) {
            rEl.textContent = p.rationale;
        }
    }
}
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

    // 5b. Max Pain
    const maxPain = _safeNum(ms.max_pain ?? data.market_signals_detail?.max_pain);
    if (maxPain !== null) {
        const niftySpot = _safeNum(ms.nifty_spot ?? data.market_signals_detail?.nifty_spot);
        const diff = niftySpot ? Math.round(maxPain - niftySpot) : null;
        const diffStr = diff !== null ? ` (${diff >= 0 ? "+" : ""}${diff} pts from spot)` : "";
        const cls = diff === null ? "neutral" : (Math.abs(diff) < 100 ? "positive" : "neutral");
        rows.push({ name: "⚖️ Max Pain Level", value: `${maxPain}${diffStr}`, category: "Options OI Gravity Zone", status: "🟡 MAGNETIC LEVEL — Market drawn here by expiry", cls });
    }

    // 5c. Top OI Call & Put Strikes
    const topCall = _safeNum(ms.top_oi_call_strike ?? data.market_signals_detail?.top_oi_call_strike);
    const topPut  = _safeNum(ms.top_oi_put_strike  ?? data.market_signals_detail?.top_oi_put_strike);
    if (topCall !== null) {
        rows.push({ name: "🔴 OI Call Wall (Resistance)", value: `${topCall}`, category: "Options OI — Max Call Writers", status: "🔴 HEAVY CALL OI — Key resistance zone for next expiry", cls: "negative" });
    }
    if (topPut !== null) {
        rows.push({ name: "🟢 OI Put Wall (Support)", value: `${topPut}`, category: "Options OI — Max Put Writers", status: "🟢 HEAVY PUT OI — Key support zone for next expiry", cls: "positive" });
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

    // ── 3-Analyst Intraday Debate Committee ──
    renderIntradayDebateCommittee(intraday.debate);
}

const _INTRADAY_PERSONA_META = {
    momentum_scalper: { icon: "🚀", title: "Momentum Scalper", sub: "ORB Breakout & Trend" },
    wall_defender:    { icon: "🛡️", title: "Wall Defender", sub: "OI Resistance & Option Seller" },
    tactical_scalper: { icon: "⚖️", title: "Tactical Manager", sub: "Pullbacks & R:R Execution" },
};

function renderIntradayDebateCommittee(debate) {
    const section = document.getElementById("intraday-debate-section");
    const grid = document.getElementById("intraday-debate-cards-grid");
    const structBadge = document.getElementById("intraday-debate-structure-badge");
    const consBadge = document.getElementById("intraday-debate-consensus-badge");
    const entryEl = document.getElementById("intraday-judge-entry");
    const targetEl = document.getElementById("intraday-judge-target");
    const slEl = document.getElementById("intraday-judge-sl");
    const actionEl = document.getElementById("intraday-judge-action");
    const ratEl = document.getElementById("intraday-judge-rationale");

    if (!section || !grid) return;

    if (!debate || typeof debate !== "object" || !debate.momentum_scalper) {
        section.style.display = "none";
        return;
    }

    section.style.display = "block";

    // Badges
    if (structBadge) {
        const s = (debate.structure || "SCALP DIPS").replace(/_/g, " ");
        structBadge.textContent = s;
        if (s.includes("CALL") || s.includes("BUY") || s.includes("DIPS")) {
            structBadge.style.background = "rgba(34,197,94,0.15)";
            structBadge.style.color = "#4ade80";
            structBadge.style.borderColor = "rgba(34,197,94,0.3)";
        } else if (s.includes("PUT") || s.includes("PULLBACKS")) {
            structBadge.style.background = "rgba(239,68,68,0.15)";
            structBadge.style.color = "#f87171";
            structBadge.style.borderColor = "rgba(239,68,68,0.3)";
        } else {
            structBadge.style.background = "rgba(245,158,11,0.15)";
            structBadge.style.color = "#fbbf24";
            structBadge.style.borderColor = "rgba(245,158,11,0.3)";
        }
    }

    if (consBadge) {
        const consText = debate.consensus || "MAJORITY";
        consBadge.textContent = consText;
        if (consText === "UNANIMOUS") {
            consBadge.style.background = "rgba(34,197,94,0.15)";
            consBadge.style.color = "#4ade80";
            consBadge.style.borderColor = "rgba(34,197,94,0.3)";
        } else if (consText === "SPLIT") {
            consBadge.style.background = "rgba(239,68,68,0.15)";
            consBadge.style.color = "#f87171";
            consBadge.style.borderColor = "rgba(239,68,68,0.3)";
        } else {
            consBadge.style.background = "rgba(99,102,241,0.15)";
            consBadge.style.color = "#a5b4fc";
            consBadge.style.borderColor = "rgba(99,102,241,0.3)";
        }
    }

    // Populate 3 cards
    grid.innerHTML = "";
    for (const [key, meta] of Object.entries(_INTRADAY_PERSONA_META)) {
        const p = debate[key];
        if (!p) continue;

        const card = document.createElement("div");
        card.style.cssText = `
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.07);
            border-radius: 8px;
            padding: 12px;
            display: flex;
            flex-direction: column;
            gap: 6px;
        `;

        const v = (p.verdict || "WAIT").replace(/_/g, " ");
        let vColor = "#94a3b8";
        let vBg = "rgba(148,163,184,0.15)";
        if (v.includes("CALL") || v.includes("BUY") || v.includes("DIPS")) {
            vColor = "#4ade80"; vBg = "rgba(34,197,94,0.15)";
        } else if (v.includes("PUT") || v.includes("PULLBACKS")) {
            vColor = "#f87171"; vBg = "rgba(239,68,68,0.15)";
        } else if (v.includes("RANGE") || v.includes("OPTION")) {
            vColor = "#fbbf24"; vBg = "rgba(245,158,11,0.15)";
        }

        let extraLevel = "";
        if (p.trigger_level) extraLevel = `<div style="font-size:0.72rem;color:#38bdf8;">Trigger: ₹${p.trigger_level}</div>`;
        else if (p.key_wall) extraLevel = `<div style="font-size:0.72rem;color:#f59e0b;">Key Wall: ₹${p.key_wall}</div>`;
        else if (p.entry_zone) extraLevel = `<div style="font-size:0.72rem;color:#a78bfa;">Entry: ${escapeHtml(String(p.entry_zone))}</div>`;

        card.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span style="font-size:0.78rem;font-weight:600;color:#f1f5f9;">${meta.icon} ${meta.title}</span>
                <span style="font-size:0.70rem;padding:2px 7px;border-radius:4px;background:${vBg};color:${vColor};border:1px solid ${vColor}44;font-weight:700;">${escapeHtml(v)}</span>
            </div>
            <div style="font-size:0.70rem;color:var(--text-muted,#94a3b8);">${meta.sub} · ${p.confidence || 70}% Conf</div>
            <div style="font-size:0.76rem;color:var(--text-secondary,#cbd5e1);line-height:1.4;margin-top:2px;">
                ${escapeHtml(p.rationale || "--")}
            </div>
            ${extraLevel}
        `;
        grid.appendChild(card);
    }

    // Judge Box
    if (entryEl) entryEl.textContent = debate.entry_zone || "--";
    if (targetEl) targetEl.textContent = debate.target ? `₹${debate.target}` : "--";
    if (slEl) slEl.textContent = debate.stop_loss ? `₹${debate.stop_loss}` : "--";
    if (actionEl) actionEl.textContent = debate.action_plan || "--";
    if (ratEl) ratEl.textContent = debate.judge_rationale || "";
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

    const syncExitDebateBtn = document.getElementById("btn-sync-exit-debate");
    if (syncExitDebateBtn) {
        syncExitDebateBtn.addEventListener("click", () => {
            const entrySpotInput = document.getElementById("entry-spot");
            if (!entrySpotInput || !entrySpotInput.value) {
                if (presetBtn) presetBtn.click();
            }
            evaluateLiveExit(true);
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

    // Initialize expiry day badge (Tuesday in IST)
    const todayIST = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
    const isExpiryDay = todayIST.getDay() === 2; // 0=Sun, 1=Mon, 2=Tue
    const expiryBadgeEl = document.getElementById("expiry-day-badge");
    if (expiryBadgeEl) expiryBadgeEl.style.display = isExpiryDay ? "block" : "none";

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

    // Show expiry day badge if today is Tuesday (IST, effective Sep 2025)
    const todayIST = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
    const isExpiryDay = todayIST.getDay() === 2; // 0=Sun, 1=Mon, 2=Tue
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


function render3StepActionPlan(actionText, actionBox, data) {
    if (!actionBox || !actionText) return;
    const verdict = (data.verdict || "HOLD_AND_RIDE").toUpperCase();
    const cleanVerdict = verdict.replace(/_/g, " ");
    actionBox.className = "exit-action-box " + verdict.toLowerCase();

    // Urgency badge
    const urgencyBadge = document.getElementById("exit-action-urgency-badge");
    if (urgencyBadge) {
        const urgency = (data.urgency || "NORMAL").toUpperCase();
        urgencyBadge.style.display = "inline-block";
        if (urgency === "CRITICAL" || verdict.includes("EMERGENCY") || verdict.includes("FULL_EXIT") || verdict.includes("PRE_CLOSE")) {
            urgencyBadge.textContent = "⚡ IMMEDIATE EXECUTION";
            urgencyBadge.style.background = "rgba(239, 68, 68, 0.25)";
            urgencyBadge.style.color = "#fca5a5";
            urgencyBadge.style.borderColor = "rgba(239, 68, 68, 0.45)";
        } else if (urgency === "HIGH" || verdict.includes("PARTIAL_BOOK_70")) {
            urgencyBadge.textContent = "⚠️ HIGH PRIORITY";
            urgencyBadge.style.background = "rgba(249, 115, 22, 0.25)";
            urgencyBadge.style.color = "#fdba74";
            urgencyBadge.style.borderColor = "rgba(249, 115, 22, 0.45)";
        } else if (urgency === "MEDIUM" || verdict.includes("PARTIAL") || verdict.includes("TRAIL_SL_TIGHT")) {
            urgencyBadge.textContent = "🎯 TACTICAL ACTION";
            urgencyBadge.style.background = "rgba(234, 179, 8, 0.2)";
            urgencyBadge.style.color = "#fde047";
            urgencyBadge.style.borderColor = "rgba(234, 179, 8, 0.4)";
        } else {
            urgencyBadge.textContent = "🛡️ DISCIPLINE / HOLD";
            urgencyBadge.style.background = "rgba(34, 197, 94, 0.18)";
            urgencyBadge.style.color = "#86efac";
            urgencyBadge.style.borderColor = "rgba(34, 197, 94, 0.35)";
        }
    }

    // Read trade parameters from DOM & payload
    const posSide = (document.getElementById("exit-pos-side")?.value || "").toUpperCase();
    const isOptionSeller = posSide.includes("SHORT");
    const isOptionBuyer = posSide.includes("BUY");
    const isBullish = posSide.includes("CE") || posSide.includes("LONG") || posSide === "SHORT_PE";

    const entrySpot = parseFloat(document.getElementById("exit-entry-spot")?.value) || 0;
    const entryPrem = parseFloat(document.getElementById("exit-entry-price")?.value) || 0;
    const currPrem = parseFloat(document.getElementById("exit-current-price")?.value) || 0;

    const slVal = data.trailing_sl || (entrySpot > 0 ? entrySpot : null);
    const slStr = slVal ? `₹${Number(slVal).toLocaleString("en-IN")}` : "Cost (Breakeven)";

    // Live spot approximation for points difference
    let liveSpot = 0;
    const spotMatch = data.reasoning?.match(/(\d{5}(?:\.\d+)?)/);
    if (spotMatch) {
        liveSpot = parseFloat(spotMatch[1]);
    } else if (data.live_spot) {
        liveSpot = parseFloat(data.live_spot);
    }
    const ptsDiff = (liveSpot && slVal) ? Math.abs(liveSpot - slVal).toFixed(1) : null;
    const directionWord = isBullish ? "below" : "above";

    // ── STEP 1: Stop-Loss Protection ─────────────────────────────────────────
    let step1Title = `Trail Stop to ${slStr} (Spot)`;
    let step1Bullets = [];

    if (verdict.includes("FULL_EXIT") || verdict.includes("EMERGENCY") || verdict.includes("PRE_CLOSE")) {
        step1Title = `Liquidate Position Immediately`;
        step1Bullets.push(`Exit 100% open lots immediately at market price.`);
        step1Bullets.push(`Structural invalidation or hard stop triggered. Halt risk bleed.`);
    } else if (verdict === "PARTIAL_BOOK_70") {
        step1Title = `Book 70% Profit & Trail Stop`;
        step1Bullets.push(`Execute market order to bank profit on 70% lots immediately.`);
        step1Bullets.push(`Move trailing SL on remaining 30% strictly to <strong>${slStr}</strong>.`);
    } else if (verdict === "PARTIAL_BOOK_50") {
        step1Title = `Book 50% Profit & Trail Stop`;
        step1Bullets.push(`Execute market order to bank profit on 50% lots immediately.`);
        step1Bullets.push(`Move trailing SL on remaining 50% strictly to <strong>${slStr}</strong>.`);
    } else {
        if (slVal) {
            const ptsNote = ptsDiff ? ` (just ${ptsDiff} pts ${directionWord} current market price)` : "";
            step1Bullets.push(`Move your underlying trailing SL to <strong>${slStr.replace('₹', '')}</strong>${ptsNote}.`);
        } else {
            step1Bullets.push(`Maintain a disciplined stop-loss at <strong>Cost (Breakeven)</strong> to protect capital.`);
        }
        if (isOptionSeller && entryPrem > 0 && currPrem > 0) {
            const optSl = Math.round(currPrem + (entryPrem - currPrem) * 0.25);
            const lockProfit = Math.max(0, Math.round(entryPrem - optSl));
            step1Bullets.push(`If trading by option premium, set an option SL around <strong>₹${optSl}</strong> (locking in ~₹${lockProfit}/share profit from your ₹${entryPrem} entry).`);
        } else if (isOptionBuyer && entryPrem > 0 && currPrem > 0) {
            const optSl = currPrem > entryPrem ? Math.round(entryPrem + (currPrem - entryPrem) * 0.5) : Math.round(entryPrem * 0.72);
            step1Bullets.push(`If trading by option premium, set an option SL around <strong>₹${optSl}</strong> to lock profits.`);
        }
    }

    // ── STEP 2: Position Sizing & Discipline ─────────────────────────────────
    let step2Title = `Hold Current Size (No Additions)`;
    let step2Bullets = [];

    if (verdict.includes("FULL_EXIT") || verdict.includes("EMERGENCY") || verdict.includes("PRE_CLOSE")) {
        step2Title = `Cancel All Broker Orders`;
        step2Bullets.push(`Cancel all pending broker limit and stop orders on terminal.`);
        step2Bullets.push(`Ensure zero unmanaged order exposure remains.`);
    } else if (verdict === "PARTIAL_BOOK_70") {
        step2Title = `Capital Defense Lock (Remaining 30%)`;
        step2Bullets.push(`Keep remaining 30% lots running as a risk-free trend runner.`);
        step2Bullets.push(`Guarantee zero-risk status: do not add to winning runner.`);
    } else if (verdict === "PARTIAL_BOOK_50") {
        step2Title = `Capital Defense Lock (Remaining 50%)`;
        step2Bullets.push(`Keep remaining 50% lots running for trend continuation.`);
        step2Bullets.push(`Move stop-loss strictly to entry cost to guarantee breakeven.`);
    } else {
        step2Bullets.push(`Keep 100% of the position running.`);
        step2Bullets.push(`Do not average down or scale in due to the +5% VIX spike.`);
    }

    // ── STEP 3: Take-Profit Triggers ─────────────────────────────────────────
    let step3Title = `Take-Profit Triggers`;
    let step3Bullets = [];

    if (verdict.includes("FULL_EXIT") || verdict.includes("EMERGENCY") || verdict.includes("PRE_CLOSE")) {
        step3Title = `Re-Entry Discipline`;
        step3Bullets.push(`Trade thesis invalidated under current market microstructure.`);
        step3Bullets.push(`Do not re-enter until fresh confirmation establishes clear edge.`);
    } else {
        if (isOptionSeller && entryPrem > 0 && currPrem > 0) {
            const targetPrem = Math.max(10, Math.round(currPrem * 0.64));
            const decayPct = Math.round(((entryPrem - targetPrem) / entryPrem) * 100);
            step3Bullets.push(`If premium hits <strong>₹${targetPrem}</strong> (≈${decayPct}% decay) → <strong>Book 50% lots</strong>.`);
        } else if (isOptionBuyer && currPrem > 0) {
            const targetPrem = Math.round(currPrem * 1.35);
            step3Bullets.push(`If premium hits <strong>₹${targetPrem}</strong> (+35% expansion) → <strong>Book 50% lots</strong>.`);
        }

        // Spot target calculation
        const baseSpot = liveSpot || entrySpot || 23428;
        const targetSpot = isBullish ? Math.round(Math.ceil(baseSpot / 50) * 50) + 25 : Math.round(Math.floor(baseSpot / 50) * 50) - 25;
        const wallStrike = isBullish ? targetSpot + 25 : targetSpot - 25;
        const wallName = isBullish ? "Call wall" : "Put wall";
        step3Bullets.push(`If Spot touches <strong>${targetSpot.toLocaleString("en-IN")}</strong> (approaching the ${wallStrike.toLocaleString("en-IN")} ${wallName}) → <strong>Book 50% lots</strong>.`);

        // Breach cutoff
        const breachVerb = isBullish ? "drops below" : "rises above";
        step3Bullets.push(`If Spot ${breachVerb} <strong>${slStr.replace('₹', '')}</strong> → <strong>Exit all lots instantly</strong>.`);
    }

    const steps = [
        { num: "1", icon: "🎯", title: step1Title, bullets: step1Bullets },
        { num: "2", icon: "🛡️", title: step2Title, bullets: step2Bullets },
        { num: "3", icon: "💰", title: step3Title, bullets: step3Bullets },
    ];

    const html = `
        <div style="margin-bottom:10px;font-size:0.80rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">
            📋 3-Step Execution Plan
        </div>
        <div class="action-3step-container" style="display:flex;flex-direction:column;gap:10px;">
            ${steps.map(s => `
                <div class="action-step-card" style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.09);border-radius:8px;padding:10px 14px;">
                    <div class="action-step-header" style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
                        <span style="font-size:0.95rem;">${s.icon}</span>
                        <span class="action-step-title" style="font-size:0.90rem;font-weight:700;color:#f8fafc;">${s.title}</span>
                    </div>
                    <ul class="action-step-bullets" style="margin:0;padding-left:18px;font-size:0.82rem;line-height:1.55;color:#cbd5e1;">
                        ${s.bullets.map(b => `<li style="margin-bottom:3px;">${b}</li>`).join("")}
                    </ul>
                </div>
            `).join("")}
        </div>
    `;

    actionText.innerHTML = html;
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

    render3StepActionPlan(actionText, actionBox, data);

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

    // ── Institutional ECI Gauge & 5 Pillars ──
    const eciScoreVal = document.getElementById("exit-eci-score-val");
    const eciUrgencyBadge = document.getElementById("exit-eci-urgency-badge");
    const eciProgress = document.getElementById("exit-eci-progress");
    const eciScore = (data.eci_score !== undefined && data.eci_score !== null) ? data.eci_score : 40;
    const urgency = data.urgency || "NORMAL";

    if (eciScoreVal) eciScoreVal.textContent = `${eciScore}/100`;
    if (eciProgress) eciProgress.style.width = `${eciScore}%`;
    if (eciUrgencyBadge) {
        eciUrgencyBadge.textContent = `${urgency} URGENCY`;
        const badgeColors = {
            NORMAL: "background:rgba(34,197,94,0.18);color:#4ade80;border:1px solid rgba(34,197,94,0.35);",
            MEDIUM: "background:rgba(245,158,11,0.18);color:#fbbf24;border:1px solid rgba(245,158,11,0.35);",
            HIGH: "background:rgba(249,115,22,0.18);color:#fb923c;border:1px solid rgba(249,115,22,0.35);",
            CRITICAL: "background:rgba(239,68,68,0.22);color:#f87171;border:1px solid rgba(239,68,68,0.45);",
        };
        eciUrgencyBadge.style.cssText = `font-size:0.70rem;font-weight:800;padding:2px 8px;border-radius:6px;${badgeColors[urgency] || badgeColors.NORMAL}`;
    }

    const bd = data.eci_breakdown || {};
    const subPa = document.getElementById("eci-sub-pa");
    const subOf = document.getElementById("eci-sub-of");
    const subOi = document.getElementById("eci-sub-oi");
    const subTd = document.getElementById("eci-sub-td");
    const subMc = document.getElementById("eci-sub-mc");
    if (subPa) subPa.textContent = bd.price_action !== undefined ? `${bd.price_action}` : "--";
    if (subOf) subOf.textContent = bd.order_flow !== undefined ? `${bd.order_flow}` : "--";
    if (subOi) subOi.textContent = bd.oi_greeks !== undefined ? `${bd.oi_greeks}` : "--";
    if (subTd) subTd.textContent = bd.time_decay !== undefined ? `${bd.time_decay}` : "--";
    if (subMc) subMc.textContent = bd.macro_intermarket !== undefined ? `${bd.macro_intermarket}` : "--";

    // ── Continuous Excursion & Microstructure Indicators ──
    const mfeEl = document.getElementById("exit-mfe-text");
    const maeEl = document.getElementById("exit-mae-text");
    const atrEl = document.getElementById("exit-atr-text");
    const cvdEl = document.getElementById("exit-cvd-text");

    if (mfeEl) {
        const mfeVal = data.mfe_pct !== undefined ? `${data.mfe_pct > 0 ? '+' : ''}${data.mfe_pct}%` : "--";
        const lockStr = data.mfe_locked ? " (Locked)" : "";
        mfeEl.textContent = `${mfeVal}${lockStr}`;
    }
    if (maeEl) {
        maeEl.textContent = data.mae_pct !== undefined ? `${data.mae_pct}%` : "--";
    }
    if (atrEl) {
        atrEl.textContent = data.atr_trail_level ? `₹${data.atr_trail_level.toLocaleString("en-IN")}` : "--";
    }
    if (cvdEl) {
        cvdEl.textContent = data.cvd_divergence || "NEUTRAL";
    }

    // ── Session ID & Manual Exit Button ──
    const sessionLabel = document.getElementById("exit-session-id-label");
    const closeBtn = document.getElementById("btn-manual-close-trade");
    window.currentExitSessionId = data.session_id || window.currentExitSessionId;

    if (sessionLabel) {
        sessionLabel.textContent = window.currentExitSessionId || "None";
    }

    if (closeBtn && !closeBtn.dataset.wired) {
        closeBtn.dataset.wired = "true";
        closeBtn.addEventListener("click", async () => {
            if (!window.currentExitSessionId) {
                alert("No active trade session to close.");
                return;
            }
            if (!confirm(`Are you sure you want to exit and mark trade session ${window.currentExitSessionId} as CLOSED?`)) {
                return;
            }
            try {
                closeBtn.disabled = true;
                closeBtn.textContent = "Closing...";
                const res = await fetch("/api/exit-advisor/close", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ session_id: window.currentExitSessionId, reason: "MANUAL_EXIT" })
                });
                const json = await res.json();
                if (json.status === "success") {
                    alert(`✅ Trade Exited Successfully!\nRealized Spot P&L: ${json.session.realized_spot_pnl_pct || 0}%\nRealized Premium P&L: ${json.session.realized_premium_pnl_pct || 0}%`);
                    window.currentExitSessionId = null;
                    if (sessionLabel) sessionLabel.textContent = "CLOSED";
                    closeBtn.style.display = "none";
                } else {
                    alert("Failed to close session: " + json.message);
                }
            } catch (err) {
                alert("Error closing session: " + err);
            } finally {
                closeBtn.disabled = false;
                closeBtn.textContent = "🚪 Close & Exit Trade Now";
            }
        });
    }


    // Contrarian Shield Banner
    const contrarianShield = document.getElementById("exit-contrarian-shield");
    const contrarianTitle = document.getElementById("exit-contrarian-title");
    const contrarianDesc = document.getElementById("exit-contrarian-desc");
    const contrarianWarn = data.contrarian_warning || (data.social_sentiment && data.social_sentiment.contrarian_warning);
    if (contrarianShield && contrarianWarn) {
        contrarianShield.style.display = "block";
        if (contrarianTitle) contrarianTitle.textContent = "🛡️ Contrarian Trap Shield Active";
        if (contrarianDesc) contrarianDesc.textContent = contrarianWarn;
    } else if (contrarianShield) {
        contrarianShield.style.display = "none";
    }

    // CogniGraph Regime Memory Banner
    const cognigraphBanner = document.getElementById("exit-cognigraph-banner");
    const cognigraphTag = document.getElementById("exit-cognigraph-regime-tag");
    const cognigraphText = document.getElementById("exit-cognigraph-precedent-text");
    if (cognigraphBanner && (data.cognigraph_regime || data.cognigraph_regime_precedent)) {
        cognigraphBanner.style.display = "block";
        if (cognigraphTag) cognigraphTag.textContent = data.cognigraph_regime || "REGIME ACTIVE";
        if (cognigraphText) cognigraphText.textContent = data.cognigraph_regime_precedent || "Active market regime matching causal history.";
    } else if (cognigraphBanner) {
        cognigraphBanner.style.display = "none";
    }

    // 3-Tier Scale-Out Execution Plan Card
    const scaleOutCard = document.getElementById("exit-scale-out-card");
    const tier1Text = document.getElementById("tier-1-text");
    const tier2Text = document.getElementById("tier-2-text");
    const tier3Text = document.getElementById("tier-3-text");
    const scaleOutPlan = data.scale_out_plan || (data.debate && data.debate.scale_out_plan);
    if (scaleOutCard && scaleOutPlan) {
        scaleOutCard.style.display = "block";
        if (tier1Text) tier1Text.textContent = scaleOutPlan.tier_1 || "--";
        if (tier2Text) tier2Text.textContent = scaleOutPlan.tier_2 || "--";
        if (tier3Text) tier3Text.textContent = scaleOutPlan.tier_3 || "--";
    } else if (scaleOutCard) {
        scaleOutCard.style.display = "none";
    }

    // Render Multi-Persona Exit Debate Committee cards
    renderExitDebateCommittee(data.debate, data.debate_consensus, data);
}

const _EXIT_PERSONA_META = {
    runner_analyst:   { icon: "🏃", title: "Runner Analyst", sub: "Momentum & Trend" },
    capital_guardian: { icon: "🛡️", title: "Capital Guardian", sub: "Risk & Theta Defense" },
    tactical_manager: { icon: "⚖️", title: "Tactical Manager", sub: "Scale-Out & Sizing" },
};

function renderExitDebateCommittee(debate, consensus, data) {
    const fullSection = document.getElementById("exit-advisor-debate-full-section");
    const section = document.getElementById("exit-debate-section");
    const grid = document.getElementById("exit-debate-cards-grid");
    const badge = document.getElementById("exit-debate-consensus-badge");
    const judgeBox = document.getElementById("exit-judge-note-box");
    const judgeText = document.getElementById("exit-judge-note-text");

    // Full-width badges and elements
    const fullStructBadge = document.getElementById("exit-full-debate-structure-badge");
    const fullConsBadge = document.getElementById("exit-full-debate-consensus-badge");
    const fullJudgeSl = document.getElementById("exit-full-judge-sl");
    const fullJudgeCons = document.getElementById("exit-full-judge-consensus");
    const fullJudgeAction = document.getElementById("exit-full-judge-action");
    const fullJudgeRationale = document.getElementById("exit-full-judge-rationale");

    if (!debate || typeof debate !== "object") {
        if (fullSection) fullSection.style.display = "none";
        if (section) section.style.display = "none";
        return;
    }

    if (fullSection) fullSection.style.display = "block";
    if (section) section.style.display = "block";

    const consText = consensus || (debate ? debate.consensus : null) || "MAJORITY";

    if (badge) {
        badge.textContent = consText;
        if (consText === "UNANIMOUS") {
            badge.style.background = "rgba(34,197,94,0.15)";
            badge.style.color = "#4ade80";
            badge.style.borderColor = "rgba(34,197,94,0.3)";
        } else if (consText === "SPLIT") {
            badge.style.background = "rgba(239,68,68,0.15)";
            badge.style.color = "#f87171";
            badge.style.borderColor = "rgba(239,68,68,0.3)";
        } else {
            badge.style.background = "rgba(99,102,241,0.15)";
            badge.style.color = "#a5b4fc";
            badge.style.borderColor = "rgba(99,102,241,0.3)";
        }
    }

    if (fullConsBadge) {
        fullConsBadge.textContent = consText;
        if (consText === "UNANIMOUS") {
            fullConsBadge.style.background = "rgba(34,197,94,0.15)";
            fullConsBadge.style.color = "#4ade80";
            fullConsBadge.style.borderColor = "rgba(34,197,94,0.3)";
        } else if (consText === "SPLIT") {
            fullConsBadge.style.background = "rgba(239,68,68,0.15)";
            fullConsBadge.style.color = "#f87171";
            fullConsBadge.style.borderColor = "rgba(239,68,68,0.3)";
        } else {
            fullConsBadge.style.background = "rgba(99,102,241,0.15)";
            fullConsBadge.style.color = "#a5b4fc";
            fullConsBadge.style.borderColor = "rgba(99,102,241,0.3)";
        }
    }

    if (data && data.verdict && fullStructBadge) {
        const v = data.verdict.replace(/_/g, " ");
        fullStructBadge.textContent = v;
        const bg = _verdictBg(data.verdict);
        const border = _verdictBorder(data.verdict);
        fullStructBadge.style.background = bg;
        fullStructBadge.style.borderColor = border;
        if (data.verdict.includes("HOLD")) fullStructBadge.style.color = "#4ade80";
        else if (data.verdict.includes("EXIT")) fullStructBadge.style.color = "#f87171";
        else fullStructBadge.style.color = "#fbbf24";
    }

    if (data && fullJudgeAction && data.action) {
        fullJudgeAction.textContent = data.action;
    }

    if (data && fullJudgeSl && data.trailing_sl) {
        fullJudgeSl.textContent = `₹${data.trailing_sl}`;
    }

    if (fullJudgeCons) {
        fullJudgeCons.textContent = consText;
    }

    if (judgeBox && judgeText && debate && debate.judge_rationale) {
        judgeBox.style.display = "block";
        judgeText.textContent = debate.judge_rationale;
    }

    if (fullJudgeRationale && debate && debate.judge_rationale) {
        fullJudgeRationale.textContent = debate.judge_rationale;
    }

    // Full-Width Judge Scale-Out Plan
    const fullScaleOutBox = document.getElementById("exit-full-scale-out-box");
    const fullTier1 = document.getElementById("exit-full-tier-1");
    const fullTier2 = document.getElementById("exit-full-tier-2");
    const fullTier3 = document.getElementById("exit-full-tier-3");
    const plan = data?.scale_out_plan || debate?.scale_out_plan;
    if (fullScaleOutBox && plan) {
        fullScaleOutBox.style.display = "block";
        if (fullTier1) fullTier1.innerHTML = `<strong style="color:#4ade80;">Tier 1 (Lock):</strong> ${escapeHtml(plan.tier_1 || "--")}`;
        if (fullTier2) fullTier2.innerHTML = `<strong style="color:#fbbf24;">Tier 2 (Defend):</strong> ${escapeHtml(plan.tier_2 || "--")}`;
        if (fullTier3) fullTier3.innerHTML = `<strong style="color:#a5b4fc;">Tier 3 (Runner):</strong> ${escapeHtml(plan.tier_3 || "--")}`;
    } else if (fullScaleOutBox) {
        fullScaleOutBox.style.display = "none";
    }

    if (!debate || typeof debate !== "object") return;

    // Render inner cards grid
    if (grid) {
        grid.innerHTML = "";
        for (const [key, meta] of Object.entries(_EXIT_PERSONA_META)) {
            const p = debate[key];
            if (!p) continue;

            const card = document.createElement("div");
            card.style.cssText = `
                background: rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 8px;
                padding: 10px;
                display: flex;
                flex-direction: column;
                gap: 6px;
            `;

            const v = (p.verdict || "HOLD").replace(/_/g, " ");
            const bg = _verdictBg(p.verdict);
            const border = _verdictBorder(p.verdict);

            card.innerHTML = `
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-size:0.75rem;font-weight:600;color:#f1f5f9;">${meta.icon} ${meta.title}</span>
                    <span style="font-size:0.68rem;padding:2px 6px;border-radius:4px;background:${bg};border:1px solid ${border};font-weight:700;letter-spacing:0.02em;">${escapeHtml(v)}</span>
                </div>
                <div style="font-size:0.70rem;color:var(--text-muted,#94a3b8);">${meta.sub} · ${p.confidence || 70}% Conf</div>
                <div style="font-size:0.75rem;color:var(--text-secondary,#cbd5e1);line-height:1.35;margin-top:2px;">
                    ${escapeHtml(p.rationale || "--")}
                </div>
                ${p.suggested_sl ? `<div style="font-size:0.68rem;color:#f59e0b;margin-top:2px;">Suggested SL: ₹${p.suggested_sl}</div>` : ""}
            `;
            grid.appendChild(card);
        }
    }

    // Update full-width persona cards
    const runner = debate.runner_analyst;
    if (runner) {
        const vEl = document.getElementById("exit-verdict-runner");
        const mEl = document.getElementById("exit-meta-runner");
        const rEl = document.getElementById("exit-rationale-runner");
        const sEl = document.getElementById("exit-sl-runner");
        if (vEl && runner.verdict) {
            vEl.textContent = runner.verdict.replace(/_/g, " ");
            vEl.style.background = _verdictBg(runner.verdict);
            vEl.style.borderColor = _verdictBorder(runner.verdict);
        }
        if (mEl) mEl.textContent = `Momentum & Trend Expansion · ${runner.confidence || 80}% Conf`;
        if (rEl && runner.rationale) rEl.textContent = runner.rationale;
        if (sEl && runner.suggested_sl) sEl.textContent = `Suggested SL: ₹${runner.suggested_sl}`;
    }

    const guardian = debate.capital_guardian;
    if (guardian) {
        const vEl = document.getElementById("exit-verdict-guardian");
        const mEl = document.getElementById("exit-meta-guardian");
        const rEl = document.getElementById("exit-rationale-guardian");
        const sEl = document.getElementById("exit-sl-guardian");
        if (vEl && guardian.verdict) {
            vEl.textContent = guardian.verdict.replace(/_/g, " ");
            vEl.style.background = _verdictBg(guardian.verdict);
            vEl.style.borderColor = _verdictBorder(guardian.verdict);
        }
        if (mEl) mEl.textContent = `Theta Decay & Capital Defense · ${guardian.confidence || 85}% Conf`;
        if (rEl && guardian.rationale) rEl.textContent = guardian.rationale;
        if (sEl && guardian.suggested_sl) sEl.textContent = `Suggested SL: ₹${guardian.suggested_sl}`;
    }

    const tactical = debate.tactical_manager;
    if (tactical) {
        const vEl = document.getElementById("exit-verdict-tactical");
        const mEl = document.getElementById("exit-meta-tactical");
        const rEl = document.getElementById("exit-rationale-tactical");
        const sEl = document.getElementById("exit-sl-tactical");
        if (vEl && tactical.verdict) {
            vEl.textContent = tactical.verdict.replace(/_/g, " ");
            vEl.style.background = _verdictBg(tactical.verdict);
            vEl.style.borderColor = _verdictBorder(tactical.verdict);
        }
        if (mEl) mEl.textContent = `Scale-Out & Risk-Reward · ${tactical.confidence || 75}% Conf`;
        if (rEl && tactical.rationale) rEl.textContent = tactical.rationale;
        if (sEl && tactical.suggested_sl) sEl.textContent = `Suggested SL: ₹${tactical.suggested_sl}`;
    }
}

const _DIMENSION_META = {
    greeks_decay:      { icon: "📐", label: "Greeks & Decay" },
    oi_pcr:            { icon: "📊", label: "OI / PCR" },
    heavyweights:      { icon: "🏛️", label: "Heavyweights" },
    price_action:      { icon: "📈", label: "Price Action" },
    vix_regime:        { icon: "⚡", label: "VIX Regime" },
    macro_global:      { icon: "🌍", label: "Macro & Global" },
    social_contrarian: { icon: "👥", label: "Social Contrarian" },
    mfe_mae:           { icon: "🎯", label: "MFE / MAE Excursion" },
    order_flow:        { icon: "🌊", label: "Microstructure & Flow" },
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

async function autoLoadLatestAnalysis() {
    try {
        const res = await fetch("/api/history");
        const json = await res.json();
        if (json.status !== "success") return;
        const allRuns = [...(json.manual || []), ...(json.scheduled || [])];
        if (allRuns.length === 0) return;

        const latestRun = allRuns.find(r => r.filename && r.filename.startsWith("analysis_")) || allRuns[0];
        if (!latestRun || !latestRun.filename) return;

        const detailRes = await fetch(`/api/history/${encodeURIComponent(latestRun.filename)}`);
        const detailJson = await detailRes.json();
        if (detailJson.status === "success" && detailJson.data) {
            renderDashboard(detailJson.data);
            console.log("Auto-loaded latest analysis:", latestRun.filename);

            const hash = (window.location.hash || "").replace("#", "").toLowerCase();
            if (hash && ["btst", "intraday", "exit-advisor", "history"].includes(hash)) {
                switchTab(hash);
            }
        }
    } catch (e) {
        console.warn("Auto-load latest analysis error:", e);
    }
}

// Initialize on DOM load
document.addEventListener("DOMContentLoaded", () => {
    initExitAdvisor();
    autoLoadLatestAnalysis();
    fetchAndRenderInstitutionalRadar();
    initCogniGraphTabListeners();
    initWalkForwardSimulationListeners();

    const hash = (window.location.hash || "").replace("#", "").toLowerCase();
    if (hash && ["btst", "intraday", "exit-advisor", "history", "cognigraph"].includes(hash)) {
        switchTab(hash);
    }
});

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Institutional BTST & Next-Day Prediction Radar
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const _INST_PROVIDERS = [
    { key: "religare",    label: "Religare\n(Ajit Mishra)" },
    { key: "anand_rathi", label: "Anand Rathi\nResearch" },
    { key: "hdfc_sec",    label: "HDFC\nSecurities" },
    { key: "indiacharts", label: "IndiaCharts\n(Rohit S.)" },
    { key: "consensus",   label: "🧭 Street\nConsensus" },
];

const _MATRIX_ROWS = [
    { key: "next_day_bias", label: "🧭 Next-Day Bias",    cls: "inst-row-bias",  field: "next_day_bias" },
    { key: "r2",            label: "🎯 R2 Resistance",    cls: "inst-row-r2",   field: "r2" },
    { key: "r1",            label: "📈 R1 Resistance",    cls: "inst-row-r1",   field: "r1" },
    { key: "spot",          label: "◆ Live NIFTY Spot",  cls: "inst-row-spot", field: "__spot__" },
    { key: "s1",            label: "🛡️ S1 Support",       cls: "inst-row-s1",   field: "s1" },
    { key: "s2",            label: "🛑 S2 Support",       cls: "inst-row-s2",   field: "s2" },
    { key: "gap",           label: "🔁 Expected Gap",     cls: "inst-row-bias", field: "expected_gap" },
    { key: "thesis",        label: "📝 BTST Thesis",      cls: "",               field: "thesis" },
];

function _instBiasPill(bias) {
    if (!bias) return '<span class="inst-bias-pill inst-bias-range">—</span>';
    const b = String(bias).toUpperCase();
    if (b.includes("BULL"))  return `<span class="inst-bias-pill inst-bias-bull">🟢 BULLISH</span>`;
    if (b.includes("BEAR"))  return `<span class="inst-bias-pill inst-bias-bear">🔴 BEARISH</span>`;
    return `<span class="inst-bias-pill inst-bias-range">⚖️ RANGEBOUND</span>`;
}

function _instGapPill(gap) {
    if (!gap) return '—';
    const g = String(gap).toUpperCase();
    if (g.includes("POS") || g.includes("UP"))  return `<span class="inst-bias-pill inst-bias-bull">⬆️ Positive Gap</span>`;
    if (g.includes("NEG") || g.includes("DOWN")) return `<span class="inst-bias-pill inst-bias-bear">⬇️ Negative Gap</span>`;
    return `<span class="inst-bias-pill inst-bias-range">↔️ Flat</span>`;
}

function _formatLevel(val) {
    if (!val && val !== 0) return '<span style="color:var(--text-muted);">—</span>';
    const s = String(val);
    // Zone string like "24100 — 24350"
    if (s.includes("—") || s.includes("-")) {
        const parts = s.split(/[—\-]/);
        return parts.map(p => {
            const n = parseInt(p.replace(/,/g, "").trim());
            return isNaN(n) ? p.trim() : `<span class="inst-confluence-zone inst-conf-r">₹${n.toLocaleString("en-IN")}</span>`;
        }).join('<span style="color:var(--text-muted);padding:0 4px;">–</span>');
    }
    const n = parseInt(s.replace(/,/g, "").trim());
    if (isNaN(n)) return val;
    return `<span class="inst-confluence-zone">₹${n.toLocaleString("en-IN")}</span>`;
}

function _instActionBadge(action) {
    if (!action) return '—';
    const a = action.toUpperCase();
    if (a.includes("BUY"))     return `<span class="inst-action inst-action-buy">BUY</span>`;
    if (a.includes("SELL"))    return `<span class="inst-action inst-action-sell">SELL</span>`;
    if (a.includes("UPGRADE")) return `<span class="inst-action inst-action-upgrade">UPGRADE</span>`;
    if (a.includes("CUT") || a.includes("REDUCE")) return `<span class="inst-action inst-action-cut">TARGET CUT</span>`;
    if (a.includes("RAISED"))  return `<span class="inst-action inst-action-upgrade">TARGET RAISED</span>`;
    if (a.includes("HOLD") || a.includes("NEUTRAL")) return `<span class="inst-action inst-action-hold">HOLD</span>`;
    return `<span class="inst-action inst-action-hold">${action}</span>`;
}

function renderInstitutionalRadar(data) {
    const radar = data && data.institutional_radar;
    const section = document.getElementById("institutional-radar-section");
    if (!section) return;

    // Always show the section
    section.style.display = "";

    // ─── Tab Switcher Wiring (Unconditional) ───────────────────────────────
    const tabBtns = document.querySelectorAll(".inst-tab-btn");
    tabBtns.forEach(btn => {
        btn.onclick = () => {
            tabBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            const tab = btn.dataset.tab;
            const matrixPanel = document.getElementById("inst-panel-matrix");
            const brokeragePanel = document.getElementById("inst-panel-brokerage");
            if (matrixPanel) matrixPanel.style.display = tab === "matrix" ? "" : "none";
            if (brokeragePanel) brokeragePanel.style.display = tab === "brokerage" ? "" : "none";
        };
    });

    const badge = document.getElementById("inst-consensus-badge");

    if (!radar || Object.keys(radar).length === 0) {
        if (badge) {
            badge.style.background = "rgba(100,100,100,0.2)";
            badge.style.color = "var(--text-muted)";
            badge.textContent = "⏰ Awaiting Cache";
        }
        // Show awaiting cache state
        const matrixBody = document.getElementById("inst-matrix-body");
        if (matrixBody) {
            matrixBody.innerHTML =
                `<tr><td colspan="6" class="inst-empty">
                    ⏰ Awaiting first scheduled run (08:30 / 15:15 / 17:30 IST).<br>
                    <small>Institutional predictions are refreshed automatically — no data during market hours before first run.</small>
                </td></tr>`;
        }
        const brokerageBody = document.getElementById("inst-brokerage-body");
        if (brokerageBody) {
            brokerageBody.innerHTML =
                `<tr><td colspan="5" class="inst-empty">No brokerage calls cached yet.</td></tr>`;
        }
        if (!_instRadarFetching) {
            fetchAndRenderInstitutionalRadar();
        }
        return;
    }

    const providerCalls = radar.provider_calls || {};
    const consensus = radar.consensus || {};
    const niftySpot = radar.nifty_spot;
    const hasProviders = Object.keys(providerCalls).length > 0;
    const hasBrokerage = Array.isArray(radar.brokerage_calls) && radar.brokerage_calls.length > 0;

    // ─── Consensus Badge ──────────────────────────────────────────────────
    if (badge) {
        if (!hasProviders && !hasBrokerage) {
            badge.style.background = "rgba(100,100,100,0.2)";
            badge.style.color = "var(--text-muted)";
            badge.textContent = "⏰ Awaiting Run";
        } else {
            const consensusBias = radar.consensus_bias || consensus.next_day_bias || "RANGEBOUND";
            const bullPct = radar.bull_pct != null ? radar.bull_pct : (consensus.bull_pct || 0);
            const b = consensusBias.toUpperCase();
            let bg = "rgba(251,191,36,0.15)";
            let color = "#fde68a";
            if (b.includes("BULL")) { bg = "rgba(34,197,94,0.15)"; color = "#86efac"; }
            if (b.includes("BEAR")) { bg = "rgba(239,68,68,0.15)"; color = "#fca5a5"; }
            badge.style.background = bg;
            badge.style.color = color;
            badge.textContent = `${bullPct}% Bullish · ${consensusBias}`;
        }
    }

    // ─── Timestamp ────────────────────────────────────────────────────────
    const tsEl = document.getElementById("inst-radar-timestamp");
    if (tsEl && radar.fetched_at_ist) tsEl.textContent = `Cached: ${radar.fetched_at_ist}`;

    // ─── Matrix Table: Providers in columns, Levels in rows ───────────────

    // Build header columns
    const headerRow = document.getElementById("inst-matrix-header");
    if (headerRow) {
        let headHtml = `<th class="inst-level-col">Level / Dimension</th>`;
        _INST_PROVIDERS.forEach(p => {
            headHtml += `<th style="text-align:center;white-space:pre-line;">${p.label.replace(/\n/g, "<br>")}</th>`;
        });
        headerRow.innerHTML = headHtml;
    }

    // Build matrix body rows
    const tbody = document.getElementById("inst-matrix-body");
    if (!tbody) return;

    let bodyHtml = "";

    _MATRIX_ROWS.forEach(row => {
        bodyHtml += `<tr class="${row.cls}">`;
        bodyHtml += `<td>${row.label}</td>`;

        _INST_PROVIDERS.forEach(p => {
            const call = p.key === "consensus" ? consensus : (providerCalls[p.key] || {});
            let cellHtml = "";

            if (row.field === "__spot__") {
                // Spot row: same for all columns
                if (niftySpot) {
                    cellHtml = `<span class="inst-conf-spot">₹${Number(niftySpot).toLocaleString("en-IN")}</span>`;
                } else {
                    cellHtml = `<span style="color:var(--text-muted);">Live data</span>`;
                }
            } else if (row.field === "next_day_bias") {
                cellHtml = _instBiasPill(call[row.field]);
            } else if (row.field === "expected_gap") {
                cellHtml = _instGapPill(call[row.field]);
            } else if (row.field === "thesis") {
                const t = call.thesis || "";
                const link = call.source_link && call.source_link !== "#"
                    ? `<a href="${call.source_link}" target="_blank" rel="noopener" style="color:rgba(165,180,252,0.6);font-size:0.7rem;"> [src]</a>`
                    : "";
                cellHtml = t
                    ? `<span class="inst-thesis-text">${t}${link}</span>`
                    : `<span style="color:var(--text-muted);">—</span>`;
            } else {
                // S1, S2, R1, R2
                const val = call[row.field];
                const isR = row.key.startsWith("r");
                const formatted = _formatLevel(val);
                if (val) {
                    cellHtml = `<span class="${isR ? 'inst-conf-r' : 'inst-conf-s'}">${formatted}</span>`;
                } else {
                    cellHtml = `<span style="color:var(--text-muted);">—</span>`;
                }
            }

            bodyHtml += `<td style="text-align:center;">${cellHtml}</td>`;
        });

        bodyHtml += "</tr>";
    });

    // Risk-reward row
    const matrix = radar.confluence_matrix || {};
    if (matrix.upside_pts != null || matrix.downside_pts != null) {
        const rr = matrix.rr_ratio ? `<b>${matrix.rr_ratio}:1</b>` : "—";
        const upPts = matrix.upside_pts != null ? `<span class="inst-conf-s">+${matrix.upside_pts} pts</span>` : "—";
        const dwPts = matrix.downside_pts != null ? `<span class="inst-conf-r">-${matrix.downside_pts} pts</span>` : "—";
        bodyHtml += `<tr style="background:rgba(129,140,248,0.05);border-top:1px solid rgba(129,140,248,0.2);">
            <td style="font-weight:700;">⚖️ Risk/Reward</td>
            <td colspan="5" style="text-align:center;">
                ${upPts} upside &nbsp;·&nbsp; ${dwPts} downside &nbsp;·&nbsp; R:R = ${rr}
            </td>
        </tr>`;
    }

    tbody.innerHTML = bodyHtml;

    // ─── Brokerage Radar Table ─────────────────────────────────────────────
    const brokerageBody = document.getElementById("inst-brokerage-body");
    const calls = radar.brokerage_calls || [];

    if (!brokerageBody) return;

    if (calls.length === 0) {
        brokerageBody.innerHTML = `<tr><td colspan="5" class="inst-empty">No brokerage calls in cache yet. Will populate on next scheduled run.</td></tr>`;
    } else {
        let brHtml = "";
        calls.forEach(c => {
            const tp = c.target_price ? `₹${Number(c.target_price).toLocaleString("en-IN")}` : "—";
            const upside = c.upside_pct != null ? `(${c.upside_pct > 0 ? "+" : ""}${c.upside_pct}%)` : "";
            const link = c.source_link && c.source_link !== "#"
                ? `<a href="${c.source_link}" target="_blank" rel="noopener" style="color:rgba(165,180,252,0.5);font-size:0.7rem;"> ↗</a>`
                : "";
            brHtml += `<tr>
                <td><b>${c.institution || "—"}</b></td>
                <td>${c.stock_name || c.stock_symbol || "—"}${link}</td>
                <td>${_instActionBadge(c.action)}</td>
                <td>${tp} ${upside}</td>
                <td style="color:var(--text-muted);font-size:0.76rem;">${c.sector || "—"}</td>
            </tr>`;
        });
        brokerageBody.innerHTML = brHtml;
    }
}

let _instRadarFetching = false;

// Helper: show/hide the stale-data warning badge and refresh button
function _updateInstStaleBadge(isStale, cacheAgeHours) {
    const staleBadge = document.getElementById("inst-stale-badge");
    const refreshBtn = document.getElementById("inst-refresh-btn");
    if (staleBadge) staleBadge.style.display = isStale ? "inline-block" : "none";
    if (refreshBtn) refreshBtn.style.display = isStale ? "inline-block" : "none";
    // Update timestamp colour as a visual hint
    const tsEl = document.getElementById("inst-radar-timestamp");
    if (tsEl && isStale) tsEl.style.color = "#fde047";
    else if (tsEl) tsEl.style.color = "";
}

// Also expose a standalone fetch for the /api/institutional-radar endpoint
async function fetchAndRenderInstitutionalRadar() {
    if (_instRadarFetching) return;
    _instRadarFetching = true;
    try {
        const res = await fetch("/api/institutional-radar");
        const json = await res.json();
        if (json && json.data && Object.keys(json.data).length > 0) {
            renderInstitutionalRadar({ institutional_radar: json.data });
            _updateInstStaleBadge(json.is_stale === true, json.cache_age_hours || 0);
        } else {
            const badge = document.getElementById("inst-consensus-badge");
            if (badge && badge.textContent === "Loading...") {
                badge.style.background = "rgba(100,100,100,0.2)";
                badge.style.color = "var(--text-muted)";
                badge.textContent = "⏰ Awaiting Cache";
            }
            // Show stale/refresh when no data at all
            _updateInstStaleBadge(true, 999);
        }
    } catch (e) {
        console.warn("Institutional radar fetch failed:", e);
        const badge = document.getElementById("inst-consensus-badge");
        if (badge && badge.textContent === "Loading...") {
            badge.style.background = "rgba(100,100,100,0.2)";
            badge.style.color = "var(--text-muted)";
            badge.textContent = "⏰ Standby";
        }
    } finally {
        _instRadarFetching = false;
    }
}

// Manual force-refresh triggered by the "Refresh Now" button
async function manualRefreshInstitutionalRadar() {
    const refreshBtn = document.getElementById("inst-refresh-btn");
    const staleBadge = document.getElementById("inst-stale-badge");
    const tsEl = document.getElementById("inst-radar-timestamp");
    if (refreshBtn) { refreshBtn.disabled = true; refreshBtn.textContent = "⏳ Fetching…"; }
    if (staleBadge) staleBadge.textContent = "⚠️ Refreshing…";
    try {
        // Pass current Nifty spot if available on the page
        const spotEl = document.getElementById("nifty-spot-display");
        const spotText = spotEl ? spotEl.textContent.replace(/[^\d.]/g, "") : "";
        const niftySpot = spotText ? parseFloat(spotText) : null;
        const res = await fetch("/api/institutional-radar/refresh", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(niftySpot ? { nifty_spot: niftySpot } : {}),
        });
        const json = await res.json();
        if (json && json.data && Object.keys(json.data).length > 0) {
            renderInstitutionalRadar({ institutional_radar: json.data });
            _updateInstStaleBadge(false, 0);
            if (tsEl) { tsEl.style.color = ""; }
        } else {
            if (staleBadge) staleBadge.textContent = "⚠️ Refresh failed — retry later";
            if (refreshBtn) { refreshBtn.disabled = false; refreshBtn.textContent = "🔄 Refresh Now"; }
        }
    } catch (e) {
        console.warn("Manual radar refresh failed:", e);
        if (staleBadge) staleBadge.textContent = "⚠️ Network error";
        if (refreshBtn) { refreshBtn.disabled = false; refreshBtn.textContent = "🔄 Refresh Now"; }
    }
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 🧠 CogniGraph Causal Memory & Dreaming Console
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

let activeCogniGraphPersona = "CONSERVATIVE";

async function loadCogniGraphData(persona = null) {
    if (persona) activeCogniGraphPersona = persona;
    const regimeBadge = document.getElementById("cognigraph-active-regime-badge");
    const personaTitle = document.getElementById("cognigraph-persona-title");
    const personaContent = document.getElementById("cognigraph-persona-content");
    const trapsList = document.getElementById("cognigraph-traps-list");
    const trapsCount = document.getElementById("cognigraph-traps-count");

    try {
        const res = await fetch(`/api/cognigraph?persona=${encodeURIComponent(activeCogniGraphPersona)}`);
        const json = await res.json();
        if (json.status !== "ok" || !json.data) return;

        const data = json.data;

        // Active Regime Signature
        if (regimeBadge) {
            regimeBadge.textContent = `REGIME: ${data.active_regime || "DEFAULT"}`;
        }

        // Persona Output Box
        if (personaTitle) {
            const icons = { CONSERVATIVE: "🛡️", AGGRESSIVE: "⚡", NEUTRAL: "⚖️", JUDGE: "👨‍⚖️" };
            personaTitle.textContent = `${icons[activeCogniGraphPersona] || "👤"} ${activeCogniGraphPersona} Causal Precedents`;
        }
        if (personaContent) {
            personaContent.textContent = data.persona_context || `No specific causal memory precedents retrieved for ${activeCogniGraphPersona}. Using baseline institutional priors.`;
        }

        // Active Failure Traps List
        if (trapsList) {
            const topTraps = data.top_traps || [];
            if (trapsCount) trapsCount.textContent = `${topTraps.length} active`;
            if (topTraps.length === 0) {
                trapsList.innerHTML = `<div style="font-size:0.76rem;color:var(--text-muted);padding:8px 0;">No active failure traps recorded for this regime yet.</div>`;
            } else {
                trapsList.innerHTML = topTraps.map(trap => {
                    const isNeg = (trap.polarity || "NEGATIVE") === "NEGATIVE";
                    const icon = isNeg ? "⚠️" : "💡";
                    const badgeClass = isNeg ? "negative" : "positive";
                    const weightPct = Math.round((trap.weight || 1.0) * 100);
                    return `
                        <div class="trap-card-item ${badgeClass}">
                            <div>
                                <span style="font-weight:700;color:#f8fafc;">${icon} ${escapeHtml(trap.subject || "")}</span>
                                <span style="opacity:0.65;"> · ${escapeHtml(trap.predicate || "")} · </span>
                                <span style="color:${isNeg ? '#f87171' : '#4ade80'};font-weight:600;">${escapeHtml(trap.object || "")}</span>
                            </div>
                            <span style="font-family:monospace;font-size:0.70rem;opacity:0.8;white-space:nowrap;padding:2px 6px;border-radius:4px;background:rgba(255,255,255,0.05);">
                                W:${weightPct}%
                            </span>
                        </div>
                    `;
                }).join("");
            }
        }
    } catch (e) {
        console.warn("loadCogniGraphData failed:", e);
    }
}

async function loadDreamingData() {
    const lastRunBadge = document.getElementById("dreaming-last-run-badge");
    const metricScore = document.getElementById("dreaming-metric-score");
    const metricTotal = document.getElementById("dreaming-metric-total");
    const metricLocks = document.getElementById("dreaming-metric-locks");
    const metricLethal = document.getElementById("dreaming-metric-lethal");
    const axiomsList = document.getElementById("dreaming-axioms-list");
    const axiomsCount = document.getElementById("dreaming-axioms-count");

    try {
        const res = await fetch("/api/dreaming/status");
        const json = await res.json();
        if (json.status !== "ok" || !json.data) return;

        const data = json.data;
        const report = data.latest_report || {};
        const audit = report.exit_advisor_audit || {};

        if (lastRunBadge) {
            lastRunBadge.textContent = report.timestamp ? `LAST RUN: ${report.timestamp.split(" ")[1] || report.timestamp}` : "STATUS: READY";
        }

        // Scorecard Metrics
        if (metricScore) {
            const score = audit.effectiveness_score_pct != null ? audit.effectiveness_score_pct : 100.0;
            metricScore.textContent = `${Math.round(score)}%`;
            metricScore.style.color = score >= 80 ? "#34d399" : score >= 50 ? "#fbbf24" : "#f87171";
        }
        if (metricTotal) {
            metricTotal.textContent = audit.total_exits_audited != null ? audit.total_exits_audited : (report.exit_episodes_processed || 0);
        }
        if (metricLocks) {
            metricLocks.textContent = audit.timely_profit_locks != null ? audit.timely_profit_locks : 0;
        }
        if (metricLethal) {
            metricLethal.textContent = audit.lethal_hold_errors != null ? audit.lethal_hold_errors : 0;
        }

        // Macro Axioms List
        if (axiomsList) {
            const axioms = data.macro_axioms || [];
            if (axiomsCount) axiomsCount.textContent = `${axioms.length} active`;
            if (axioms.length === 0) {
                axiomsList.innerHTML = `<div style="font-size:0.76rem;color:var(--text-muted);padding:8px 0;">No macro axioms synthesized yet. Click "Consolidate & Dream Now" to generate.</div>`;
            } else {
                axiomsList.innerHTML = axioms.map(ax => {
                    const rule = ax.rule || ax.description || ax.axiom_id;
                    const cleanId = (ax.axiom_id || "").replace(/_/g, " ");
                    return `
                        <div class="macro-axiom-card">
                            <div style="font-weight:700;color:#a5b4fc;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.04em;">
                                📜 ${escapeHtml(cleanId)}
                            </div>
                            <div style="color:#e2e8f0;font-size:0.76rem;">
                                ${escapeHtml(rule)}
                            </div>
                        </div>
                    `;
                }).join("");
            }
        }
    } catch (e) {
        console.warn("loadDreamingData failed:", e);
    }
}

async function loadTrajectoryStats() {
    const badge = document.getElementById("trajectory-episodes-count-badge");
    try {
        const res = await fetch("/api/trajectories/export?format=sharegpt");
        const json = await res.json();
        if (json && json.count != null && badge) {
            badge.textContent = `HARVESTED EPISODES: ${json.count}`;
        }
    } catch (e) {
        console.warn("loadTrajectoryStats failed:", e);
    }
}

function initCogniGraphTabListeners() {
    // Persona Pills
    const pills = document.querySelectorAll("#cognigraph-persona-pills .persona-pill-btn");
    pills.forEach(btn => {
        btn.addEventListener("click", () => {
            pills.forEach(p => p.classList.remove("active"));
            btn.classList.add("active");
            loadCogniGraphData(btn.dataset.persona);
        });
    });

    // Refresh Memory Button
    const refreshBtn = document.getElementById("btn-refresh-cognigraph");
    if (refreshBtn) {
        refreshBtn.addEventListener("click", () => {
            loadCogniGraphData();
            loadDreamingData();
            loadTrajectoryStats();
        });
    }

    // Run Dreaming Button
    const runDreamingBtn = document.getElementById("btn-run-dreaming");
    if (runDreamingBtn) {
        runDreamingBtn.addEventListener("click", async () => {
            runDreamingBtn.disabled = true;
            runDreamingBtn.innerHTML = `<span>⏳</span><span>Consolidating Memory...</span>`;
            try {
                const res = await fetch("/api/dreaming/run", { method: "POST" });
                const json = await res.json();
                if (json.status === "success") {
                    await loadDreamingData();
                    await loadCogniGraphData();
                    await loadTrajectoryStats();
                    alert("✅ Autonomous Dreaming consolidation completed successfully!");
                } else {
                    alert("Dreaming consolidation failed: " + (json.message || "Unknown error"));
                }
            } catch (e) {
                console.error("Dreaming error:", e);
                alert("Network error triggering dreaming consolidation.");
            } finally {
                runDreamingBtn.disabled = false;
                runDreamingBtn.innerHTML = `<span>🌙</span><span>Consolidate &amp; Dream Now</span>`;
            }
        });
    }

    // Trajectory Export & Local JSONL Download
    const downloadJsonlBtn = document.getElementById("btn-download-jsonl");
    const formatSelect = document.getElementById("trajectory-format-select");
    const exportSharegptBtn = document.getElementById("btn-export-sharegpt");
    const exportAlpacaBtn = document.getElementById("btn-export-alpaca");
    const exportDpoBtn = document.getElementById("btn-export-dpo");
    const exportStatus = document.getElementById("trajectory-export-status");

    function downloadAsLocalFile(content, filename, mimeType = "application/x-jsonlines") {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    async function triggerExport(fmt, downloadLocal = true) {
        if (exportStatus) {
            exportStatus.style.display = "inline-block";
            exportStatus.textContent = `Processing ${fmt.toUpperCase()} JSONL...`;
            exportStatus.style.color = "#a5b4fc";
        }
        try {
            if (fmt === "all") {
                const res = await fetch(`/api/trajectories/export?format=all`, { method: "POST" });
                const json = await res.json();
                if (json.status === "ok" && exportStatus) {
                    exportStatus.textContent = `✅ Saved all 3 formats to server disk! Initiating download...`;
                    exportStatus.style.color = "#34d399";
                }
                window.location.href = `/api/trajectories/export?format=sharegpt&download=1`;
                setTimeout(() => { if (exportStatus) exportStatus.style.display = "none"; }, 5000);
                return;
            }

            const res = await fetch(`/api/trajectories/export?format=${fmt}`, { method: "POST" });
            const json = await res.json();
            if (json.status === "ok") {
                const records = json.data || [];
                if (downloadLocal && records.length > 0) {
                    const jsonlLines = records.map(r => JSON.stringify(r)).join("\n") + "\n";
                    downloadAsLocalFile(jsonlLines, `nifty_trajectories_${fmt}.jsonl`);
                }
                if (exportStatus) {
                    exportStatus.textContent = `✅ Saved & downloaded ${json.count || records.length} ${fmt.toUpperCase()} episodes (.jsonl)!`;
                    exportStatus.style.color = "#34d399";
                    setTimeout(() => { if (exportStatus) exportStatus.style.display = "none"; }, 4500);
                }
            } else {
                throw new Error(json.message || "Export returned non-ok status");
            }
        } catch (e) {
            if (exportStatus) {
                exportStatus.textContent = `⚠️ Export failed: ${e.message || e}`;
                exportStatus.style.color = "#f87171";
            }
        }
    }

    if (downloadJsonlBtn) {
        downloadJsonlBtn.addEventListener("click", () => {
            const chosenFmt = formatSelect ? formatSelect.value : "sharegpt";
            triggerExport(chosenFmt, true);
        });
    }
    if (exportSharegptBtn) exportSharegptBtn.addEventListener("click", () => triggerExport("sharegpt", true));
    if (exportAlpacaBtn) exportAlpacaBtn.addEventListener("click", () => triggerExport("alpaca", true));
    if (exportDpoBtn) exportDpoBtn.addEventListener("click", () => triggerExport("dpo", true));
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Phase 6: Multi-Month Historical Walk-Forward Simulation
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async function loadWalkForwardSimulationData(forceRun = false) {
    const statusBadge = document.getElementById("walk-forward-status-badge");
    try {
        const url = forceRun ? "/api/simulation/walk-forward?force_run=1" : "/api/simulation/walk-forward";
        const res = await fetch(url);
        const json = await res.json();
        if (json.status === "ok" && json.data) {
            renderWalkForwardSimulation(json.data);
            if (statusBadge) {
                statusBadge.textContent = `${json.data.total_trades || 0} TRADES / ${json.data.simulation_config?.sessions_count || 126} SESSIONS`;
                statusBadge.style.color = "#34d399";
                statusBadge.style.borderColor = "rgba(52,211,153,0.3)";
                statusBadge.style.background = "rgba(52,211,153,0.1)";
            }
        }
    } catch (e) {
        console.warn("loadWalkForwardSimulationData failed:", e);
    }
}

function renderWalkForwardSimulation(data) {
    if (!data) return;

    // Metrics Scorecard
    const elReturn = document.getElementById("wf-metric-return");
    const elPnl = document.getElementById("wf-metric-pnl");
    const elSharpe = document.getElementById("wf-metric-sharpe");
    const elSortino = document.getElementById("wf-metric-sortino");
    const elDd = document.getElementById("wf-metric-drawdown");
    const elWinrate = document.getElementById("wf-metric-winrate");

    const retPct = data.cumulative_return_pct ?? 0;
    if (elReturn) {
        elReturn.textContent = `${retPct >= 0 ? "+" : ""}${retPct.toFixed(1)}%`;
        elReturn.style.color = retPct >= 0 ? "#34d399" : "#f87171";
    }

    const pnl = data.total_pnl_inr ?? 0;
    if (elPnl) {
        elPnl.textContent = `₹${pnl >= 0 ? "+" : ""}${Math.round(pnl).toLocaleString("en-IN")}`;
        elPnl.style.color = pnl >= 0 ? "#60a5fa" : "#f87171";
    }

    if (elSharpe) elSharpe.textContent = (data.sharpe_ratio ?? 0).toFixed(2);
    if (elSortino) elSortino.textContent = (data.sortino_ratio ?? 0).toFixed(2);
    if (elDd) elDd.textContent = `-${(data.max_drawdown_pct ?? 0).toFixed(1)}%`;
    if (elWinrate) {
        elWinrate.textContent = `${(data.win_rate_pct ?? 0).toFixed(1)}%`;
    }

    // Chart
    renderEquityCurveSVG(data.equity_curve || [], data.initial_capital);

    // Monthly Table
    const monthlyTbody = document.getElementById("wf-monthly-table-body");
    if (monthlyTbody) {
        const months = data.monthly_performance || [];
        if (months.length === 0) {
            monthlyTbody.innerHTML = `<tr><td colspan="4" style="padding:8px;color:var(--text-muted);text-align:center;">No monthly data</td></tr>`;
        } else {
            monthlyTbody.innerHTML = months.map(m => {
                const isProfitable = m.pnl_inr >= 0;
                return `
                    <tr style="border-bottom:1px solid rgba(255,255,255,0.04);">
                        <td style="padding:6px;font-weight:600;color:#f1f5f9;">${escapeHtml(m.month)}</td>
                        <td style="padding:6px;color:var(--text-muted);">${m.trades} (${m.wins}W)</td>
                        <td style="padding:6px;color:${m.win_rate >= 50 ? '#34d399' : '#f87171'};font-weight:600;">${m.win_rate}%</td>
                        <td style="padding:6px;text-align:right;font-weight:700;color:${isProfitable ? '#34d399' : '#f87171'};">
                            ${isProfitable ? "+" : ""}₹${Math.round(m.pnl_inr).toLocaleString("en-IN")}
                        </td>
                    </tr>
                `;
            }).join("");
        }
    }

    // Regime Table
    const regimeTbody = document.getElementById("wf-regime-table-body");
    if (regimeTbody) {
        const regimes = data.regime_performance || [];
        if (regimes.length === 0) {
            regimeTbody.innerHTML = `<tr><td colspan="4" style="padding:8px;color:var(--text-muted);text-align:center;">No regime data</td></tr>`;
        } else {
            regimeTbody.innerHTML = regimes.slice(0, 6).map(r => {
                const isProfitable = r.pnl_inr >= 0;
                return `
                    <tr style="border-bottom:1px solid rgba(255,255,255,0.04);">
                        <td style="padding:6px;font-family:monospace;font-size:0.70rem;color:#a5b4fc;">${escapeHtml(r.regime)}</td>
                        <td style="padding:6px;color:var(--text-muted);">${r.trades} (${r.wins}W)</td>
                        <td style="padding:6px;color:${r.win_rate >= 50 ? '#34d399' : '#f87171'};font-weight:600;">${r.win_rate}%</td>
                        <td style="padding:6px;text-align:right;font-weight:700;color:${isProfitable ? '#34d399' : '#f87171'};">
                            ${isProfitable ? "+" : ""}₹${Math.round(r.pnl_inr).toLocaleString("en-IN")}
                        </td>
                    </tr>
                `;
            }).join("");
        }
    }
}

function renderEquityCurveSVG(equityCurve, initialCapital = 100000) {
    const container = document.getElementById("wf-equity-chart-container");
    if (!container) return;
    if (!equityCurve || equityCurve.length < 2) {
        container.innerHTML = `<div style="text-align:center;padding:40px;color:var(--text-muted);font-size:0.80rem;">Insufficient equity data for chart</div>`;
        return;
    }

    const w = container.clientWidth || 600;
    const h = 150;
    const padding = { top: 15, right: 15, bottom: 20, left: 45 };

    const values = equityCurve.map(pt => pt.equity);
    const baseCapital = Number(initialCapital) || values[0] || 100000;
    let minVal = Math.min(...values, baseCapital) * 0.98;
    let maxVal = Math.max(...values, baseCapital) * 1.02;

    // Zero-variance protection: prevent minVal === maxVal producing NaN coordinates
    if (maxVal - minVal < 1e-6) {
        minVal = minVal * 0.95;
        maxVal = maxVal * 1.05 + 1.0;
    }
    const n = values.length;

    const scaleX = i => padding.left + (i / (n - 1)) * (w - padding.left - padding.right);
    const scaleY = val => h - padding.bottom - ((val - minVal) / (maxVal - minVal)) * (h - padding.top - padding.bottom);

    const baselineY = scaleY(baseCapital);

    const points = values.map((val, idx) => `${scaleX(idx).toFixed(1)},${scaleY(val).toFixed(1)}`).join(" ");

    // Fill area polygon
    const firstX = scaleX(0).toFixed(1);
    const lastX = scaleX(n - 1).toFixed(1);
    const bottomY = (h - padding.bottom).toFixed(1);
    const areaPoints = `${firstX},${bottomY} ${points} ${lastX},${bottomY}`;

    const lastVal = values[values.length - 1];
    const isUp = lastVal >= baseCapital;
    const strokeColor = isUp ? "#34d399" : "#f87171";
    const baseK = Math.round(baseCapital / 1000);

    const svgHtml = `
        <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" style="width:100%;height:100%;overflow:visible;">
            <defs>
                <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stop-color="${strokeColor}" stop-opacity="0.3" />
                    <stop offset="100%" stop-color="${strokeColor}" stop-opacity="0.0" />
                </linearGradient>
            </defs>
            <!-- Baseline -->
            <line x1="${padding.left}" y1="${baselineY}" x2="${w - padding.right}" y2="${baselineY}" stroke="rgba(255,255,255,0.15)" stroke-dasharray="3,3" stroke-width="1" />
            <text x="${padding.left + 4}" y="${baselineY - 4}" fill="rgba(255,255,255,0.4)" font-size="9" font-family="sans-serif">₹${baseK}k Base</text>

            <!-- Area Fill -->
            <polygon points="${areaPoints}" fill="url(#eqGrad)" />

            <!-- Curve Line -->
            <polyline points="${points}" fill="none" stroke="${strokeColor}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />

            <!-- Start & End Dots -->
            <circle cx="${scaleX(0)}" cy="${scaleY(values[0])}" r="3.5" fill="#94a3b8" />
            <circle cx="${scaleX(n - 1)}" cy="${scaleY(lastVal)}" r="4.5" fill="${strokeColor}" stroke="#ffffff" stroke-width="1.5" />

            <!-- Value Labels -->
            <text x="${w - padding.right - 2}" y="${scaleY(lastVal) - 6}" fill="${strokeColor}" font-size="10" font-weight="700" text-anchor="end" font-family="sans-serif">
                ₹${Math.round(lastVal).toLocaleString("en-IN")}
            </text>
        </svg>
    `;

    container.innerHTML = svgHtml;
}

function initWalkForwardSimulationListeners() {
    const runBtn = document.getElementById("btn-run-walk-forward");
    if (runBtn) {
        runBtn.addEventListener("click", async () => {
            runBtn.disabled = true;
            runBtn.innerHTML = `<span>⏳</span><span>Simulating 6 Months...</span>`;
            try {
                const res = await fetch("/api/simulation/walk-forward", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ months: 6, initial_capital: 100000, risk_profile: "BALANCED" }),
                });
                const json = await res.json();
                if (json.status === "ok" && json.data) {
                    renderWalkForwardSimulation(json.data);
                    const statusBadge = document.getElementById("walk-forward-status-badge");
                    if (statusBadge) {
                        statusBadge.textContent = `${json.data.total_trades || 0} TRADES / ${json.data.simulation_config?.sessions_count || 126} SESSIONS`;
                        statusBadge.style.color = "#34d399";
                    }
                } else {
                    alert("Walk-forward simulation failed: " + (json.message || "Unknown error"));
                }
            } catch (e) {
                console.error("Walk-forward error:", e);
                alert("Network error executing walk-forward simulation.");
            } finally {
                runBtn.disabled = false;
                runBtn.innerHTML = `<span>🚀</span><span>Run Walk-Forward Simulation</span>`;
            }
        });
    }
}

