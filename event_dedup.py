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
    # Celebrity and breaking-news posts often omit the location and repeat
    # different paraphrases of the same rumor.  Keep these terms in the event
    # signature so those reposts can be collapsed just like local complaints.
    "爆料", "传闻", "谣言", "不实", "狗仔", "私生子", "产子", "天王", "艺人",
    "歌手", "股东", "热搜", "对号入座", "辟谣", "澄清",
    # 人身伤害类舆情常被不同账号大幅改写，原有民生主题词无法形成共同签名。
    "男孩", "女孩", "少年", "未成年人", "民警", "公职人员", "工作人员",
    "殴打", "掌掴", "踢打", "踢踹", "报警", "颅脑损伤", "耳鸣", "拘留",
    "道歉", "赔偿", "有偿服务", "色情服务", "涉黄",
)

_NOISE_PHRASES = (
    "转发微博", "微博正文", "网页链接", "展开全文", "求扩散", "请转发",
    "帮忙转发", "新浪微博", "来自微博", "视频微博",
)

_DURATION_RE = re.compile(
    r"(?:\d+|一|两|三|四|五|六|七|八|九|十|半)(?:天|日|周|星期|个?月|年|小时)"
)
_AGE_RE = re.compile(r"\d{1,3}岁")
_DATE_RE = re.compile(r"\d{1,2}月\d{1,2}日")
_CLOCK_RE = re.compile(r"\d{1,2}(?:时|点)(?:\d{1,2}分)?")
_MASKED_NAME_RE = re.compile(r"[A-Za-z\u4e00-\u9fff]某")
_HASHTAG_RE = re.compile(r"#([^#\r\n]{4,60})#")

_DISTINCTIVE_EVENT_TERMS = frozenset({
    "爆料", "传闻", "谣言", "不实", "狗仔", "私生子", "产子", "股东",
    "辟谣", "澄清", "天王", "艺人", "歌手", "热搜", "对号入座",
})

_GENERIC_SIGNATURE_TERMS = (
    "网络", "爆料", "传闻", "谣言", "不实", "相关", "网友", "引发", "持续",
    "热搜", "事件", "平台", "目前", "全程", "没有", "未提", "某", "据称",
    "指向", "当事", "事人", "方面", "暂无", "回应",
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
    anchors.update(_AGE_RE.findall(weibo.text))
    anchors.update(_DATE_RE.findall(weibo.text))
    anchors.update(_CLOCK_RE.findall(weibo.text))
    anchors.update(_MASKED_NAME_RE.findall(weibo.text))
    return anchors


def _hashtags(weibo: Weibo) -> set[str]:
    """提取具体事件话题；过短话题通常只是城市或投诉类通用标签。"""
    return {
        _normalize(value)
        for value in _HASHTAG_RE.findall(weibo.text)
        if len(_normalize(value)) >= 8
    }


def _distinctive_trigrams(text: str) -> set[str]:
    return {
        gram for gram in _ngrams(text, 3)
        if not any(term in gram for term in _GENERIC_SIGNATURE_TERMS)
    }


def same_event(left: Weibo, right: Weibo) -> bool:
    """保守判断两条不同账号微博是否描述同一具体事件。"""
    if left.id == right.id:
        return True

    left_text, right_text = _normalize(left.text), _normalize(right.text)
    if min(len(left_text), len(right_text)) < 12:
        return False
    if left_text == right_text:
        return True

    common_regions = set(left.regions) & set(right.regions)
    if common_regions and _hashtags(left) & _hashtags(right):
        return True

    shorter, longer = sorted((left_text, right_text), key=len)
    if len(shorter) >= 20 and shorter in longer:
        return True

    sequence_ratio = SequenceMatcher(None, left_text, right_text, autojunk=False).ratio()
    trigram_ratio = _jaccard(_ngrams(left_text, 3), _ngrams(right_text, 3))
    common_topics = _topics(left) & _topics(right)
    if sequence_ratio >= 0.76:
        return True
    # A high n-gram score is enough for ordinary service complaints.  For
    # rumor/news text, generic phrases such as "网络爆料" can inflate that
    # score, so require the entity-aware branch below instead.
    if trigram_ratio >= 0.36 and not common_topics & _DISTINCTIVE_EVENT_TERMS:
        return True
    if not common_regions or not common_topics:
        return False

    shared_bigrams = len(_ngrams(left_text, 2) & _ngrams(right_text, 2))
    shared_trigrams = len(
        _distinctive_trigrams(left_text) & _distinctive_trigrams(right_text)
    )
    common_anchors = _anchors(left) & _anchors(right)
    # Rumor/news rewrites frequently have low sequence similarity, but retain
    # several distinctive event terms.  This catches reposts such as multiple
    # accounts paraphrasing one celebrity rumor without weakening the stricter
    # rules used for ordinary local-service topics.
    if common_topics & _DISTINCTIVE_EVENT_TERMS and shared_trigrams >= 1:
        return True
    common_non_rumor_topics = {
        topic for topic in common_topics
        if not any(term in topic for term in _DISTINCTIVE_EVENT_TERMS)
    }
    rumor_topics = common_topics & _DISTINCTIVE_EVENT_TERMS
    return (
        (
            sequence_ratio >= 0.52
            and trigram_ratio >= 0.16
            and shared_bigrams >= 6
            and (not rumor_topics or shared_trigrams >= 1)
        )
        or (
            len(common_topics) >= 2
            and bool(common_non_rumor_topics)
            and shared_bigrams >= 7
        )
        or (
            bool(common_anchors)
            and len(common_topics) >= 3
            and shared_bigrams >= 3
        )
        or (bool(common_anchors) and len(common_topics) >= 2 and shared_bigrams >= 5)
    )


def deduplicate_event_candidates(
    candidates: list[tuple[str, Weibo]],
) -> list[tuple[str, Weibo]]:
    """按相似关系的连通分组去重，并保留每组输入顺序最靠前的一条。"""
    if len(candidates) < 2:
        return list(candidates)

    parents = list(range(len(candidates)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left_index: int, right_index: int) -> None:
        left_root, right_root = find(left_index), find(right_index)
        if left_root != right_root:
            parents[right_root] = left_root

    for right_index in range(1, len(candidates)):
        for left_index in range(right_index):
            if same_event(candidates[left_index][1], candidates[right_index][1]):
                union(left_index, right_index)

    selected: list[tuple[str, Weibo]] = []
    selected_roots: set[int] = set()
    for index, candidate in enumerate(candidates):
        root = find(index)
        if root not in selected_roots:
            selected.append(candidate)
            selected_roots.add(root)
    return selected
