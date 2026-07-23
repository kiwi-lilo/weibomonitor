from __future__ import annotations
from config import TARGET_MEDIA, NEWS_CATEGORIES

def get_target_media_name(username):
    # type: (str) -> str | None
    """
    判断是否为目标央媒，如果是，返回该媒体的标准名称（如输入"中新网"返回"中国新闻网"）
    如果不是，返回 None
    """
    for std_name, aliases in TARGET_MEDIA.items():
        for alias in aliases:
            if alias in username:
                return std_name
    return None

def analyze_news(text):
    # type: (str) -> list
    """给新闻打分类标签"""
    tags = set()
    for cat, kws in NEWS_CATEGORIES.items():
        for kw in kws:
            if kw in text:
                tags.add(cat)
                break # 匹配到一个词就打上该类别的标签
    if not tags:
        tags.add("📰 综合资讯")
    return list(tags)
