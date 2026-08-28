"""wb_parser.py — 微博数据解析 + 时间处理（统一北京时间）"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from config import TZ, DAYS_BACK
from models import Weibo

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def now_cn() -> datetime:
    return datetime.now(TZ)


def clean_text(text: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub("", text)).strip()


def parse_time(s: str, now: datetime | None = None) -> str:
    """各种微博时间格式 → 'YYYY-MM-DD HH:MM'（北京时间）。解析失败返回原串。"""
    if not s:
        return ""
    now = now or now_cn()

    if "刚刚" in s:
        return now.strftime("%Y-%m-%d %H:%M")

    for pat, unit in [(r"(\d+)\s*秒前", "seconds"),
                      (r"(\d+)\s*分钟前", "minutes"),
                      (r"(\d+)\s*小时前", "hours")]:
        m = re.search(pat, s)
        if m:
            return (now - timedelta(**{unit: int(m.group(1))})).strftime("%Y-%m-%d %H:%M")

    m = re.search(r"今天\s*(\d{1,2}):(\d{2})", s)
    if m:
        return "{} {:0>2}:{}".format(now.strftime("%Y-%m-%d"), m.group(1), m.group(2))

    m = re.search(r"昨天\s*(\d{1,2}):(\d{2})", s)
    if m:
        d = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        return "{} {:0>2}:{}".format(d, m.group(1), m.group(2))

    # "MM-DD HH:MM"：跨年修正——若拼出的日期在未来（>1天），说明是去年的帖子
    m = re.search(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", s)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = now.year
        try:
            dt = datetime(year, month, day, tzinfo=TZ)
            if dt - now > timedelta(days=1):
                year -= 1
        except ValueError:
            pass
        return "{}-{:02d}-{:02d} {:0>2}:{}".format(year, month, day, m.group(3), m.group(4))

    # 标准格式 "Sat Jul 25 20:31:02 +0800 2026"
    try:
        dt = datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")
        return dt.astimezone(TZ).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        pass

    m = re.search(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else s


def within_days(t: str, days: int = DAYS_BACK, now: datetime | None = None) -> bool:
    """时间串是否落在最近 days 天内；无法解析时保守保留"""
    now = now or now_cn()
    m = re.search(r"(\d{4}-\d{2}-\d{2})", t)
    if not m:
        return True
    try:
        d = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=TZ)
    except ValueError:
        return True
    cutoff = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return d >= cutoff


def _to_int(v) -> int:
    """粉丝数等字段兼容 '2.8万' / '1.2亿' / 数字字符串"""
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        try:
            if s.endswith("万"):
                return int(float(s[:-1]) * 10_000)
            if s.endswith("亿"):
                return int(float(s[:-1]) * 100_000_000)
            return int(float(s))
        except ValueError:
            return 0
    return 0


def _normalize_image_url(value: object) -> str:
    url = str(value or "").strip()
    if url.startswith("//"):
        return "https:" + url
    return url if url.startswith(("https://", "http://")) else ""


def _image_urls(raw: dict) -> list[str]:
    """兼容移动端 pics 与 PC 端 pic_infos，优先保留大图地址。"""
    urls: list[str] = []
    for pic in raw.get("pics") or []:
        if not isinstance(pic, dict):
            continue
        large = pic.get("large") if isinstance(pic.get("large"), dict) else {}
        url = _normalize_image_url(large.get("url") or pic.get("url"))
        if url and url not in urls:
            urls.append(url)

    pic_infos = raw.get("pic_infos") or {}
    if isinstance(pic_infos, dict):
        pic_ids = raw.get("pic_ids") or list(pic_infos)
        for pic_id in pic_ids:
            info = pic_infos.get(str(pic_id)) or {}
            if not isinstance(info, dict):
                continue
            largest = info.get("largest") if isinstance(info.get("largest"), dict) else {}
            large = info.get("large") if isinstance(info.get("large"), dict) else {}
            url = _normalize_image_url(
                largest.get("url") or large.get("url") or info.get("url")
            )
            if url and url not in urls:
                urls.append(url)
    retweeted = raw.get("retweeted_status")
    if isinstance(retweeted, dict):
        for url in _image_urls(retweeted):
            if url not in urls:
                urls.append(url)
    return urls


def _build(raw: dict, text: str, keyword: str, url_tpl: str) -> Weibo | None:
    text = clean_text(text)
    if len(text) < 6:
        return None
    pt = parse_time(raw.get("created_at", ""))
    if pt and not within_days(pt):
        return None
    user = raw.get("user") or {}
    wid = str(raw.get("id") or raw.get("mid") or "")
    if not wid:
        return None
    return Weibo(
        id=wid,
        user=user.get("screen_name", "未知"),
        verified=bool(user.get("verified", False)),
        verified_type=user.get("verified_type", -1),
        verified_reason=user.get("verified_reason", "") or "",
        followers=_to_int(user.get("followers_count", 0)),
        text=text,
        time=pt or raw.get("created_at", ""),
        reposts=_to_int(raw.get("reposts_count", 0)),
        comments=_to_int(raw.get("comments_count", 0)),
        likes=_to_int(raw.get("attitudes_count", 0)),
        keyword=keyword,
        url=url_tpl.format(wid),
        image_urls=_image_urls(raw),
    )


def parse_mblog(mb: dict, keyword: str) -> Weibo | None:
    """移动端 mblog"""
    if not mb:
        return None
    text = mb.get("text", "")
    if mb.get("isLongText"):
        lt = mb.get("longText") or {}
        if isinstance(lt, dict) and lt.get("longTextContent"):
            text = lt["longTextContent"]
    weibo = _build(mb, text, keyword, "https://m.weibo.cn/detail/{}")
    if weibo:
        long_text = mb.get("longText") or {}
        has_full_text = isinstance(long_text, dict) and bool(
            long_text.get("longTextContent")
        )
        weibo.needs_full_text = bool(mb.get("isLongText")) and not has_full_text
        weibo.full_text_loaded = has_full_text
    return weibo


def parse_status(st: dict, keyword: str) -> Weibo | None:
    """PC 端 status"""
    if not st:
        return None
    text = st.get("text_raw") or st.get("text", "")
    return _build(st, text, keyword, "https://weibo.com/detail/{}")
