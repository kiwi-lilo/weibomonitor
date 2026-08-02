from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Weibo
from reporter import build_alert_html, build_digest_html


def test_digest_email_contains_copy_area_and_escapes_content():
    weibo = Weibo(
        id="1",
        user="用户<b>",
        text="小区电梯停运<script>alert(1)</script>",
        time="2026-08-02 10:00",
        url="https://weibo.com/1",
        keyword="电梯",
        sentiment_label="负面",
        regions=["榆阳区"],
    )
    sections = [{
        "city": "榆林",
        "new_neg": 1,
        "total": 20,
        "old_neg": 2,
        "filtered": 3,
        "health_summary": "OK",
        "health_ok": True,
        "new_negatives": [weibo],
    }]

    rendered = build_digest_html(
        sections,
        "2026-08-01 ~ 2026-08-02",
        leader_text="△推荐<script>（新浪微博：用户）https://weibo.com/1",
    )

    assert "今日推荐候选" in rendered
    assert "榆林舆情" in rendered
    assert "&lt;script&gt;" in rendered
    assert "<script>" not in rendered


def test_alert_email_escapes_reason():
    rendered = build_alert_html("Cookie <失效>", "状态 <异常>")
    assert "Cookie &lt;失效&gt;" in rendered
    assert "状态 &lt;异常&gt;" in rendered
