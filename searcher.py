from __future__ import annotations

"""
searcher.py — 微博搜索（3种接口）
"""

import json
import time

try:
    from urllib.parse import quote
except ImportError:
    from urllib import quote

from wb_parser import parse_mblog, parse_status


def search_mobile(session, keyword, page, today):
    # type: (...) -> list
    """移动端接口"""
    weibos = []
    cid = "100103type=61&q={}&t=0".format(keyword)
    params = {"containerid": cid, "page_type": "searchall", "page": page}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5) "
            "AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
        ),
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://m.weibo.cn/search?containerid=" + quote(cid),
    }
    try:
        r = session.get(
            "https://m.weibo.cn/api/container/getIndex",
            params=params, headers=headers, timeout=15,
        )
        if r.status_code != 200:
            return weibos
        raw = r.text.strip()
        if not raw.startswith("{"):
            return weibos
        data = r.json()
        if data.get("ok") != 1:
            return weibos
        for card in data.get("data", {}).get("cards", []):
            for mb in _extract_mblogs(card):
                w = parse_mblog(mb, keyword, today)
                if w:
                    weibos.append(w)
    except (json.JSONDecodeError, Exception):
        pass
    return weibos


def search_pc(session, keyword, page, today, two_days_ago):
    # type: (...) -> list
    """PC端 Ajax 接口"""
    weibos = []
    params = {
        "q": keyword, "typeall": 1, "suball": 1,
        "timescope": "custom:{}-0:{}-23".format(two_days_ago, today),
        "page": page,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://weibo.com/search?q={}".format(quote(keyword)),
    }
    try:
        r = session.get(
            "https://weibo.com/ajax/search/wb",
            params=params, headers=headers, timeout=15,
        )
        if r.status_code != 200:
            return weibos
        raw = r.text.strip()
        if not raw.startswith("{"):
            return weibos
        data = r.json()
        statuses = []
        if isinstance(data.get("data"), dict):
            statuses = data["data"].get("statuses", [])
        for st in statuses:
            w = parse_status(st, keyword, today)
            if w:
                weibos.append(w)
    except (json.JSONDecodeError, Exception):
        pass
    return weibos


def search_general(session, keyword, page, today):
    # type: (...) -> list
    """通用兜底"""
    weibos = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/125.0.0.0 Mobile",
        "Accept": "application/json",
        "Referer": "https://m.weibo.cn/",
    }
    for cid in [
        "100103type=61&q={}&t=0".format(keyword),
        "100103type=1&q={}&t=0".format(keyword),
    ]:
        try:
            r = session.get(
                "https://m.weibo.cn/api/container/getIndex",
                params={"containerid": cid, "page": page},
                headers=headers, timeout=12,
            )
            raw = r.text.strip()
            if raw.startswith("{"):
                data = r.json()
                if data.get("ok") == 1:
                    for card in data.get("data", {}).get("cards", []):
                        if card.get("card_type") == 9 and card.get("mblog"):
                            w = parse_mblog(card["mblog"], keyword, today)
                            if w:
                                weibos.append(w)
                    if weibos:
                        break
        except Exception:
            pass
        time.sleep(0.5)
    return weibos


def _extract_mblogs(card):
    # type: (dict) -> list
    """从卡片提取 mblog 列表"""
    mblogs = []
    if card.get("card_type") == 9:
        if card.get("mblog"):
            mblogs.append(card["mblog"])
    elif card.get("card_type") == 11:
        for sub in card.get("card_group", []):
            if sub.get("card_type") == 9 and sub.get("mblog"):
                mblogs.append(sub["mblog"])
    return mblogs