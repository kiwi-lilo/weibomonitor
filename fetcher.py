"""fetcher.py — 微博采集

核心改进（相对 v4）：
1. 每次请求显式区分 5 种结果状态，Cookie 失效 / 被限流不再伪装成"0 条"。
2. requests.Session 挂自动重试（连接错误 / 5xx 指数退避）。
3. 长微博搜索卡片自动补取详情全文，避免摘要只看到“全文”前的截断内容。
4. Health 计数器供 main 决策：掉登录立即中止并发送邮件、Bark 告警。
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from dataclasses import dataclass, field
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from models import Weibo
from wb_parser import clean_text, parse_mblog, parse_status

log = logging.getLogger(__name__)


class Status(Enum):
    OK = "ok"              # 正常且有数据
    EMPTY = "empty"        # 正常但无数据
    AUTH = "auth"          # Cookie 失效 / 需要登录
    BLOCKED = "blocked"    # 被限流 / 风控
    ERROR = "error"        # 网络或解析异常


@dataclass
class FetchResult:
    status: Status
    items: list[Weibo] = field(default_factory=list)


@dataclass
class Health:
    counts: dict = field(default_factory=lambda: {s: 0 for s in Status})

    def record(self, st: Status) -> None:
        self.counts[st] += 1

    @property
    def auth_failures(self) -> int:
        return self.counts[Status.AUTH]

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def summary(self) -> str:
        return "  ".join(f"{s.value}:{n}" for s, n in self.counts.items() if n)


_AUTH_HINTS = ("passport.weibo", "login", "请先登录", "帐号登录", "Sina Visitor")
_BLOCK_HINTS = ("频繁", "访问过快", "414", "418")


def build_session(cookie: str) -> requests.Session:
    s = requests.Session()
    s.headers["Cookie"] = cookie
    retry = Retry(total=2, backoff_factor=1.5,
                  status_forcelist=(500, 502, 503, 504),
                  allowed_methods=("GET",))
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def _classify_response(r: requests.Response) -> Status | None:
    """根据响应判断异常状态；正常 JSON 返回 None 由调用方继续解析"""
    if r.status_code in (403, 418):
        return Status.BLOCKED
    if r.status_code in (401,):
        return Status.AUTH
    if r.status_code != 200:
        return Status.ERROR
    text = r.text[:2000]
    if not text.strip().startswith("{"):
        # 返回了 HTML：大概率是登录页或风控页
        low = text.lower()
        if any(h.lower() in low for h in _AUTH_HINTS):
            return Status.AUTH
        if any(h in text for h in _BLOCK_HINTS):
            return Status.BLOCKED
        return Status.ERROR
    return None


def _detail_payload(data: object) -> dict | None:
    """Normalize the different shapes returned by the status detail API."""
    if not isinstance(data, dict):
        return None
    payload = data.get("data")
    if isinstance(payload, dict):
        nested = payload.get("status")
        if isinstance(nested, dict):
            return nested
        return payload
    return data


def _hydrate_long_mblog(session: requests.Session, mb: dict,
                        headers: dict[str, str]) -> dict:
    """Replace a search-card excerpt with the status detail's full text.

    The mobile search API marks long posts with ``isLongText`` but often only
    returns the excerpt and a "全文" link.  The detail endpoint carries the
    actual ``longText.longTextContent`` and may also contain richer image
    metadata, so use it before parsing the Weibo object.
    """
    if not mb or not mb.get("isLongText"):
        return mb
    long_text = mb.get("longText")
    if isinstance(long_text, dict) and long_text.get("longTextContent"):
        return mb

    wid = str(mb.get("id") or mb.get("mid") or "").strip()
    if not wid:
        return mb

    cache = getattr(session, "_weibo_detail_cache", None)
    if cache is None:
        cache = {}
        setattr(session, "_weibo_detail_cache", cache)
    if wid in cache:
        detail = cache[wid]
    else:
        detail_headers = dict(headers)
        detail_headers["Referer"] = f"https://m.weibo.cn/detail/{wid}"
        try:
            response = session.get(
                "https://m.weibo.cn/api/statuses/show",
                params={"id": wid},
                headers=detail_headers,
                timeout=15,
            )
            bad = _classify_response(response)
            if bad:
                log.warning("长微博全文补取失败 [%s]: %s", wid, bad.value)
                detail = None
            else:
                detail = _detail_payload(response.json())
        except (requests.RequestException, ValueError, TypeError) as exc:
            log.warning("长微博全文补取失败 [%s]: %s", wid, exc)
            detail = None
        cache[wid] = detail

    if not detail:
        return mb

    full = detail.get("longText")
    full_text = full.get("longTextContent") if isinstance(full, dict) else ""
    full_text = full_text or detail.get("text")
    if not isinstance(full_text, str) or not clean_text(full_text):
        return mb

    hydrated = dict(mb)
    hydrated["text"] = full_text
    hydrated["longText"] = {"longTextContent": full_text}
    # Search cards normally include pics, but detail data is a useful fallback
    # when the search response omits them.
    for key in ("pics", "pic_infos", "pic_ids", "pic_num", "original_pic", "bmiddle_pic"):
        if detail.get(key):
            hydrated[key] = detail[key]
    log.info("已补取长微博全文 [%s]: %d→%d字",
             wid, len(clean_text(mb.get("text", ""))), len(clean_text(full_text)))
    return hydrated


def search_mobile(session: requests.Session, keyword: str, page: int) -> FetchResult:
    """移动端 container 接口"""
    cid = f"100103type=61&q={keyword}&t=0"
    headers = {
        "User-Agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5) "
                       "AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"),
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://m.weibo.cn/search?containerid=" + quote(cid),
    }
    try:
        r = session.get(
            "https://m.weibo.cn/api/container/getIndex",
            params={"containerid": cid, "page_type": "searchall", "page": page},
            headers=headers, timeout=15,
        )
        bad = _classify_response(r)
        if bad:
            return FetchResult(bad)
        data = r.json()
        if data.get("ok") != 1:
            msg = str(data.get("msg", ""))
            if "登录" in msg:
                return FetchResult(Status.AUTH)
            return FetchResult(Status.EMPTY)
        items: list[Weibo] = []
        for card in data.get("data", {}).get("cards", []):
            for mb in _extract_mblogs(card):
                w = parse_mblog(_hydrate_long_mblog(session, mb, headers), keyword)
                if w:
                    items.append(w)
        return FetchResult(Status.OK if items else Status.EMPTY, items)
    except requests.RequestException as e:
        log.warning("mobile search failed kw=%s p=%s: %s", keyword, page, e)
        return FetchResult(Status.ERROR)
    except (ValueError, KeyError, TypeError) as e:
        log.warning("mobile parse failed kw=%s p=%s: %s", keyword, page, e)
        return FetchResult(Status.ERROR)


def search_general(session: requests.Session, keyword: str, page: int) -> FetchResult:
    """通用兜底：换 containerid 类型再搜一次"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/125.0.0.0 Mobile",
        "Accept": "application/json",
        "Referer": "https://m.weibo.cn/",
    }
    last = Status.EMPTY
    for cid in (f"100103type=61&q={keyword}&t=0", f"100103type=1&q={keyword}&t=0"):
        try:
            r = session.get(
                "https://m.weibo.cn/api/container/getIndex",
                params={"containerid": cid, "page": page},
                headers=headers, timeout=12,
            )
            bad = _classify_response(r)
            if bad:
                last = bad
                continue
            data = r.json()
            if data.get("ok") != 1:
                continue
            items: list[Weibo] = []
            for card in data.get("data", {}).get("cards", []):
                if card.get("card_type") == 9 and card.get("mblog"):
                    w = parse_mblog(
                        _hydrate_long_mblog(session, card["mblog"], headers),
                        keyword,
                    )
                    if w:
                        items.append(w)
            if items:
                return FetchResult(Status.OK, items)
        except requests.RequestException as e:
            log.warning("general search failed kw=%s: %s", keyword, e)
            last = Status.ERROR
        except (ValueError, KeyError, TypeError):
            last = Status.ERROR
    return FetchResult(last)


def _extract_mblogs(card: dict) -> list[dict]:
    if card.get("card_type") == 9 and card.get("mblog"):
        return [card["mblog"]]
    if card.get("card_type") == 11:
        return [sub["mblog"] for sub in card.get("card_group", [])
                if sub.get("card_type") == 9 and sub.get("mblog")]
    return []
