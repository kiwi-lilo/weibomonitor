from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from event_dedup import deduplicate_event_candidates, same_event
from models import Weibo


def _weibo(identifier, text, topics, heat=0):
    return Weibo(
        id=identifier,
        user=f"用户{identifier}",
        text=text,
        time="2026-08-03 10:00",
        url=f"https://weibo.com/{identifier}",
        keyword="",
        regions=["雁塔区"],
        medium_neg=topics,
        likes=heat,
    )


def test_paraphrased_posts_about_one_incident_are_deduplicated():
    first = _weibo(
        "1",
        "西安雁塔区某小区电梯停运半个月，物业一直不维修，居民上下楼困难",
        ["物业不维修"],
        heat=20,
    )
    repost = _weibo(
        "2",
        "雁塔区这个小区的电梯已经坏了半个月，多名业主反映物业迟迟没人修，老人出行不便",
        ["物业不维修"],
        heat=2,
    )

    assert same_event(first, repost)
    assert deduplicate_event_candidates([("西安", first), ("西安", repost)]) == [
        ("西安", first)
    ]


def test_different_incidents_in_one_district_are_not_merged():
    elevator = _weibo(
        "1",
        "西安雁塔区某小区电梯停运半个月，物业一直不维修，居民上下楼困难",
        ["物业不维修"],
    )
    school = _weibo(
        "3",
        "雁塔区某学校食堂存在乱收费问题，家长要求公开收费明细",
        ["乱收费"],
    )

    assert not same_event(elevator, school)
    assert len(deduplicate_event_candidates([("西安", elevator), ("西安", school)])) == 2


def test_paraphrased_rumor_posts_about_one_topic_are_deduplicated():
    first = _weibo(
        "4",
        "网传某男艺人涉嫌育有私生子的谣言引发热议，狗仔匿名爆料并将线索指向周杰伦，未提供实质证据",
        ["不实传闻"],
        heat=30,
    )
    repost = _weibo(
        "5",
        "周杰伦与刘姓女股东产子传闻持续发酵，网络爆料全程没有照片或鉴定，相关方面正在辟谣澄清",
        ["网络传闻"],
        heat=3,
    )

    assert same_event(first, repost)
    assert deduplicate_event_candidates([("西安", first), ("西安", repost)]) == [
        ("西安", first)
    ]


def test_different_rumors_are_not_merged_without_a_shared_entity():
    divorce = _weibo(
        "6",
        "某演员离婚传闻引发热议，网络爆料指向当事人，相关方面暂无回应",
        ["网络传闻"],
    )
    tax = _weibo(
        "7",
        "某歌手涉嫌偷税传闻引发关注，狗仔爆料指向当事人，相关方面暂无回应",
        ["网络传闻"],
    )

    assert not same_event(divorce, tax)
