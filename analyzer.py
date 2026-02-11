from __future__ import annotations

"""
analyzer.py — 官方账号过滤 + 情感分析
"""

try:
    from snownlp import SnowNLP
    HAS_SNOWNLP = True
except ImportError:
    HAS_SNOWNLP = False

from config import (
    OFFICIAL_NAME_KW, OFFICIAL_REASONS, OFFICIAL_PHRASES,
    STRONG_NEGATIVE, MEDIUM_NEGATIVE, MILD_NEGATIVE, POSITIVE_CONTEXT,
)


def is_official(w):
    # type: (dict) -> bool
    """True = 官方/媒体账号，应过滤"""
    username = w.get("user", "")
    vtype = w.get("verified_type", -1)
    vreason = w.get("verified_reason", "")
    text = w.get("text", "")

    if vtype is not None and vtype >= 1:
        return True

    for kw in OFFICIAL_NAME_KW:
        if kw in username:
            return True

    for kw in OFFICIAL_REASONS:
        if kw in vreason:
            return True

    count = 0
    for p in OFFICIAL_PHRASES:
        if p in text:
            count += 1
    if count >= 2:
        return True

    return False


def has_official_phrases(text):
    # type: (str) -> bool
    """正文含 >=1 个通稿句式"""
    for p in OFFICIAL_PHRASES:
        if p in text:
            return True
    return False


def analyze(text):
    # type: (str) -> dict
    """
    情感分析，返回:
      score, label, strong_neg, medium_neg, mild_neg, positive_ctx
    """
    result = {
        "score": 0.5,
        "label": "中性",
        "strong_neg": [],
        "medium_neg": [],
        "mild_neg": [],
        "positive_ctx": [],
    }

    result["strong_neg"]   = [p for p in STRONG_NEGATIVE  if p in text]
    result["medium_neg"]   = [p for p in MEDIUM_NEGATIVE  if p in text]
    result["mild_neg"]     = [p for p in MILD_NEGATIVE    if p in text]
    result["positive_ctx"] = [p for p in POSITIVE_CONTEXT if p in text]

    s_count = len(result["strong_neg"])
    m_count = len(result["medium_neg"])
    l_count = len(result["mild_neg"])
    p_count = len(result["positive_ctx"])

    # 1. 强负面：出现即判
    if s_count >= 1:
        result["label"] = "负面"
        result["score"] = 0.05
        return result

    # 2. 正面上下文翻转
    if p_count >= 2:
        result["label"] = "正面"
        result["score"] = 0.8
        return result

    # 3. 中等负面
    if m_count >= 2:
        result["label"] = "负面"
        result["score"] = 0.2
        return result
    if m_count == 1:
        result["label"] = "偏负面"
        result["score"] = 0.35
        return result

    # 4. 轻度负面
    if l_count >= 3:
        result["label"] = "关注"
        result["score"] = 0.4
        return result
    if l_count >= 1 and HAS_SNOWNLP:
        try:
            if SnowNLP(text).sentiments < 0.3:
                result["label"] = "偏负面"
                result["score"] = 0.3
                return result
        except Exception:
            pass

    # 5. 兜底
    if HAS_SNOWNLP and not result["positive_ctx"]:
        try:
            snlp = SnowNLP(text).sentiments
            result["score"] = round(snlp, 4)
            if snlp < 0.15:
                result["label"] = "关注"
        except Exception:
            pass

    return result