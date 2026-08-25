"""analyzer.py — 官方账号过滤 + 情感研判

研判为两级漏斗：
  1) 词库加权打分（本文件 analyze）——高召回粗筛；
  2) 可选 LLM 复核（llm_refine）——只对粗筛出的负面候选精判，
     修正"打击黑恶势力专项行动"这类关键词误报。未配置 LLM 时跳过。
"""

from __future__ import annotations

import json
import logging
import os
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

# DeepSeek 生成摘要可能需要几十秒；可按部署网络情况通过环境变量覆盖。
LLM_SUMMARY_TIMEOUT = int(os.environ.get("LLM_SUMMARY_TIMEOUT", "60"))

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

_SUMMARY_DISCLAIMER_PATTERNS = (
    re.compile(
        r"(?:目前|截至(?:发帖时|当前|目前))[，,]?"
        r"(?:相关|有关)(?:方面|部门|单位)?(?:尚未|未)"
        r"(?:作出|公开)?(?:回应|答复)"
    ),
    re.compile(
        r"(?:截至(?:当前|目前|材料所述时间)[，,]?)?"
        r"(?:前述|上述|有关|相关)?(?:网络帖文|网帖|帖文)?(?:情况|内容|说法)"
        r"(?:尚未|未)(?:获得|获)?(?:有关)?官方(?:证实|确认)"
    ),
    re.compile(
        r"(?:截至(?:当前|目前|材料所述时间)[，,]?)?"
        r"(?:前述|上述|有关|相关)?(?:情况|内容|说法)?(?:仍)?"
        r"(?:尚待|有待|待)(?:有关部门|官方)?(?:进一步)?(?:核实|证实)"
    ),
    re.compile(
        r"(?:上述|前述)(?:内容|情况)(?:均)?为"
        r"(?:网帖|帖文|网民)(?:自行|个人)?(?:表述|说法)"
    ),
)


def _clean_summary(content: str) -> str:
    summary = re.sub(r"\s+", " ", content or "").strip()
    for pattern in _SUMMARY_DISCLAIMER_PATTERNS:
        summary = pattern.sub("", summary)
    summary = re.sub(r"(?:截至(?:当前|目前)|目前)[，,]?(?=[。！？!?]|$)", "", summary)
    summary = re.sub(r"[，,；;]+(?=[。！？!?])", "", summary)
    summary = re.sub(r"([。！？!?])\1+", r"\1", summary)
    summary = summary.strip(" ，,；;")
    if summary and summary[-1] not in "。！？!?":
        summary += "。"
    return summary


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
        image_urls = list(dict.fromkeys(getattr(w, "image_urls", []) or []))[:6]
        prompt = f"""你是资深政务舆情信息编辑。请把下面一条网络舆情编辑成可直接报送的高质量摘要。任务不是机械复述微博，也不是评判真假或补齐报告要素，而是提炼最值得上报的问题，并用具体事实把事情说清楚。

编辑方法：
1. 先判断素材的核心上报价值。政策类突出执行落差；公共服务类突出故障、持续时间和影响范围；行政履职类突出群众反映经过与处置问题；消费投诉类突出交易事实、金额和争议点；安全事件类突出行为、后果和已有处置；网络指控类突出指控主体、具体行为和原文证据。不要在成文中写出这些分类名称。
2. 文本必须以“△”开头。第一句用“地区或核心对象＋具体问题＋关键影响或状态”概括整条舆情，通常控制在20至45字。首句必须有实质判断，不得只写“存在问题”“引发关注”“引发质疑”“引发争议”“相关问题待解决”等空泛结论。
3. 从第二句开始自然交代信息来源和事件经过。优先保留原文中的具体地点、单位、人物、时间、持续时长、金额、数量、专有名词、图片文字说明、现场细节和其他能够支撑首句的证据；不要用一串被@的账号代替事件事实。
4. 原文明确写到的实际影响、群众诉求、整改建议、回应或处置进展，应根据重要性保留。原文提出的建议可以转述，但不得自行新增建议、原因、责任认定或影响。
5. 对单方投诉或网络爆料，只在首次出现时用“网民反映”“网帖称”“被指”等方式标明来源。不得在结尾追加真实性核验、等待官方确认、材料未提及或相关方面未回应等免责声明；只有原文明示曾联系某单位但未获回应，且这本身属于事件经过时，才可客观写入。
6. 原文没有的信息直接省略，不为凑齐原因、影响、诉求、回应等结构而补写。多项原因或问题确有事实支撑时，可以自然使用“一是、二是”等简明归纳，但不得机械罗列。

写作要求：
- 只依据原帖正文和随附图片，不新增事实，不推测动机，不扩大责任主体，不替任何一方下结论。有图片时应认真读取其中可辨识的文字、标识、场景和证据，并把能够支撑核心问题的具体信息写入摘要；看不清或无法确定的内容不得猜测。
- 删除情绪宣泄、夸张修辞、反问、口号、重复表述和无信息量套话，但不得删除能够说明问题的具体事实。
- 通常写180至260字；信息丰富时可适当延长。
- 使用第三人称、简洁克制的新闻写法，写成一个自然段，不换行、不加标题、不分点，不输出解释。

原帖内容：{source_text}"""
        vision_model = getattr(settings, "llm_vision_model", "").strip()
        use_vision = bool(image_urls and vision_model)
        request_model = vision_model if use_vision else model
        message_content: str | list[dict] = prompt
        if use_vision:
            message_content = [{"type": "text", "text": prompt}]
            message_content.extend(
                {"type": "image_url", "image_url": {"url": image_url}}
                for image_url in image_urls
            )
        try:
            # 正常只请求一次；视觉接口拒绝图片时再降级为文本模型。
            payload = {
                "model": request_model,
                "temperature": 0.1,
                "messages": [{"role": "user", "content": message_content}],
            }
            try:
                resp = requests.post(
                    url, headers=headers, timeout=LLM_SUMMARY_TIMEOUT, json=payload
                )
            except requests.RequestException as exc:
                if not use_vision:
                    raise
                log.warning(
                    "视觉摘要请求异常，降级为文本模型 [%s]: %s",
                    getattr(w, "id", "未知"),
                    exc,
                )
                payload["model"] = model
                payload["messages"] = [{"role": "user", "content": prompt}]
                resp = requests.post(
                    url, headers=headers, timeout=LLM_SUMMARY_TIMEOUT, json=payload
                )
            if use_vision and not resp.ok:
                log.warning(
                    "视觉摘要失败，降级为文本模型 [%s]: HTTP %s",
                    getattr(w, "id", "未知"),
                    resp.status_code,
                )
                payload["model"] = model
                payload["messages"] = [{"role": "user", "content": prompt}]
                resp = requests.post(
                    url, headers=headers, timeout=LLM_SUMMARY_TIMEOUT, json=payload
                )
            resp.raise_for_status()
            content = _clean_summary(
                resp.json()["choices"][0]["message"]["content"]
            )
            w.summary = content or source_text
        except Exception as e:
            log.warning("LLM 摘要失败 [%s]: %s", getattr(w, 'id', '未知'), e)
            # 接口失败时保留原帖，避免摘要失败导致整条候选消失。
            w.summary = source_text
