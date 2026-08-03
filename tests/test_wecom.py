from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import Settings
from models import Weibo
from wecom import build_alert_message, build_digest_messages, send_wecom


def _weibo(number: int) -> Weibo:
    return Weibo(
        id=str(number),
        user="热心市民",
        text="陕西某地产业项目取得新进展，群众获得感持续提升。",
        time="2026-08-03 10:00",
        url=f"https://weibo.com/{number}",
        keyword="",
        sentiment_label="关注",
        summary=f"陕西项目取得新进展，群众获得感持续提升（第{number}条）",
        regions=["陕西"],
    )


def test_digest_is_styled_and_split_into_two_messages():
    sections = [{"city": "汉中", "new_neg": 2, "total": 80, "health_ok": True}]
    highlights = [("汉中", _weibo(number)) for number in range(1, 11)]

    messages = build_digest_messages(
        sections,
        "2026-08-02 ~ 2026-08-03",
        highlights,
    )

    assert len(messages) == 2
    assert "陕西舆情日报" in messages[0].content
    assert "今日推荐候选 01–05" in messages[0].content
    assert "今日推荐候选 06–10" in messages[1].content
    assert messages[0].content.count("[查看原微博]") == 5
    assert "<font color=\"warning\">" in messages[0].content


def test_alert_message_contains_actionable_context():
    message = build_alert_message("Cookie 失效")
    assert "舆情监测采集异常" in message.content
    assert "Cookie 失效" in message.content


def test_send_wecom_posts_markdown_payload(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"errcode": 0, "errmsg": "ok"}

    def fake_post(url, *, json, timeout):
        captured.update(url=url, json=json, timeout=timeout)
        return Response()

    monkeypatch.setattr("wecom.requests.post", fake_post)
    settings = Settings(
        cookie="cookie",
        wecom_webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
    )
    message = build_alert_message("接口异常")

    assert send_wecom(settings, message)
    assert captured["url"].startswith("https://qyapi.weixin.qq.com")
    assert captured["timeout"] == (5, 20)
    assert captured["json"]["msgtype"] == "markdown"
    assert "接口异常" in captured["json"]["markdown"]["content"]


def test_send_wecom_skips_missing_webhook(monkeypatch):
    monkeypatch.setattr(
        "wecom.requests.post",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应请求企业微信")),
    )
    assert not send_wecom(Settings(cookie="cookie", wecom_webhook=""), build_alert_message("异常"))
