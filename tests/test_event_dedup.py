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


def test_todays_rewrites_of_dingbian_assault_are_one_event():
    posts = [
        _weibo(
            "dingbian-1",
            "#男孩被民警掌掴近1个月未能正常上学#陕西定边县13岁少年被公职人员殴打致颅脑损伤，涉事人员被处十日处罚",
            ["殴打"],
            heat=569,
        ),
        _weibo(
            "dingbian-2",
            "#13岁男孩被民警掌掴致伤不敢出门#陕西定边县13岁男孩夜间回家，被公职人员无故殴打，民警郭某掌掴男孩，造成闭合性轻型颅脑损伤、耳鸣",
            ["殴打"],
            heat=23,
        ),
        _weibo(
            "dingbian-3",
            "#男孩被民警掌掴近1个月未能正常上学#陕西定边13岁男孩回家途中被公积金工作人员刘某踢打，报警时又被民警郭某掌掴",
            ["殴打"],
            heat=16,
        ),
        _weibo(
            "dingbian-4",
            "13岁男孩被民警掌掴致颅脑损伤，拘留10天就完事了？道歉和赔偿不能少",
            ["殴打"],
            heat=1,
        ),
    ]
    for post in posts:
        post.regions = ["定边县"]

    result = deduplicate_event_candidates([("榆林", post) for post in posts])

    assert result == [("榆林", posts[0])]


def test_different_assaults_in_one_county_are_not_merged():
    april = _weibo(
        "assault-april",
        "定边县4月25日一名13岁男孩被民警郭某掌掴，造成颅脑损伤和耳鸣",
        ["殴打"],
    )
    july = _weibo(
        "assault-july",
        "定边县7月12日一名16岁女孩在校外被工作人员殴打，手臂骨折",
        ["殴打"],
    )
    april.regions = july.regions = ["定边县"]

    assert not same_event(april, july)
