from __future__ import annotations

"""
parser.py — 微博数据解析 + 时间处理
"""

import re
from datetime import datetime, timedelta


def parse_mblog(mb, keyword, today):
    # type: (dict, str, str) -> dict
    """解析移动端 mblog → 统一字典，无效返回 None"""
    if not mb:
        return None

    text = mb.get("text", "")
    if mb.get("isLongText"):
        lt = mb.get("longText", {})
        if isinstance(lt, dict) and lt.get("longTextContent"):
            text = lt["longTextContent"]

    text = _clean(text)
    if not text or len(text) < 6:
        return None

    created = mb.get("created_at", "")
    pt = parse_time(created, today)
    if pt and not _within_2_days(pt):
        return None

    user = mb.get("user") or {}
    wid = str(mb.get("id", ""))

    return {
        "id": wid,
        "user": user.get("screen_name", "未知"),
        "verified": user.get("verified", False),
        "verified_type": user.get("verified_type", -1),
        "verified_reason": user.get("verified_reason", ""),
        "followers": user.get("followers_count", 0),
        "text": text,
        "time": pt or created,
        "reposts": mb.get("reposts_count", 0),
        "comments": mb.get("comments_count", 0),
        "likes": mb.get("attitudes_count", 0),
        "keyword": keyword,
        "url": "https://m.weibo.cn/detail/{}".format(wid),
        "source": "微博",
    }


def parse_status(st, keyword, today):
    # type: (dict, str, str) -> dict
    """解析PC端 status → 统一字典，无效返回 None"""
    if not st:
        return None

    text = st.get("text_raw", "") or re.sub(r'<[^>]+>', '', st.get("text", ""))
    text = re.sub(r'\s+', ' ', text).strip()
    if not text or len(text) < 6:
        return None

    created = st.get("created_at", "")
    pt = parse_time(created, today)
    if pt and not _within_2_days(pt):
        return None

    user = st.get("user") or {}
    wid = str(st.get("id", st.get("mid", "")))

    return {
        "id": wid,
        "user": user.get("screen_name", "未知"),
        "verified": user.get("verified", False),
        "verified_type": user.get("verified_type", -1),
        "verified_reason": user.get("verified_reason", ""),
        "followers": user.get("followers_count", 0),
        "text": text,
        "time": pt or created,
        "reposts": st.get("reposts_count", 0),
        "comments": st.get("comments_count", 0),
        "likes": st.get("attitudes_count", 0),
        "keyword": keyword,
        "url": "https://weibo.com/detail/{}".format(wid),
        "source": "微博",
    }


def parse_time(s, today):
    # type: (str, str) -> str
    """各种微博时间格式 → 'YYYY-MM-DD HH:MM'"""
    if not s:
        return ""
    now = datetime.now()

    if "刚刚" in s:
        return now.strftime("%Y-%m-%d %H:%M")

    for pat, unit in [
        (r"(\d+)\s*秒前", "seconds"),
        (r"(\d+)\s*分钟前", "minutes"),
        (r"(\d+)\s*小时前", "hours"),
    ]:
        m = re.search(pat, s)
        if m:
            delta = timedelta(**{unit: int(m.group(1))})
            return (now - delta).strftime("%Y-%m-%d %H:%M")

    m = re.search(r"今天\s*(\d{1,2}):(\d{2})", s)
    if m:
        return "{} {}:{}".format(today, m.group(1).zfill(2), m.group(2))

    m = re.search(r"昨天\s*(\d{1,2}):(\d{2})", s)
    if m:
        yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
        return "{} {}:{}".format(yesterday, m.group(1).zfill(2), m.group(2))

    m = re.search(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", s)
    if m:
        return "{}-{:02d}-{:02d} {}:{}".format(
            now.year, int(m.group(1)), int(m.group(2)),
            m.group(3).zfill(2), m.group(4)
        )

    try:
        return datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y").strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass

    m = re.search(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else s


def _clean(text):
    # type: (str) -> str
    text = re.sub(r'<[^>]+>', '', text).strip()
    return re.sub(r'\s+', ' ', text)


def _within_2_days(t):
    # type: (str) -> bool
    try:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", t)
        if m:
            d = datetime.strptime(m.group(1), "%Y-%m-%d")
            cutoff = (datetime.now() - timedelta(days=2)).replace(
                hour=0, minute=0, second=0
            )
            return d >= cutoff
    except Exception:
        pass
    return True