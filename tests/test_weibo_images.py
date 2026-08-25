from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wb_parser import parse_mblog, parse_status


def _base_raw(identifier: str) -> dict:
    return {
        "id": identifier,
        "created_at": "刚刚",
        "text": "这是一条包含现场配图的公共问题反映。",
        "user": {"screen_name": "测试用户"},
    }


def test_parse_mblog_keeps_large_image_urls():
    raw = _base_raw("mobile-image")
    raw["pics"] = [
        {
            "url": "https://img.example.com/thumb.jpg",
            "large": {"url": "//img.example.com/large.jpg"},
        },
        {"url": "https://img.example.com/second.jpg"},
    ]

    weibo = parse_mblog(raw, "投诉")

    assert weibo is not None
    assert weibo.image_urls == [
        "https://img.example.com/large.jpg",
        "https://img.example.com/second.jpg",
    ]


def test_parse_status_keeps_pc_image_urls_in_post_order():
    raw = _base_raw("pc-image")
    raw["text_raw"] = raw.pop("text")
    raw["pic_ids"] = ["pid-2", "pid-1"]
    raw["pic_infos"] = {
        "pid-1": {"large": {"url": "https://img.example.com/one.jpg"}},
        "pid-2": {"largest": {"url": "https://img.example.com/two.jpg"}},
    }

    weibo = parse_status(raw, "投诉")

    assert weibo is not None
    assert weibo.image_urls == [
        "https://img.example.com/two.jpg",
        "https://img.example.com/one.jpg",
    ]


def test_parse_mblog_includes_retweeted_post_images_without_duplicates():
    raw = _base_raw("repost-image")
    raw["pics"] = [{"large": {"url": "https://img.example.com/shared.jpg"}}]
    raw["retweeted_status"] = {
        "pics": [
            {"large": {"url": "https://img.example.com/shared.jpg"}},
            {"large": {"url": "https://img.example.com/original.jpg"}},
        ]
    }

    weibo = parse_mblog(raw, "投诉")

    assert weibo is not None
    assert weibo.image_urls == [
        "https://img.example.com/shared.jpg",
        "https://img.example.com/original.jpg",
    ]
