from __future__ import annotations
import re
from datetime import datetime, timedelta, timezone

def get_beijing_today():
    # 获取北京时间（UTC+8）的今天日期
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d")

def parse_mblog(mb, keyword, today):
    # (解析代码同原版，提取text, user, id, url等)
    # ... 保留你原有的 parse_mblog 解析基础字段代码 ...
    
    if not mb: return None
    text = mb.get("text", "")
    if mb.get("isLongText"):
        lt = mb.get("longText", {})
        if isinstance(lt, dict) and lt.get("longTextContent"):
            text = lt["longTextContent"]
    
    text = _clean(text)
    if not text: return None

    created = mb.get("created_at", "")
    pt = parse_time(created, today)
    
    # 严格判断是否为今日发布
    if not pt.startswith(today):
        return None

    user = mb.get("user") or {}
    wid = str(mb.get("id", ""))

    return {
        "id": wid,
        "user": user.get("screen_name", "未知"),
        "text": text,
        "time": pt or created,
        "reposts": mb.get("reposts_count", 0),
        "comments": mb.get("comments_count", 0),
        "likes": mb.get("attitudes_count", 0),
        "keyword": keyword,
        "url": f"https://m.weibo.cn/detail/{wid}",
    }

# parse_status 和 parse_time 函数保留原有逻辑，只要最后返回的时间字符串开头符合 today 即可。
# ... (保留 parse_status 和 parse_time 的原有代码)
def _clean(text):
    text = re.sub(r'<[^>]+>', '', text).strip()
    return re.sub(r'\s+', ' ', text)

def parse_time(s, today):
    # 保留原有的 parse_time 实现，它能处理 "刚刚", "x分钟前", "今天 12:00" 等
    now = datetime.now(timezone(timedelta(hours=8)))
    if not s: return ""
    if "刚刚" in s: return now.strftime("%Y-%m-%d %H:%M")
    # ... 其他时间解析保留 ...
    m = re.search(r"今天\s*(\d{1,2}):(\d{2})", s)
    if m: return f"{today} {m.group(1).zfill(2)}:{m.group(2)}"
    
    try:
        return datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y").strftime("%Y-%m-%d %H:%M")
    except:
        pass
    return s
