"""analyzer.py — 官方账号过滤 + 情感研判

研判为两级漏斗：
  1) 词库加权打分（本文件 analyze）——高召回粗筛；
  2) 可选 LLM 复核（llm_refine）——只对粗筛出的负面候选精判，
     修正"打击黑恶势力专项行动"这类关键词误报。未配置 LLM 时跳过。
"""

from __future__ import annotations

import json
import logging
import re

import requests

from config import DEFAULT_LLM_API_BASE, DEFAULT_LLM_MODEL, Settings
from models import Weibo
from cities import City
from keywords import (
    OFFICIAL_NAME_STRONG, OFFICIAL_NAME_WEAK, OFFICIAL_REASONS, OFFICIAL_PHRASES,
    ENTERTAINMENT_SUBJECT, ENTERTAINMENT_NEWS, PUBLIC_ISSUE_TERMS,
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


# ══════════════ 内容范围过滤 ══════════════

def is_entertainment_news(w: Weibo) -> tuple[bool, str]:
    """排除娱乐新闻，同时保留演出退票、剧组扰民等真实公共问题。"""
    text = w.text
    public_hits = [term for term in PUBLIC_ISSUE_TERMS if term in text]
    if public_hits:
        return False, ""

    subject_hits = [term for term in ENTERTAINMENT_SUBJECT if term in text]
    news_hits = [term for term in ENTERTAINMENT_NEWS if term in text]
    if (subject_hits and news_hits) or len(subject_hits) >= 2 or len(news_hits) >= 3:
        evidence = (subject_hits[:2] + news_hits[:3])[:4]
        return True, f"娱乐新闻{evidence}"
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

_SUMMARY_DATA_RE = re.compile(
    r"\d+(?:\.\d+)?(?:余|多)?(?:年|个月|月|日|户|人次|人|名|次|天|层|栋|部|万元|公里|小时)"
)

_SUMMARY_BOILERPLATE = (
    "信息来源为",
    "事件经过为",
    "争议或疑似原因在于",
    "造成影响方面",
    "群众反映及当前进展方面",
    "相关舆情持续一段时间",
    "部分网络用户近期围绕",
    "原文未提及",
)


def _summary_quality_issue(summary: str, source_text: str) -> str:
    if "\n" in summary or "\r" in summary:
        return "摘要出现分段"
    summary = summary.strip()
    if not summary.startswith("△"):
        return "摘要未以△开头"

    body = summary.lstrip("△").strip()
    if len(source_text) >= 120 and len(body) < 160:
        return "摘要过短，尚未说清事件经过"
    if len(body) > 300:
        return "摘要超过300字"

    first_end = re.search(r"[。！？!?]", body)
    if not first_end or first_end.end() > 60:
        return "首句没有简短概括事件核心"

    source_facts = set(_SUMMARY_DATA_RE.findall(source_text or ""))
    missing_facts = [fact for fact in source_facts if fact not in body]
    if missing_facts:
        return f"遗漏原帖数据：{'、'.join(sorted(missing_facts))}"
    if any(marker in body for marker in ("一是", "二是", "首先", "其次")):
        return "使用了禁止的罗列式连接词"
    if any(marker in body for marker in _SUMMARY_BOILERPLATE):
        return "使用了模板化套话，需改为自然叙事"
    return ""


def _clean_summary(content: str) -> str:
    return re.sub(r"\s+", " ", content or "").strip()


def llm_summarize(top_candidates: list, settings) -> None:
    """对 Top 10 负面舆情调用 LLM 生成单段总结（专供领导阅示）。"""
    # 检查是否在 GitHub Secrets 中配置了 API KEY
    if not settings.llm_api_key or not top_candidates:
        return
    
    # 默认使用 DeepSeek 的 OpenAI 兼容接口；显式配置仍优先，避免把已有部署配置静默改掉。
    base_url = (settings.llm_api_base or DEFAULT_LLM_API_BASE).rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json"
    }
    
    model = settings.llm_model or DEFAULT_LLM_MODEL
    log.info("开始生成 Top %d 领导专报摘要（模型=%s，接口=%s）...",
             len(top_candidates), model, base_url)
    for w in top_candidates:
        source_text = w.text.strip()[:8000]
        prompt = (
            "请作为专业政务舆情分析员，根据我提供的素材，撰写一篇高质量的舆情信息报送文本。请严格执行以下所有指令："
            "符号与首句概括：文本最开头必须带有“△”符号，且紧跟其后的第一句话必须是一句简短的话，直接概括“地点、事件、涉及主体和持续时间”。"
            "字数与排版格式：在素材信息充足时，生成文本总字数控制在180至260字；素材较短时以事实完整为先，严禁为凑字数编造内容。按“信息来源—事件经过—争议或疑似原因—造成影响—群众反映及当前进展”的顺序组织内容"
            "只使用原文明确提供的信息，不新增事实、不推测动机、不扩大责任主体、不替任何一方下结论。对知情人爆料、未经官方确认的指控，必须保留来源归属，并使用“据报道、据知情人士称、疑似、被指、尚待核实”等谨慎表述，不能将其写成已证实事实。"
            "核心内容与数据：保留关键地点、时间、数字、道路名称和相关主体；删除重复内容、情绪化表达、夸张修辞、反问、类比、号召性语言和未经证实的定性词。"
            "内容绝对禁区：不需要阐述事件的影响及群众诉求；绝对不允许在文本中提出任何解决建议或应对措施。使用第三人称、简洁、克制的新闻写法，只输出一个自然段，不加标题、不分点、不作评论。"
            "结尾说明群众是否曾反映、问题是否已解决；如原文没有权威处置结果，应写明“截至材料所述时间，尚无明确处置结果”。"
            "公文文风语态：保持严肃、紧凑的公文语态，行文要高度凝练，坚决禁止使用如“一是、二是，首先、其次”等罗列型连接词。"
            f"原帖内容：{source_text}"
        )
        previous_summary = ""
        quality_issue = ""
        best_summary = ""
        for attempt in range(2):
            messages = [{"role": "user", "content": prompt}]
            if quality_issue:
                messages.extend([
                    {"role": "assistant", "content": previous_summary},
                    {"role": "user", "content": (
                        f"上一版不合格：{quality_issue}。请保留全部既定格式和内容禁区，"
                        "重新阅读原帖，把事件经过、关键细节和数据写完整后重写。"
                    )},
                ])
            try:
                resp = requests.post(url, headers=headers, timeout=20, json={
                    "model": model,
                    "temperature": 0.1,
                    "messages": messages,
                })
                resp.raise_for_status()
                content = _clean_summary(
                    resp.json()["choices"][0]["message"]["content"]
                )
                if len(content) > len(best_summary):
                    best_summary = content
                quality_issue = _summary_quality_issue(content, source_text)
                if quality_issue:
                    previous_summary = content
                    log.warning("LLM 摘要需重写 [%s]: %s", getattr(w, 'id', '未知'), quality_issue)
                    continue
                w.summary = content
                break
            except Exception as e:
                log.warning("LLM 摘要失败 [%s]: %s", getattr(w, 'id', '未知'), e)
                if attempt == 0:
                    continue
        else:
            # 两次均不合格时保留信息量最大的一版；接口完全失败则保留原文。
            w.summary = best_summary or source_text
