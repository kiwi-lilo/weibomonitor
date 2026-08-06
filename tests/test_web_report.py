from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Weibo
from reporter import (
    build_personal_report_payload,
    build_leader_summary_text,
    build_web_report_html,
    save_web_report,
)


def _weibo() -> Weibo:
    weibo = Weibo(
        id="web-1",
        user="用户<b>",
        text="小区电梯停运<script>alert(1)</script>",
        time="2026-08-05 08:30",
        url="https://weibo.com/web-1",
        keyword="电梯",
        sentiment_label="负面",
        regions=["汉中", "汉台区"],
        comments=12,
    )
    weibo.summary = "某小区电梯长期停运，居民出行受到影响。"
    return weibo


def test_web_report_has_individual_copy_control_and_escapes_content(tmp_path):
    weibo = _weibo()
    sections = [{
        "city": "汉中",
        "new_neg": 1,
        "total": 20,
        "health_ok": True,
    }]

    rendered = build_web_report_html(
        sections,
        "2026-08-03 ~ 2026-08-05",
        [("汉中", weibo)],
    )
    output_path = save_web_report(rendered, str(tmp_path))

    assert os.path.basename(output_path) == "latest.html"
    assert "aria-label=\"复制第 1 条舆情\"" in rendered
    assert "navigator.clipboard.writeText" in rendered
    assert "某小区电梯长期停运" in rendered
    assert "△某小区电梯长期停运" in rendered
    assert "（新浪微博：用户&lt;b&gt;）" in rendered
    assert "用户&lt;b&gt;" in rendered
    assert "<b>" not in rendered
    assert os.path.exists(output_path)
    assert (tmp_path / "index.html").read_text(encoding="utf-8") == rendered


def test_web_report_empty_state():
    rendered = build_web_report_html(
        [{"city": "汉中", "new_neg": 0, "total": 20, "health_ok": True}],
        "2026-08-03 ~ 2026-08-05",
        [],
    )

    assert "未发现新增个人负面舆情" in rendered
    assert "class=\"copy-button\"" not in rendered


def test_personal_report_payload_is_dashboard_contract():
    weibo = _weibo()
    weibo.summary = "△居民反映电梯停运，出行受到影响"
    other = _weibo()
    other.id = "web-2"
    other.text = "另一条尚未生成摘要的新增舆情"
    other.url = "https://weibo.com/web-2"
    other.summary = ""
    payload = build_personal_report_payload(
        [{"city": "汉中", "new_neg": 1, "total": 20, "health_ok": True}],
        "2026-08-03 ~ 2026-08-05",
        [("汉中", weibo)],
        [("汉中", weibo), ("汉中", other)],
    )

    item = payload["recommendations"][0]
    assert payload["source"] == "personal"
    assert payload["stats"] == {
        "new_neg": 1,
        "total_posts": 20,
        "healthy": 1,
        "city_count": 1,
    }
    assert not item["summary"].startswith("△")
    assert item["copy_text"] == (
        f"△{item['summary']}（新浪微博：{item['user']}）{item['url']}"
    )
    assert item["url"] == weibo.url
    assert payload["unsummarized"][0]["id"] == other.id
    assert payload["unsummarized"][0]["text"] == other.text


def test_personal_post_browsers_use_short_source_text_without_llm_titles():
    monitored = _weibo()
    monitored.id = "monitored-1"
    monitored.text = "监测帖子第一句。监测帖子第二句。监测帖子第三句。"
    monitored.summary = "这段模型摘要不应该成为帖子标题。"
    negative = _weibo()
    negative.id = "negative-1"
    negative.text = "新增负面第一句。新增负面第二句。"

    payload = build_personal_report_payload(
        [{"city": "汉中", "new_neg": 1, "total": 2, "health_ok": True}],
        "2026-08-03 ~ 2026-08-05",
        [],
        monitored_items=[("汉中", monitored)],
        new_negative_items=[("汉中", negative)],
    )

    monitored_item = payload["monitored_posts"][0]
    assert monitored_item["title"] == "监测帖子第一句。"
    assert monitored_item["excerpt"] == "监测帖子第一句。监测帖子第二句。"
    assert "模型摘要" not in monitored_item["title"]
    assert monitored_item["url"] == monitored.url
    assert payload["new_negatives"][0]["title"] == "新增负面第一句。"


def test_personal_copy_format_has_triangle_and_source_suffix():
    weibo = _weibo()
    weibo.summary = "△某小区电梯停运，居民出行受影响"

    assert build_leader_summary_text([weibo]) == (
        "△某小区电梯停运，居民出行受影响（新浪微博：用户<b>）"
        "https://weibo.com/web-1"
    )
