"""
Sentiment analysis module with negation checks, intensity weights,
source credibility, and recency decay. Acts as the single source of truth
for classifying news headlines sentiment and ticker relevance.
"""
import re
import math
from datetime import datetime
import pytz

WIB = pytz.timezone("Asia/Jakarta")

POS_LEXICON = {"naik": 1.0, "tumbuh": 1.0, "laba": 1.0, "untung": 1.0, "profit": 1.0,
               "bullish": 1.2, "rekor": 1.3, "melonjak": 1.8, "akuisisi": 1.0,
               "dividen": 1.0, "upgrade": 1.2, "surplus": 1.0, "raih": 0.8}
NEG_LEXICON = {"turun": -1.0, "rugi": -1.2, "gagal": -1.2, "krisis": -1.5,
               "downgrade": -1.2, "bearish": -1.2, "crash": -1.8, "anjlok": -1.8,
               "default": -1.5, "pailit": -1.8, "tunda": -0.7}

MACRO_CONTEXT_GUARD = ["kurs", "suku bunga", "inflasi", "the fed", "rupiah", "bi rate"]
NEGATORS = ["tidak", "belum", "bukan", "tanpa", "batal"]
INTENSIFIERS = {"sangat": 1.4, "drastis": 1.6, "tipis": 0.5, "sedikit": 0.5}
SOURCE_WEIGHT = {"idx_disclosure": 1.5, "stockbit": 1.0, "cnbc_indonesia": 1.0,
                  "kontan": 0.9, "antara_ekonomi": 0.9, "yfinance": 0.8}
RECENCY_TAU_HOURS = 24.0


def _score_headline(title: str) -> float:
    title_l = title.lower()
    if any(kw in title_l for kw in MACRO_CONTEXT_GUARD):
        return 0.0  # biarkan macro engine yang handle, hindari sinyal ganda yang kontradiktif

    words = re.findall(r"[a-zA-Z]+", title_l)
    score, hits = 0.0, 0
    for i, w in enumerate(words):
        base = POS_LEXICON.get(w) or NEG_LEXICON.get(w)
        if base is None:
            continue
        window = words[max(0, i - 3):i]
        negated = any(neg in window for neg in NEGATORS)
        intensity = next((f for mod, f in INTENSIFIERS.items() if mod in window), 1.0)
        score += base * intensity * (-1 if negated else 1)
        hits += 1
    return (score / hits) if hits else 0.0


def is_relevant_to_ticker(title: str, ticker: str, company_name: str = "") -> bool:
    """Cegah false-positive: 4 huruf yang kebetulan match ticker tapi bukan mention asli."""
    title_l = title.lower()
    if re.search(rf"\b{ticker.lower()}\b", title_l):
        return True
    return bool(company_name) and company_name.lower() in title_l


def combined_ticker_sentiment(articles: list[dict], now_ts: float | None = None) -> dict:
    now_ts = now_ts or datetime.now(WIB).timestamp()
    w_sum, w_total, n = 0.0, 0.0, 0
    for art in articles:
        raw = _score_headline(art["title"])
        if raw == 0.0:
            continue
        age_h = max(0.0, (now_ts - art.get("ts", now_ts)) / 3600.0)
        w = math.exp(-age_h / RECENCY_TAU_HOURS) * SOURCE_WEIGHT.get(art.get("source", ""), 0.8)
        w_sum += raw * w
        w_total += w
        n += 1

    score = round(w_sum / w_total, 3) if w_total > 0 else 0.0
    label = "🟢 Positif" if score >= 0.3 else "🔴 Negatif" if score <= -0.3 else "🟡 Netral"
    return {"score": score, "label": label, "n_headlines": n,
            "confidence": "⚠️ Low Confidence" if n < 2 else "✅ Confirmed"}
