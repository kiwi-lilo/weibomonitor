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
from cities import City
from keywords import (
    OFFICIAL_NAME_STRONG, OFFICIAL_NAME_WEAK, OFFICIAL_REASONS, OFFICIAL_PHRASES,
    STRONG_NEGATIVE, MEDIUM_NEGATIVE, MILD_NEGATIVE, POSITIVE_CONTEXT,
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

def analyze(w: Weibo, city: City) -> None:
    """就地填充 Weibo 的研判字段（city 用于区县归属）"""
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

    # 区县归属（与 main 的相关性过滤共用同一套消歧逻辑）
    w.regions = [r for r in city.match_regions(text)
                 if r != city.name] or [city.name]


# ══════════════ 可选：本地模型复核（免费） ══════════════

# 融合阈值：只在引擎较确信时才推翻词库结论。lite 打分器分布更居中，阈值略宽。
THRESHOLDS = {
    "transformer": (0.90, 0.10),   # (升级阈值, 降级阈值)
    "lite":        (0.82, 0.15),
}


def model_refine(results: list[Weibo]) -> int:
    """本地情感引擎对全部结果打分并与词库结论融合。返回修正条数。

    引擎优先级：transformer 模型（装了 torch/transformers 才启用）
              → lite 词典打分器（零依赖，始终可用）
    """
    if not results:
        return 0
    import local_model
    import lite_sentiment
    scores, engine = None, "transformer"
    if local_model.available():
        scores = local_model.score_texts([w.text for w in results])
        if scores is not None:
            log.info("情感引擎: transformer (%s)", local_model.MODEL_NAME)
    if scores is None:
        scores = lite_sentiment.score_texts([w.text for w in results])
        engine = "lite"
        log.info("情感引擎: lite 词典打分器")
    up_th, down_th = THRESHOLDS[engine]
    changed = 0
    for w, p_neg in zip(results, scores):
        w.model_score = round(p_neg, 3)
        if w.sentiment_label == "中性" and p_neg >= up_th:
            w.sentiment_label, w.sentiment_score = "关注", 0.4
            changed += 1
            log.info("模型补漏 → 关注 (p=%.2f): %s…", p_neg, w.text[:40])
        elif (w.sentiment_label in ("偏负面", "关注") or
              (w.sentiment_label == "负面" and not w.strong_neg)) and p_neg <= down_th:
            w.sentiment_label, w.sentiment_score = "中性", 0.5
            changed += 1
            log.info("模型消误报 → 中性 (p=%.2f): %s…", p_neg, w.text[:40])
    if changed:
        log.info("本地模型共修正 %d 条", changed)
    return changed


# ══════════════ 可选：LLM 复核 ══════════════

def _llm_system(city_name: str) -> str:
    return (
        f"你是地市级舆情研判助手。对每条微博判断其是否为公众对{city_name}（含区县）"
        "政务、民生、市场秩序等方面的负面反馈。官方通报、正面宣传、"
        "整治行动新闻、与本地无关的内容都不算负面。"
        '只输出JSON数组，每项形如 {"id":"...","label":"负面|偏负面|关注|中性|正面","reason":"15字内"}。'
    )


def llm_refine(candidates: list[Weibo], settings: Settings,
               city_name: str = "本市", batch: int = 20) -> None:
    """对负面候选调用 OpenAI 兼容接口复核，失败时静默保留词库结论"""
    # ✅ 在这里加上这一行：直接退出，彻底关闭大模型的情感复核！
    return
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
                "messages": [{"role": "system", "content": _llm_system(city_name)},
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
# --- analyzer.py 文件的末尾 ---
import requests
import logging

log = logging.getLogger(__name__)

def llm_summarize(top_candidates: list, settings) -> None:
    """对 Top 10 负面舆情调用 LLM 生成单句总结（专供领导阅示）"""
    # 检查是否在 GitHub Secrets 中配置了 API KEY
    if not settings.llm_api_key or not top_candidates:
        return
    
    # 默认使用 Google 的 OpenAI 兼容接口，如果 GitHub Secrets 没填 BASE 就用默认的
    base_url = (settings.llm_api_base or "https://generativelanguage.googleapis.com/v1beta/openai/").rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json"
    }
    
    log.info("开始生成 Top %d 领导专报摘要...", len(top_candidates))
    for w in top_candidates:
        prompt = (
            "请作为专业政务舆情分析员，根据我提供的素材，撰写一篇高质量的舆情信息报送文本。请严格执行以下所有指令："
            "符号与首句概括：文本最开头必须带有“△”符号，且紧跟其后的第一句话必须是一句简短的话，用于精准概括该舆情事件的核心。"
            "字数与排版格式：生成的文本总字数需严格控制在100字左右。必须采用纯粹的一段话形式输出，首尾贯通，绝对不可分段。"
            "核心内容与数据：必须客观说清楚事情的来龙去脉（包含事发地点、前因后果等核心要素），直击矛盾痛点。特别提醒：若提供的原文素材中包含任何具体数据，必须在输出文本中予以完整保留。"
            "内容绝对禁区：不需要阐述事件的影响及群众诉求；绝对不允许在文本中提出任何解决建议或应对措施。"
            "责任性质界定：确保舆情事件发生的责任主体严格限定在政府行政及公共服务工作范畴内，坚决禁止从党口相关工作、司法程序、官员贪腐、普通民事纠纷或诉讼案件等角度进行撰写。"
            "公文文风语态：保持严肃、紧凑的公文语态，行文要高度凝练，坚决禁止使用如“一是、二是，首先、其次”等罗列型连接词。"
            f"原贴内容：{w.text[:400]}"
        )
        try:
            resp = requests.post(url, headers=headers, timeout=15, json={
                "model": settings.llm_model or "gemini-1.5-flash",
                "temperature": 0.2, # 低温保证客观严肃
                "messages": [{"role": "user", "content": prompt}],
            })
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            # 强行清洗大模型可能附带的标点或换行
            w.summary = content.replace('\n', '').strip('。，！；.,!; ')
        except Exception as e:
            log.warning("LLM 摘要失败 [%s]: %s", getattr(w, 'id', '未知'), e)
            # 失败兜底：截取原文
            w.summary = w.text[:20].strip() + "..."
