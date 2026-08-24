from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

index = pytest.importorskip("index")


def _news(media, title, link):
    return {"media": media, "title": title, "link": link, "time": "08-03 10:00"}


def test_weather_disaster_and_negative_news_are_excluded():
    rejected = [
        "陕西发布暴雨红色预警 多地迎来强降水",
        "陕西部分地区发生洪涝灾害",
        "西安一地发生安全事故造成伤亡",
        "陕西气象台发布高温预警",
    ]
    assert all(not index.title_is_relevant(title) for title in rejected)


def test_positive_shaanxi_achievement_news_is_kept():
    accepted = [
        "陕西科技创新成果加速落地取得新突破",
        "西安中欧班列开行量增长 枢纽建设再提速",
        "陕西乡村振兴实践助力群众增收",
        "陕西非遗保护与文旅产业融合发展",
    ]
    assert all(index.title_is_relevant(title) for title in accepted)


def test_cross_media_rewrites_of_one_event_keep_authoritative_source():
    less_authoritative = _news(
        "中国新闻网",
        "陕西：现代化产业体系建设取得新成效",
        "https://example.com/2",
    )
    authoritative = _news(
        "人民日报",
        "陕西加快建设现代化产业体系取得新成效",
        "https://example.com/1",
    )
    another_event = _news(
        "新华网",
        "西安科技创新成果加速落地",
        "https://example.com/3",
    )

    assert index.same_news_event(authoritative, less_authoritative)
    selected = index.deduplicate_news_events(
        [less_authoritative, authoritative, another_event]
    )
    assert [item["link"] for item in selected] == [
        "https://example.com/1",
        "https://example.com/3",
    ]


def test_top_ten_never_backfills_with_weather_to_reach_ten():
    items = [
        _news("人民日报", "陕西科技创新成果取得新突破", "https://example.com/good"),
        _news("新华网", "陕西发布暴雨红色预警", "https://example.com/weather"),
    ]
    selected = index.get_top_10(items)
    assert [item["link"] for item in selected] == ["https://example.com/good"]
