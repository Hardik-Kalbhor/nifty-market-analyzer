from .constants import (
    NEGATION_WORDS,
    BULLISH_PATTERNS, BEARISH_PATTERNS,
    BULLISH_SYNONYMS, BEARISH_SYNONYMS,
    BULLISH_KEYWORDS, BEARISH_KEYWORDS,
)
from datetime import datetime


def _is_negated(text: str, keyword_start_idx: int) -> bool:
    pre_text = text[max(0, keyword_start_idx - 60): keyword_start_idx].lower()
    pre_words = pre_text.split()[-5:]
    pre_snippet = " ".join(pre_words)
    return any(neg in pre_snippet for neg in NEGATION_WORDS)


def _get_recency_multiplier(published_date_str: str) -> float:
    if not published_date_str:
        return 0.7
    formats = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%B %d, %Y", "%d %b %Y"]
    pub_date = None
    for fmt in formats:
        try:
            pub_date = datetime.strptime(published_date_str.strip(), fmt)
            break
        except ValueError:
            continue
    if pub_date is None:
        return 0.7
    delta_days = (datetime.now() - pub_date).days
    if delta_days == 0:
        return 1.0
    elif delta_days == 1:
        return 0.65
    elif delta_days == 2:
        return 0.40
    else:
        return 0.25


def _score_sentiment(text: str) -> tuple[float, float, list[str], list[str]]:
    bull_score = 0.0
    bear_score = 0.0
    bull_matches: list[str] = []
    bear_matches: list[str] = []
    bull_matched_labels: set[str] = set()
    bear_matched_labels: set[str] = set()

    for pattern, weight, label in BULLISH_PATTERNS:
        if label in bull_matched_labels:
            continue
        m = pattern.search(text)
        if m:
            negated = _is_negated(text, m.start())
            if negated:
                bear_score += weight * 0.4
                bear_matches.append(f"[negated] {label}")
                bear_matched_labels.add(f"neg_{label}")
            else:
                bull_score += weight
                bull_matches.append(label)
                bull_matched_labels.add(label)

    for pattern, weight, label in BEARISH_PATTERNS:
        if label in bear_matched_labels:
            continue
        m = pattern.search(text)
        if m:
            negated = _is_negated(text, m.start())
            if negated:
                bull_score += weight * 0.4
                bull_matches.append(f"[negated] {label}")
                bull_matched_labels.add(f"neg_{label}")
            else:
                bear_score += weight
                bear_matches.append(label)
                bear_matched_labels.add(label)

    text_lower = text.lower()

    for canonical, synonyms in BULLISH_SYNONYMS.items():
        label = f"syn_{canonical}"
        if label in bull_matched_labels:
            continue
        for syn in synonyms:
            idx = text_lower.find(syn)
            if idx != -1:
                weight = BULLISH_KEYWORDS.get(canonical, 2)
                negated = _is_negated(text, idx)
                if negated:
                    bear_score += weight * 0.4
                    bear_matches.append(f"[negated] {syn}")
                else:
                    bull_score += weight
                    bull_matches.append(syn)
                    bull_matched_labels.add(label)
                break

    for canonical, synonyms in BEARISH_SYNONYMS.items():
        label = f"syn_{canonical}"
        if label in bear_matched_labels:
            continue
        for syn in synonyms:
            idx = text_lower.find(syn)
            if idx != -1:
                weight = BEARISH_KEYWORDS.get(canonical, 2)
                negated = _is_negated(text, idx)
                if negated:
                    bull_score += weight * 0.4
                    bull_matches.append(f"[negated] {syn}")
                else:
                    bear_score += weight
                    bear_matches.append(syn)
                    bear_matched_labels.add(label)
                break

    for keyword, weight in BULLISH_KEYWORDS.items():
        if keyword.lower().replace(" ", "_") in bull_matched_labels:
            continue
        idx = text_lower.find(keyword)
        if idx != -1:
            negated = _is_negated(text, idx)
            if negated:
                bear_score += weight * 0.4
            else:
                bull_score += weight
                bull_matches.append(keyword)

    for keyword, weight in BEARISH_KEYWORDS.items():
        if keyword.lower().replace(" ", "_") in bear_matched_labels:
            continue
        idx = text_lower.find(keyword)
        if idx != -1:
            negated = _is_negated(text, idx)
            if negated:
                bull_score += weight * 0.4
            else:
                bear_score += weight
                bear_matches.append(keyword)

    return bull_score, bear_score, bull_matches, bear_matches
