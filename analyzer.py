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


# ══════════════ 政府职责相关性过滤 ══════════════

# 个人生活、消费和经验分享不直接进入领导舆情；只有存在公共事务对象、
# 具体问题事实或明确求助/投诉行为时，才交给后续情感研判和摘要。
GOVERNMENT_DUTY_TERMS = (
    "公安", "民警", "派出所", "交警", "交管", "城管", "住建", "住房建设",
    "人社", "劳动监察", "劳动仲裁", "市场监管", "市监", "卫健", "教育局",
    "生态环境", "环保", "交通局", "街道", "社区", "村委", "政府", "部门",
    "12345", "市长热线", "消防", "应急管理", "自然资源", "水务局", "供水",
    "供电", "燃气", "民政", "法院", "检察院", "纪委",
)

PUBLIC_OBJECT_TERMS = (
    "小区", "物业", "业主", "居民", "道路", "公路", "桥", "地铁", "公交",
    "车站", "学校", "医院", "工地", "项目", "施工", "商场", "商家", "门店",
    "市场", "景区", "河道", "公园", "停车", "电梯", "供暖", "停水", "停电",
    "垃圾", "排污", "农民工", "工资", "工钱",
)

PUBLIC_PROBLEM_TERMS = (
    "投诉", "举报", "反映", "求助", "报警", "仲裁", "维权", "欠薪", "拖欠工资",
    "不发工资", "乱收费", "收费不合理", "停水", "停电", "供暖不", "烂尾", "交了钱不交房", "违建",
    "强拆", "拆迁", "扰民", "污染", "扬尘", "噪音", "违法", "违规", "事故",
    "隐患", "殴打", "强制消费", "拒绝退款", "不退款", "欺诈", "翻译不当", "不规范",
    "故障", "坏了", "停运", "不维修", "没来", "服务差", "服务太差", "态度恶劣", "排队", "拥堵",
    "积水", "漏水", "缺失", "不便", "影响", "问题", "用水异常", "水费异常", "没人管",
    "不作为", "推诿", "扯皮", "未处理", "不处理",
)

PUBLIC_ACTION_TERMS = (
    "请关注", "请处理", "请求", "恳请", "督促", "希望有关部门", "向有关部门", "联系",
    "建议", "排查", "更正", "希望解决", "多次投诉", "多次反映", "多次举报", "多次讨要", "报警后", "申请仲裁",
)

PERSONAL_HEALTH_TERMS = (
    "过敏", "鼻塞", "流涕", "眼睛发红", "皮肤起疹", "胸闷气短", "呼吸不畅",
    "失眠", "头疼", "感冒", "发烧", "咳嗽",
)

GENERIC_ARTICLE_TERMS = (
    "维权攻略", "律师经验", "法律经验", "案例分享", "律师建议", "我发表了",
    "头条文章", "揭秘", "攻略", "经验帖",
)


def is_government_relevant(w: Weibo) -> tuple[bool, str]:
    """判断帖子是否包含可由政府部门或公共治理体系处理的具体事项。"""
    text = re.sub(r"\s+", "", w.text or "")
    has_duty = any(term in text for term in GOVERNMENT_DUTY_TERMS)
    has_object = any(term in text for term in PUBLIC_OBJECT_TERMS)
    has_problem = any(term in text for term in PUBLIC_PROBLEM_TERMS)
    has_action = any(term in text for term in PUBLIC_ACTION_TERMS)

    # 医生营销、商业避雷和个人健康感受本身不是公共治理舆情；出现明确
    # 无证行医、医疗事故等监管事实时再放行。
    medical_regulation = any(term in text for term in
                             ("无证行医", "医疗事故", "医疗纠纷", "医疗机构", "执业资格", "医患"))
    if (any(term in text for term in ("医生营销", "铺天盖地营销", "黑心医生")) or
            ("避雷" in text and any(term in text for term in ("医生", "医美", "整形")))):
        if not medical_regulation:
            return False, "个人商业避雷/医生营销"
    if any(term in text for term in PERSONAL_HEALTH_TERMS) and not (
            has_duty or any(term in text for term in ("疫情", "传染病", "公共卫生", "医院", "医疗"))):
        return False, "个人健康感受"

    # 只有文章标题、攻略或经验分享，没有本人遭遇、项目、金额等个案事实。
    has_case_anchor = bool(re.search(
        r"(?:本人|我在|我于|我被|我们|其于|遭遇|项目|小区|工地|欠薪|拖欠|工资|金额|元|万元|"
        r"报警|立案|仲裁|处罚|受伤|停运|停水|停电|污染)", text
    ))
    if any(term in text for term in GENERIC_ARTICLE_TERMS) and not has_case_anchor:
        return False, "泛化攻略/经验文章"

    if has_duty and has_problem:
        return True, "政府职责事项"
    if has_object and has_problem and (has_action or any(
            term in text for term in ("影响居民", "无法生活", "长期", "连续", "多人", "公共"))):
        return True, "公共服务或公共问题"
    if any(term in text for term in ("欠薪", "拖欠工资", "农民工工资", "强拆", "食品中毒", "交通违法", "交了钱不交房")):
        return True, "明确公共治理问题"
    return False, "个人生活/消费或缺少具体公共事项"


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
        image_urls = list(dict.fromkeys(getattr(w, "image_urls", []) or []))[:6]
        prompt = (
            "请作为政务舆情编辑，根据原帖正文和配图，写一条可直接报送领导的舆情摘要。"
            "通常写180至260字，采用纯粹的一段话形式输出，不换行、不加标题、不分点。"
            "开头必须带有“△”，第一句话只做对整条舆情的概括，写清核心对象、核心问题和当前状态，不要堆砌细节。"
            "概括句之后，自然交代原文明确提供的事件经过、关键事实、实际影响、处置进展或群众诉求；只写与事件判断和政府职责相关的信息。"
            "金额、人数、时间、地点、项目名称、责任主体、证据、已采取措施和明确诉求等内容，按信息价值择要保留，不要求机械全部罗列。"
            "只使用原帖和配图明确提供的事实，不新增事实、不推测动机、不扩大责任主体，不把网民反映改写成已证实结论。"
            "原文没有提供的官方回应、处置结果、核实状态或争议判断直接省略，不得自行补写无来源的情况性结尾。"
            "删除情绪宣泄、夸张修辞、反问、口号、重复表述和无信息量套话，使用第三人称、简洁克制。"
            "有配图时，仅结合图片中清晰可辨且与事件直接相关的文字、标识、场景或证据；看不清或无法确定的内容不要猜测。"
            f"原帖内容：{source_text}"
        )
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
