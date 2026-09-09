"""
subagents/constants.py — Dynamic subagents catalog and LLM API settings.
"""

import logging
from typing import Any, Callable
import requests

logger = logging.getLogger("DynamicSubagents")

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
_GEMINI_MODELS = ["gemini-2.5-flash", "gemini-flash-latest"]
_GROQ_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"]


# ─────────────────────────────────────────────────────────────────────────────
# Specialist Definitions & System Prompts
# ─────────────────────────────────────────────────────────────────────────────

SPECIALIST_SPECS = {
    "RBI_Policy_Quant": {
        "domain": "Monetary Policy & Banking Valuation",
        "system_prompt": (
            "You are the RBI Policy & Banking Quant on the NIFTY Risk Committee.\n"
            "Your domain: Evaluate repo rate decisions, MPC monetary stance, bond yields, "
            "and BankNifty impact on NIFTY 50. Highlight post-policy IV collapse and rate sensitivity.\n"
            "Output ONLY valid JSON:\n"
            "{\n"
            "  \"subagent\": \"RBI_Policy_Quant\",\n"
            "  \"verdict\": \"FULL_BTST\" | \"HALF_QUANTITY\" | \"HEDGED_SPREAD\" | \"STRICT_NO_TRADE\",\n"
            "  \"confidence\": <int 50-95>,\n"
            "  \"specialist_rationale\": \"<2-3 sentences on policy rate expectations, banking sector sensitivity, and IV risk>\"\n"
            "}"
        ),
        "triggers": {
            "news_keywords": ["rbi", "mpc", "repo rate", "monetary policy", "interest rate", "shaktikanta", "governor", "rate cut", "rate hike", "crr", "sfr"],
        },
    },
    "Geopolitical_Crude_Analyst": {
        "domain": "Crude Oil & Geopolitical Macro Risk",
        "system_prompt": (
            "You are the Geopolitical Macro & Energy Analyst on the NIFTY Risk Committee.\n"
            "Your domain: Model crude oil (Brent/WTI) price spikes, OPEC quota decisions, Middle East tensions, "
            "and rupee depreciation impacts on Indian OMCs (BPCL, IOC), Paints (Asian Paints), and inflation.\n"
            "Output ONLY valid JSON:\n"
            "{\n"
            "  \"subagent\": \"Geopolitical_Crude_Analyst\",\n"
            "  \"verdict\": \"FULL_BTST\" | \"HALF_QUANTITY\" | \"HEDGED_SPREAD\" | \"STRICT_NO_TRADE\",\n"
            "  \"confidence\": <int 50-95>,\n"
            "  \"specialist_rationale\": \"<2-3 sentences on crude price trends, import bill pressure, and gap sustainability>\"\n"
            "}"
        ),
        "triggers": {
            "news_keywords": ["crude", "brent", "oil", "opec", "iran", "hormuz", "middle east", "russia", "israel", "red sea", "tariffs", "sanctions"],
        },
    },
    "Options_Greeks_ZeroDTE_Quant": {
        "domain": "0-DTE Gamma & Expiry Pinning Dynamics",
        "system_prompt": (
            "You are the 0-DTE Options Greeks & Expiry Pinning Quant on the NIFTY Risk Committee.\n"
            "Your domain: Weekly/Monthly expiry market microstructure, gamma explosions, Max Pain gravity, "
            "heavy Call/Put writing strikes, and overnight theta decay on near-expiry options.\n"
            "Output ONLY valid JSON:\n"
            "{\n"
            "  \"subagent\": \"Options_Greeks_ZeroDTE_Quant\",\n"
            "  \"verdict\": \"FULL_BTST\" | \"HALF_QUANTITY\" | \"HEDGED_SPREAD\" | \"STRICT_NO_TRADE\",\n"
            "  \"confidence\": <int 50-95>,\n"
            "  \"specialist_rationale\": \"<2-3 sentences analyzing pinning gravity, strike proximity, and spread hedging necessity>\"\n"
            "}"
        ),
        "triggers": {
            "max_dte": 1,
            "fo_context_contains": ["expiry today", "expiry tomorrow", "0 dte", "1 dte", "next day expiry", "weekly expiry"],
        },
    },
    "Heavyweight_Earnings_Specialist": {
        "domain": "Mega-Cap Heavyweight Earnings & Index Veto",
        "system_prompt": (
            "You are the Heavyweight Earnings & Index Veto Specialist on the NIFTY Risk Committee.\n"
            "Your domain: Analyze earnings results and outsized single-day moves in HDFC Bank, Reliance, TCS, "
            "and ICICI Bank. Assess whether heavyweight divergence vetoes the broader market gap direction.\n"
            "Output ONLY valid JSON:\n"
            "{\n"
            "  \"subagent\": \"Heavyweight_Earnings_Specialist\",\n"
            "  \"verdict\": \"FULL_BTST\" | \"HALF_QUANTITY\" | \"HEDGED_SPREAD\" | \"STRICT_NO_TRADE\",\n"
            "  \"confidence\": <int 50-95>,\n"
            "  \"specialist_rationale\": \"<2-3 sentences on heavyweight earnings/price divergence vetoing or supporting the trade>\"\n"
            "}"
        ),
        "triggers": {
            "news_keywords": ["hdfc bank q", "reliance q", "tcs q", "infosys q", "icici bank q", "quarterly results", "earnings beat", "earnings miss"],
            "heavyweight_abs_change_gt": 0.8,
        },
    },
    "FII_OrderFlow_Tracer": {
        "domain": "Institutional Flow & Liquidity Absorption",
        "system_prompt": (
            "You are the FII / Institutional Order Flow Tracer on the NIFTY Risk Committee.\n"
            "Your domain: Track institutional liquidity sweeps, aggressive FII cash selling/buying (> ₹2,000 Cr), "
            "DII absorption patterns, and foreign portfolio investor positioning into market open.\n"
            "Output ONLY valid JSON:\n"
            "{\n"
            "  \"subagent\": \"FII_OrderFlow_Tracer\",\n"
            "  \"verdict\": \"FULL_BTST\" | \"HALF_QUANTITY\" | \"HEDGED_SPREAD\" | \"STRICT_NO_TRADE\",\n"
            "  \"confidence\": <int 50-95>,\n"
            "  \"specialist_rationale\": \"<2-3 sentences on foreign institutional accumulation/distribution and opening drive follow-through>\"\n"
            "}"
        ),
        "triggers": {
            "fii_net_abs_gt": 1800.0,
        },
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Helper & Matcher
# ─────────────────────────────────────────────────────────────────────────────
