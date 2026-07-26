"""analyzer.py — 官方账号过滤 + 情感研判

研判为两级漏斗：
  1) 词库加权打分（本文件 analyze）——高召回粗筛；
  2) 可选 LLM 复核（llm_refine）——只对粗筛出的负面候选精判，
     修正"打击黑恶势力专项行动"这类关键词误报。未配置 LLM 时跳过。
"""

from __future__ import annotations

import json
import logging

import requests

from config import Settings
from models import Weibo
from keywords import (
    CITY_NAME,
    OFFICIAL_NAME_STRONG, OFFICIAL_NAME_WEAK, OFFICIAL_REASONS, OFFICIAL_PHRASES,
    STRONG_NEGATIVE, MEDIUM_NEGATIVE, MILD_NEGATIVE, POSITIVE_CONTEXT, REGIONS,
)

log = logging.getLogger(__name__)

W_STRONG, W_MEDIUM, W_MILD, W_POS = 4, 2, 1, 2


# ══════════════ 官方号过滤 ══════════════

def is_official(w: Weibo) -> tuple[bool, str]:
    """返回 (是否官方号, 判定原因)。保留原因便于审计误杀。"""
    if w.verified_type >= 1:                     # 蓝V：机构认证
        return True, f"机构认证(vtype={w.verified_type})"

    for kw in OFFICIAL_NAME_STRONG:
        if kw in w.user:
            return True, f"昵称强特征[{kw}]"

    if w.verified:                               # 弱特征词仅对认证账号生效
        for kw in OFFICIAL_NAME_WEAK:
            if kw in w.user:
                return True, f"认证+昵称弱特征[{kw}]"

    for kw in OFFICIAL_REASONS:
        if kw in w.verified_reason:
            return True, f"认证信息[{kw}]"

    hits = [p for p in OFFICIAL_PHRASES if p in w.text]
    threshold = 1 if w.verified else 2           # 普通用户须命中2个通稿句式才过滤
    if len(hits) >= threshold:
        return True, f"通稿句式{hits[:3]}"

    return False, ""


# ══════════════ 词库打分 ══════════════

def analyze(w: Weibo) -> None:
    """就地填充 Weibo 的研判字段"""
    text = w.text
    w.strong_neg = [p for p in STRONG_NEGATIVE if p in text]
    w.medium_neg = [p for p in MEDIUM_NEGATIVE if p in text]
    w.mild_neg = [p for p in MILD_NEGATIVE if p in text]
    w.positive_ctx = [p for p in POSITIVE_CONTEXT if p in text]

    s, m, l, p = (len(w.strong_neg), len(w.medium_neg),
                  len(w.mild_neg), len(w.positive_ctx))
    raw = W_STRONG * s + W_MEDIUM * m + W_MILD * l - W_POS * p

    # 正面语境前置否决：整治/表彰类内容即使含"黑恶势力"等词也不判负
    if p >= 2 and p >= s + m:
        w.sentiment_label = "正面" if raw <= 0 else "关注"
        w.sentiment_score = 0.8 if raw <= 0 else 0.45
        return

    if raw >= 6:
        w.sentiment_label, w.sentiment_score = "负面", max(0.05, 0.5 - raw * 0.04)
    elif raw >= 3:
        w.sentiment_label, w.sentiment_score = "偏负面", 0.3
    elif raw >= 1 and (m >= 1 or l >= 2):
        w.sentiment_label, w.sentiment_score = "关注", 0.4
    elif raw <= -2:
        w.sentiment_label, w.sentiment_score = "正面", 0.8
    else:
        w.sentiment_label, w.sentiment_score = "中性", 0.5

    # 区县归属
    w.regions = [name for name, kws in REGIONS.items()
                 if any(kw in text for kw in kws) and name != CITY_NAME] or [CITY_NAME]


# ══════════════ 可选：LLM 复核 ══════════════

_LLM_SYSTEM = (
    f"你是地市级舆情研判助手。对每条微博判断其是否为公众对{CITY_NAME}（含区县）"
    "政务、民生、市场秩序等方面的负面反馈。官方通报、正面宣传、"
    "整治行动新闻、与本地无关的内容都不算负面。"
    '只输出JSON数组，每项形如 {"id":"...","label":"负面|偏负面|关注|中性|正面","reason":"15字内"}。'
)


def llm_refine(candidates: list[Weibo], settings: Settings, batch: int = 20) -> None:
    """对负面候选调用 OpenAI 兼容接口复核，失败时静默保留词库结论"""
    if not settings.llm_ready or not candidates:
        return
    url = settings.llm_api_base.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.llm_api_key}",
               "Content-Type": "application/json"}
    by_id = {w.id: w for w in candidates}

    for i in range(0, len(candidates), batch):
        chunk = candidates[i:i + batch]
        user_msg = json.dumps(
            [{"id": w.id, "text": w.text[:300]} for w in chunk],
            ensure_ascii=False,
        )
        try:
            resp = requests.post(url, headers=headers, timeout=60, json={
                "model": settings.llm_model,
                "temperature": 0,
                "messages": [{"role": "system", "content": _LLM_SYSTEM},
                             {"role": "user", "content": user_msg}],
            })
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            for item in json.loads(content):
                w = by_id.get(str(item.get("id", "")))
                label = item.get("label", "")
                if w and label in ("负面", "偏负面", "关注", "中性", "正面"):
                    if label != w.sentiment_label:
                        log.info("LLM 修正 %s: %s → %s (%s)",
                                 w.id, w.sentiment_label, label, item.get("reason", ""))
                    w.sentiment_label = label
                    w.llm_reason = item.get("reason", "")
        except (requests.RequestException, ValueError, KeyError) as e:
            log.warning("LLM 复核批次失败，保留词库结论: %s", e)
