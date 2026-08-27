from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fetcher import Status, search_mobile


class _Response:
    status_code = 200

    def __init__(self, payload: dict):
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


class _Session:
    def __init__(self, search_payload: dict, detail_payload: dict):
        self.search_payload = search_payload
        self.detail_payload = detail_payload
        self.calls: list[str] = []

    def get(self, url, *, params, headers, timeout):
        self.calls.append(url)
        if url.endswith("/api/container/getIndex"):
            return _Response(self.search_payload)
        if url.endswith("/api/statuses/show"):
            return _Response(self.detail_payload)
        raise AssertionError(url)


def _mblog() -> dict:
    return {
        "id": "long-1",
        "mid": "long-1",
        "created_at": "刚刚",
        "isLongText": True,
        "text": "前文内容……<a href='/status/long-1'>全文</a>",
        "user": {"screen_name": "普通用户"},
        "pics": [{"large": {"url": "https://img.example.com/evidence.jpg"}}],
    }


def test_search_mobile_hydrates_long_text_before_parsing():
    search_payload = {"ok": 1, "data": {"cards": [{"card_type": 9, "mblog": _mblog()}]}}
    detail_payload = {
        "id": "long-1",
        "isLongText": True,
        "text": "仍是截断正文",
        "longText": {
            "longTextContent": "完整正文写明累计拖欠135人工资共220万元，劳动监察程序已经走完。"
        },
    }
    session = _Session(search_payload, detail_payload)

    result = search_mobile(session, "欠薪", 1)

    assert result.status is Status.OK
    assert len(result.items) == 1
    assert "135人" in result.items[0].text
    assert "220万元" in result.items[0].text
    assert result.items[0].image_urls == ["https://img.example.com/evidence.jpg"]
    assert session.calls.count("https://m.weibo.cn/api/statuses/show") == 1


def test_search_mobile_caches_detail_lookup_for_duplicate_long_posts():
    raw = _mblog()
    search_payload = {
        "ok": 1,
        "data": {
            "cards": [
                {"card_type": 9, "mblog": raw},
                {"card_type": 9, "mblog": dict(raw)},
            ]
        },
    }
    detail_payload = {
        "id": "long-1",
        "longText": {"longTextContent": "这是一段完整正文。"},
    }
    session = _Session(search_payload, detail_payload)

    result = search_mobile(session, "欠薪", 1)

    assert result.status is Status.OK
    assert len(result.items) == 2
    assert session.calls.count("https://m.weibo.cn/api/statuses/show") == 1
