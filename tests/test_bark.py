from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bark import BarkMessage, build_alert_message, build_digest_messages, send_bark
from config import Settings
from models import Weibo


def _weibo(**overrides) -> Weibo:
    data = {
        "id": "1001",
        "user": "热心市民",
        "text": "某小区电梯停运多日，物业一直没有处理，居民出行困难。",
        "time": "2026-08-02 10:00",
        "url": "https://weibo.com/1001",
        "keyword": "小区",
        "sentiment_label": "负面",
        "sentiment_score": 0.1,
        "regions": ["榆阳区"],
        "comments": 8,
        "likes": 12,
    }
    data.update(overrides)
    return Weibo(**data)


def test_digest_message_is_mobile_friendly():
    weibo = _weibo()
    sections = [
        {"city": "榆林", "new_neg": 1, "total": 32, "health_ok": True},
        {"city": "西安", "new_neg": 0, "total": 58, "health_ok": True},
    ]

    message = build_digest_messages(
        sections,
        "2026-07-31 ~ 2026-08-02",
        [("榆林", weibo)],
        "https://github.com/example/repo/actions/runs/123",
    )[0]

    assert message.title == "🔴 陕西舆情日报｜新增 1 条"
    assert message.subtitle == "2026-07-31 至 2026-08-02"
    assert "榆林 1 · 西安 0" in message.body
    assert "今日推荐候选 1–1" in message.body
    assert "采集健康 2/2" in message.body
    assert message.level == "timeSensitive"
    assert message.url == ""
    assert "01｜榆林 · 负面 · 榆阳区 · 热度 28" in message.body
    assert "某小区电梯停运多日" in message.body
    assert "△某小区电梯停运多日" not in message.body
    assert "新浪微博：热心市民" not in message.body
    assert "https://weibo.com/1001" in message.body


def test_clean_digest_is_passive():
    message = build_digest_messages(
        [{"city": "汉中", "new_neg": 0, "total": 20, "health_ok": True}],
        "2026-08-01 ~ 2026-08-02",
        [],
    )[0]

    assert message.level == "passive"
    assert "今日平稳" in message.title
    assert "未发现新增个人负面舆情" in message.body


def test_ten_recommendations_are_grouped_into_two_full_messages():
    highlights = []
    for index in range(10):
        weibo = _weibo(
            id=str(index),
            user=f"用户{index + 1}",
            url=f"https://weibo.com/{index + 1}",
            summary=f"第{index + 1}条推荐舆情摘要",
        )
        highlights.append(("榆林", weibo))

    messages = build_digest_messages(
        [{"city": "榆林", "new_neg": 10, "total": 40, "health_ok": True}],
        "2026-08-01 ~ 2026-08-02",
        highlights,
    )

    assert len(messages) == 2
    assert "今日推荐候选 1–5" in messages[0].body
    assert messages[1].title == "📌 今日推荐候选 6–10"
    assert messages[0].url == ""
    assert messages[1].url == ""
    for index in range(1, 11):
        assert any(
            f"https://weibo.com/{index}" in message.body for message in messages
        )


def test_single_item_keeps_full_summary_and_opens_original_weibo():
    summary = "某小区连续停水，居民多次联系物业后仍未恢复供水，影响老人和儿童日常生活。" * 4
    weibo = _weibo(summary=summary)

    messages = build_digest_messages(
        [{"city": "榆林", "new_neg": 1, "total": 1, "health_ok": True}],
        "2026-08-02 ~ 2026-08-03",
        [("榆林", weibo)],
        "https://github.com/example/repo/actions/runs/123",
    )

    assert len(messages) == 1
    assert summary in messages[0].body
    assert not messages[0].body.endswith("…")
    assert messages[0].url == ""


def test_alert_is_time_sensitive():
    message = build_alert_message("Cookie 失效")
    assert message.level == "timeSensitive"
    assert "Cookie 失效" in message.body
    assert "本轮任务已中止" == message.subtitle


def test_send_bark_posts_json(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 200, "message": "success"}

    def fake_post(url, *, json, timeout):
        captured.update(url=url, json=json, timeout=timeout)
        return Response()

    monkeypatch.setattr("bark.requests.post", fake_post)
    settings = Settings(
        cookie="cookie",
        bark_url="https://api.day.app/device-key",
        bark_group="测试分组",
        bark_icon="https://example.com/icon.png",
    )
    message = BarkMessage("日报", "正文", subtitle="日期", url="https://example.com/run")

    assert send_bark(settings, message)
    assert captured["url"] == "https://api.day.app/device-key"
    assert captured["timeout"] == (5, 20)
    assert captured["json"] == {
        "title": "日报",
        "subtitle": "日期",
        "body": "正文",
        "group": "测试分组",
        "level": "active",
        "icon": "https://example.com/icon.png",
        "url": "https://example.com/run",
    }


def test_send_bark_skips_missing_url(monkeypatch):
    monkeypatch.setattr(
        "bark.requests.post",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应发起请求")),
    )
    assert not send_bark(Settings(cookie="cookie", bark_url=""), BarkMessage("标题", "正文"))
    assert not Settings(cookie="cookie", bark_url="https://api.day.app").bark_ready
