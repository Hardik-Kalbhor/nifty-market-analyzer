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
            # Enhanced grayscale & contrast
            enhanced_img = img.convert("L")
            enhanced_img = ImageEnhance.Contrast(enhanced_img).enhance(2.0)
            
            raw_text = pytesseract.image_to_string(enhanced_img)
            logger.info(f"Pytesseract extracted {len(raw_text)} characters in {time.time()-t0:.2f}s.")
            
            if len(raw_text.strip()) > 20:
                result = _parse_ocr_text_with_groq(raw_text)
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


def parse_ocr_raw_text(raw_text: str) -> dict[str, Any]:
    """Parses raw OCR text received directly from client-side or server OCR."""
    t0 = time.time()
    result = _parse_ocr_text_with_groq(raw_text)
    if result and result.get("strike"):
        result["extraction_engine"] = "Groq LLM OCR Parser"
        result["latency_sec"] = round(time.time() - t0, 2)
        return {"status": "success", "data": result}
    return {
        "status": "error",
        "message": "Could not identify active option contract from text. Please verify screenshot clarity."
    }


def _parse_ocr_text_with_groq(ocr_text: str) -> Optional[dict[str, Any]]:
    """
    Sends raw OCR text to Groq Cloud LLM (openai/gpt-oss-120b) with specialized Indian broker rules.
    """
    groq_key = os.environ.get("GROQ_API_KEY")
    if not groq_key:
        logger.warning("GROQ_API_KEY not configured for OCR parsing.")
        return None

    prompt = f"""
You are an expert Indian stock broker trading OCR parser.
Extract the open position parameters from the OCR text of a Dhan/Zerodha/Groww/AngelOne screenshot.

OCR Extracted Text:
\"\"\"
{ocr_text}
\"\"\"

Return ONLY a valid JSON object matching this schema:
{{
  "strike": string (e.g. "24100 CE" or "24100 CALL"),
  "position_side": "BUY_CE" | "BUY_PE" | "SHORT_CE" | "SHORT_PE" | "LONG_FUTURES" | "SHORT_FUTURES",
  "trade_type": "BTST" | "INTRADAY",
  "entry_premium": number (the purchase / avg price),
  "current_premium": number (the live market price / LTP),
  "entry_spot": number (Nifty spot index level shown on screen, else null),
  "pnl_amount": number (unrealized profit/loss in INR),
  "pnl_pct": number (percentage gain or loss),
  "oi_change_pct": number (OI change percent if visible, else null),
  "broker_detected": string (e.g. "Dhan Android" or "Dhan Web" or "Zerodha Kite")
}}

Mathematical Direction Rules:
- If a CALL option has entry_premium > current_premium and is in PROFIT (or P&L is positive), it means the trader SOLD the call -> position_side is 'SHORT_CE'.
- If a CALL option has entry_premium < current_premium and is in PROFIT, it is 'BUY_CE'.
- If a PUT option has entry_premium > current_premium and is in PROFIT, it is 'SHORT_PE'.
- If a PUT option has entry_premium < current_premium and is in PROFIT, it is 'BUY_PE'.
- If badge is 'Normal' or 'CarryForward' or 'NRML', trade_type is 'BTST'. If 'MIS' or 'Intraday', trade_type is 'INTRADAY'.
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

            return parsed
        else:
            logger.warning(f"Groq OCR parse failed HTTP {res.status_code}: {res.text[:200]}")
    except Exception as e:
        logger.warning(f"Error calling Groq for OCR parsing: {e}")

    return None
