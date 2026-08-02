"""fetcher.py — 微博采集

核心改进（相对 v4）：
1. 每次请求显式区分 5 种结果状态，Cookie 失效 / 被限流不再伪装成"0 条"。
2. requests.Session 挂自动重试（连接错误 / 5xx 指数退避）。
3. Health 计数器供 main 决策：掉登录立即中止并发送邮件、Bark 告警。
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
from wb_parser import parse_mblog, parse_status

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
                w = parse_mblog(mb, keyword)
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
                    w = parse_mblog(card["mblog"], keyword)
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
