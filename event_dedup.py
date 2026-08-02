"""个人舆情事件级去重，仅用于推荐摘要，不影响原始数据存档。"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from models import Weibo

_TOPIC_TERMS = (
    "物业", "电梯", "停水", "停电", "供暖", "暖气", "燃气", "噪音", "施工",
    "烂尾", "交房", "房产证", "退款", "押金", "欠薪", "工资", "社保", "公交",
    "道路", "停车", "收费", "学校", "食堂", "医院", "医疗", "教育", "垃圾",
    "污染", "拆迁", "征地", "办证", "政务", "快递", "景区", "市场", "商家",
    "自来水", "消防", "路灯", "小区", "开发商", "业主", "工地", "交通",
)

_NOISE_PHRASES = (
    "转发微博", "微博正文", "网页链接", "展开全文", "求扩散", "请转发",
    "帮忙转发", "新浪微博", "来自微博", "视频微博",
)

_DURATION_RE = re.compile(
    r"(?:\d+|一|两|三|四|五|六|七|八|九|十|半)(?:天|日|周|星期|个?月|年|小时)"
)


def _normalize(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text or "")
    text = re.sub(r"@[\w\-\u4e00-\u9fff]+", "", text)
    text = text.replace("#", "")
    for phrase in _NOISE_PHRASES:
        text = text.replace(phrase, "")
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text).lower()


def _ngrams(text: str, size: int) -> set[str]:
    if len(text) < size:
        return {text} if text else set()
    return {text[index:index + size] for index in range(len(text) - size + 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _topics(weibo: Weibo) -> set[str]:
    text = weibo.text
    topics = {term for term in _TOPIC_TERMS if term in text}
    topics.update(weibo.strong_neg)
    topics.update(weibo.medium_neg)
    topics.update(weibo.mild_neg)
    return topics


def _anchors(weibo: Weibo) -> set[str]:
    anchors = set(_DURATION_RE.findall(weibo.text))
    anchors.update(re.findall(r"\d+(?:\.\d+)?(?:元|万|万元|户|人|次|公里|米)", weibo.text))
    return anchors


def same_event(left: Weibo, right: Weibo) -> bool:
    """保守判断两条不同账号微博是否描述同一具体事件。"""
    if left.id == right.id:
        return True

    left_text, right_text = _normalize(left.text), _normalize(right.text)
    if min(len(left_text), len(right_text)) < 12:
        return False
    if left_text == right_text:
        return True

    shorter, longer = sorted((left_text, right_text), key=len)
    if len(shorter) >= 20 and shorter in longer:
        return True

    sequence_ratio = SequenceMatcher(None, left_text, right_text, autojunk=False).ratio()
    trigram_ratio = _jaccard(_ngrams(left_text, 3), _ngrams(right_text, 3))
    if sequence_ratio >= 0.76 or trigram_ratio >= 0.36:
        return True

    common_regions = set(left.regions) & set(right.regions)
    common_topics = _topics(left) & _topics(right)
    if not common_regions or not common_topics:
        return False

    shared_bigrams = len(_ngrams(left_text, 2) & _ngrams(right_text, 2))
    common_anchors = _anchors(left) & _anchors(right)
    return (
        (sequence_ratio >= 0.52 and trigram_ratio >= 0.16 and shared_bigrams >= 6)
        or (len(common_topics) >= 2 and shared_bigrams >= 7)
        or (bool(common_anchors) and len(common_topics) >= 2 and shared_bigrams >= 5)
    )


def deduplicate_event_candidates(
    candidates: list[tuple[str, Weibo]],
) -> list[tuple[str, Weibo]]:
    """保留输入顺序中每个事件的首条；调用前应先按严重度、热度排序。"""
    selected: list[tuple[str, Weibo]] = []
    for city, candidate in candidates:
        if any(same_event(candidate, kept) for _, kept in selected):
            continue
        selected.append((city, candidate))
    return selected
