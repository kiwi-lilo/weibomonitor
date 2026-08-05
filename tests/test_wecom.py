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


def test_pages_mode_sends_one_fixed_report_link():
    sections = [{"city": "汉中", "new_neg": 10, "total": 80, "health_ok": True}]
    highlights = [("汉中", _weibo(number)) for number in range(1, 11)]

    messages = build_digest_messages(
        sections,
        "2026-08-04 ~ 2026-08-05",
        highlights,
        report_url="https://example.github.io/monitor/latest.html",
    )

    assert len(messages) == 1
    assert "今日推荐候选 10 条" in messages[0].content
    assert "https://example.github.io/monitor/latest.html" in messages[0].content
    assert "[查看原微博]" not in messages[0].content


def test_pages_report_url_is_derived_from_github_repository(monkeypatch):
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/weibomonitor")

    settings = Settings(cookie="cookie", report_url="")

    assert settings.pages_report_url == (
        "https://example.github.io/weibomonitor/latest.html"
    )


def test_long_summaries_are_not_truncated_and_messages_stay_within_limit():
    sections = [{"city": "汉中", "new_neg": 10, "total": 80, "health_ok": True}]
    highlights = []
    summaries = []
    for number in range(1, 11):
        weibo = _weibo(number)
        summary = (
            f"第{number}条舆情涉及具体地点、责任主体和公共设施维护经过，"
            "原帖详细说明了问题出现时间、持续状态、处置过程以及尚未公开的维修进度。"
            "相关数据和事件节点均完整保留，用于说明事情的来龙去脉。"
        )
        weibo.summary = summary
        summaries.append(summary)
        highlights.append(("汉中", weibo))

    messages = build_digest_messages(
        sections,
        "2026-08-03 ~ 2026-08-04",
        highlights,
    )

    combined = "\n".join(message.content for message in messages)
    assert 2 <= len(messages) <= 3
    assert all(summary in combined for summary in summaries)
    assert all(len(message.content.encode("utf-8")) <= 3900 for message in messages)


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
