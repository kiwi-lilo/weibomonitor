from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

index = pytest.importorskip("index")


def _item(number):
    link = f"https://news.example.com/{number}"
    return {
        "media": "人民日报",
        "title": f"陕西新闻标题{number}",
        "link": link,
        "time": "08-03 10:00",
        "llm_summary": f"【人民日报】陕西新闻摘要{number}。\n{link}",
    }


def test_build_bark_messages_splits_top_ten_and_keeps_copy_format():
    items = [_item(number) for number in range(1, 11)]
    messages = index.build_bark_messages(items, items)

    assert len(messages) == 2
    assert messages[0]["title"] == "📰 央媒涉陕推荐 1–5"
    assert messages[1]["title"] == "📰 央媒涉陕推荐 6–10"
    assert messages[0]["body"].count("△") == 5
    assert messages[1]["body"].count("△") == 5
    combined_lines = "\n".join(message["body"] for message in messages).splitlines()
    for number in range(1, 11):
        assert combined_lines.count(f"https://news.example.com/{number}") == 1


def test_send_bark_uses_standard_library_json_post(monkeypatch):
    captured = {}

    def fake_http_post(url, data_bytes, headers, timeout):
        captured.update(
            url=url,
            payload=index.json.loads(data_bytes.decode("utf-8")),
            headers=headers,
            timeout=timeout,
        )
        return b'{"code":200,"message":"success"}'

    monkeypatch.setattr(index, "BARK_URL", "https://api.day.app/device-key")
    monkeypatch.setattr(index, "http_post", fake_http_post)
    message = {
        "title": "测试标题",
        "subtitle": "测试日期",
        "body": "测试正文",
        "level": "active",
        "url": "https://news.example.com/1",
    }

    assert index.send_bark(message)
    assert captured["url"] == "https://api.day.app/device-key"
    assert captured["timeout"] == 20
    assert captured["headers"]["Content-Type"] == "application/json; charset=utf-8"
    assert captured["payload"]["group"] == "央媒涉陕报道"
    assert captured["payload"]["url"] == "https://news.example.com/1"


def test_send_bark_skips_blank_configuration(monkeypatch):
    monkeypatch.setattr(index, "BARK_URL", "")
    monkeypatch.setattr(
        index,
        "http_post",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应请求 Bark")),
    )
    assert not index.send_bark({"title": "标题", "body": "正文"})
