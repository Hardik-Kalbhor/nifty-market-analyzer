"""
OCR & Vision Extractor for Indian Stock Broker Trading Screens.
Supports Dhan (Mobile App & Web), Zerodha Kite, Groww, Angel One, and Upstox.
Uses enhanced grayscale contrast preprocessing + Groq / Gemini AI extraction.
"""

import io
import json
import logging
import os
import re
import time
from typing import Any, Optional
from PIL import Image, ImageEnhance
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("nifty_analyzer.ocr_extractor")

# Try importing pytesseract (if installed)
try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False


def extract_position_from_image(image_bytes: bytes) -> dict[str, Any]:
    """
    Extracts open options/futures position details from an uploaded image.
    Uses multi-stage extraction:
    1. Preprocesses image (grayscale + contrast enhancement).
    2. Runs OCR (Pytesseract) if available.
    3. Prompts Groq LLM (openai/gpt-oss-120b) with OCR text + broker rules.
    """
    t0 = time.time()
    
    # 1. Load and optimize image using Pillow
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
    except Exception as img_err:
        logger.error(f"Failed to open image: {img_err}")
        return {"status": "error", "message": "Invalid image file format."}

    # 2. Try Pytesseract OCR + Groq Cloud LLM
    if PYTESSERACT_AVAILABLE:
        try:
            import numpy as np
            
            # Detect red vs green badges in broker screenshots
            img_rgb = np.array(img.convert("RGB"))
            red_mask = (img_rgb[:, :, 0] > 180) & (img_rgb[:, :, 1] < 120) & (img_rgb[:, :, 2] < 120)
            green_mask = (img_rgb[:, :, 0] < 120) & (img_rgb[:, :, 1] > 150) & (img_rgb[:, :, 2] < 140)

            has_red_badge = bool(np.sum(red_mask) > 100)
            has_green_badge = bool(np.sum(green_mask) > 100)

            # 2x Lanczos upscaling for crystal clear text OCR
            w, h = img.size
            upscaled = img.resize((w * 2, h * 2), Image.Resampling.LANCZOS)
            gray = upscaled.convert("L")
            enhanced_img = ImageEnhance.Contrast(gray).enhance(2.0)
            
            raw_text = pytesseract.image_to_string(enhanced_img)
            logger.info(f"Pytesseract extracted {len(raw_text)} characters in {time.time()-t0:.2f}s (Red badge: {has_red_badge}, Green badge: {has_green_badge}).")
            
            if len(raw_text.strip()) > 20:
                result = _parse_ocr_text_with_groq(raw_text, has_red_badge, has_green_badge)
                if result and result.get("strike"):
                    result["extraction_engine"] = "Pytesseract OCR + Groq LLM"
                    result["latency_sec"] = round(time.time() - t0, 2)
                    return {"status": "success", "data": result}
        except Exception as ocr_err:
            logger.warning(f"Pytesseract OCR parsing error: {ocr_err}")

    return {
        "status": "error",
        "message": "Could not extract trading position from screenshot. Please enter parameters manually or ensure the contract name and prices are clearly visible."
    }


def parse_ocr_raw_text(raw_text: str, has_red_badge: bool = False, has_green_badge: bool = False) -> dict[str, Any]:
    """Parses raw OCR text received directly from client-side or server OCR."""
    t0 = time.time()
    result = _parse_ocr_text_with_groq(raw_text, has_red_badge, has_green_badge)
    if result and result.get("strike"):
        result["extraction_engine"] = "Groq LLM OCR Parser"
        result["latency_sec"] = round(time.time() - t0, 2)
        return {"status": "success", "data": result}
    return {
        "status": "error",
        "message": "Could not identify active option contract from text. Please verify screenshot clarity."
    }


def _parse_ocr_text_with_groq(ocr_text: str, has_red_badge: bool = False, has_green_badge: bool = False) -> Optional[dict[str, Any]]:
    """
    Sends raw OCR text to Groq Cloud LLM (openai/gpt-oss-120b) with specialized Indian broker rules
    combined with deterministic regex table verification.
    """
    # 1. Deterministic Table / Row Regex Extraction (Ground Truth)
    # Extracts rows matching: [Price] [Qty] [Total Value]
    table_rows = re.findall(r"(\d{2,4}\.\d{2})\s+[\+\-]?(\d{2,4})\s+([\d,]+\.\d{2})", ocr_text)
    m_avg = re.search(r"(?:Avg\s*Price|Type\s*Avg|Avg)\s*[\s\:\=]*(\d{2,4}\.\d{2})", ocr_text, re.IGNORECASE)
    m_ltp = re.search(r"(?:Live|LTP)\s*[\:\|\s]*(\d{2,4}\.\d{2})", ocr_text, re.IGNORECASE)
    
    table_entry_prem = None
    table_curr_prem = None
    if m_avg:
        table_entry_prem = float(m_avg.group(1))
    elif table_rows:
        table_entry_prem = float(table_rows[0][0])
        
    if m_ltp:
        table_curr_prem = float(m_ltp.group(1))
    elif len(table_rows) > 1:
        table_curr_prem = float(table_rows[1][0])

    groq_key = os.environ.get("GROQ_API_KEY")
    if not groq_key:
        logger.warning("GROQ_API_KEY not configured for OCR parsing.")
        return None

    # Check for text clues of Sell / Short
    has_sell_clue = (
        has_red_badge
        or bool(re.search(r"\bS\s+13\d|\bS\s+NIFTY|\bType\s+Avg.*?\bS\b|\bS\s+\d{2,4}", ocr_text, re.IGNORECASE))
        or bool(re.search(r"-\d{2,4}", ocr_text))  # Negative quantity e.g. -195
    )

    prompt = f"""
You are an expert Indian stock broker trading OCR parser (Dhan, Zerodha Kite, Groww, AngelOne, Upstox).
Analyze this OCR text and visual badge metadata from an active trading position screenshot.

Visual Color & Text Clues:
- Has Red Badge / Sell Clue (Denoting Sell / S / Short Position): {has_sell_clue or has_red_badge}
- Has Green Badge (Denoting Buy / B / Long Position): {has_green_badge}

OCR Extracted Text:
\"\"\"
{ocr_text}
\"\"\"

CRITICAL DIRECTION & PRICE RULES:
1. In Dhan / Indian brokers:
   - A RED box with 'S' denotes SELL / SHORT (Option Selling).
   - If Type is 'S' or quantity is negative (-195) or Red Badge is true, position_side MUST BE 'SHORT_CE' (for Call) or 'SHORT_PE' (for Put).
   - If Type is 'B' or quantity is positive (+195), position_side is 'BUY_CE' (for Call) or 'BUY_PE' (for Put).
2. Prices & Spot:
   - Entry Price is the 'Avg Price' in Position Summary (e.g. 134.10).
   - Current Price is the 'Live' / 'LTP' price (e.g. 123.10).
   - In Dhan, 'Underlying Spot' is the CURRENT LIVE index spot price, NOT the entry spot! Always return entry_spot as null.
3. If badge is 'Normal', 'CarryForward', 'NRML', or 'Delivery', trade_type is 'BTST'. If 'MIS' or 'Intraday', trade_type is 'INTRADAY'.

Return ONLY a valid JSON object matching this schema:
{{
  "strike": string (e.g. "24100 CE" or "24100 CALL"),
  "position_side": "SHORT_CE" | "SHORT_PE" | "BUY_CE" | "BUY_PE" | "LONG_FUTURES" | "SHORT_FUTURES",
  "trade_type": "BTST" | "INTRADAY",
  "entry_premium": number (the purchase / avg price),
  "current_premium": number (the live market price / LTP),
  "entry_spot": null,
  "pnl_amount": number (unrealized profit/loss in INR),
  "pnl_pct": number (percentage gain or loss),
  "oi_change_pct": number (OI change percent if visible, else null),
  "broker_detected": string (e.g. "Dhan Web" or "Dhan Android" or "Zerodha Kite")
}}
"""

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {groq_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "openai/gpt-oss-120b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=8)
        if res.status_code == 200:
            content = res.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            
            # Normalize strike name (e.g. "24100 CALL" -> "24100 CE")
            strike = str(parsed.get("strike", "")).strip()
            strike = re.sub(r"\bCALL\b", "CE", strike, flags=re.IGNORECASE)
            strike = re.sub(r"\bPUT\b", "PE", strike, flags=re.IGNORECASE)
            parsed["strike"] = strike

            # Underlying Spot is LIVE spot, NOT Entry spot -> Always null out entry_spot from screenshot
            parsed["entry_spot"] = None

            # Enforce deterministic table numbers if found
            if table_entry_prem is not None:
                parsed["entry_premium"] = table_entry_prem
            if table_curr_prem is not None:
                parsed["current_premium"] = table_curr_prem

            # Post-Processing: Force Direction if Red Badge or S detected
            if has_sell_clue or has_red_badge:
                if "CE" in strike.upper():
                    parsed["position_side"] = "SHORT_CE"
                elif "PE" in strike.upper():
                    parsed["position_side"] = "SHORT_PE"

            # Post-Processing: Mathematical Entry Premium reconstruction for Short Options
            pnl_pct = parsed.get("pnl_pct")
            curr_prem = parsed.get("current_premium")
            entry_prem = parsed.get("entry_premium")

            if pnl_pct is not None and curr_prem is not None:
                try:
                    p = float(pnl_pct)
                    c = float(curr_prem)
                    e = float(entry_prem) if entry_prem is not None else 0.0

                    if parsed["position_side"] in ["SHORT_CE", "SHORT_PE"]:
                        # Option Selling formula: profit when current drops below entry
                        # Entry = LTP / (1 - PnL/100) -> 123.10 / (1 - 0.082) = 134.10
                        reconstructed_entry = round(c / (1.0 - (p / 100.0)), 2)
                        if e <= 0 or abs(e - c) < 0.5:
                            parsed["entry_premium"] = reconstructed_entry
                    elif parsed["position_side"] in ["BUY_CE", "BUY_PE"]:
                        # Option Buying formula: profit when current rises above entry
                        # Entry = LTP / (1 + PnL/100)
                        reconstructed_entry = round(c / (1.0 + (p / 100.0)), 2)
                        if e <= 0 or abs(e - c) < 0.5:
                            parsed["entry_premium"] = reconstructed_entry
                except Exception as math_err:
                    logger.debug(f"Math reconstruction note: {math_err}")

            return parsed
        else:
            logger.warning(f"Groq OCR parse failed HTTP {res.status_code}: {res.text[:200]}")
    except Exception as e:
        logger.warning(f"Error calling Groq for OCR parsing: {e}")

    return None
