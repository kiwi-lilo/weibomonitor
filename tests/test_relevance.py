from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analyzer import is_government_relevant
from models import Weibo


def _post(text: str) -> Weibo:
    return Weibo(
        id="relevance",
        user="普通用户",
        text=text,
        time="2026-08-26 09:00",
        url="https://weibo.com/relevance",
        keyword="",
    )


def test_government_relevant_cases_are_kept():
    samples = (
        "累计被拖欠工资144928元，手握手写欠条13万余元，另有2025年7000元工钱没有写进欠条，恳请兰州、西安两地相关部门督促结清。",
        "水改后12天用水400吨，居民反映水费异常，请有关部门核查。",
        "街道社区调解物业纠纷，居民反映小区停车收费和公共收益问题。",
        "网民举报一辆车长期交通违法，请交警部门处理。",
        "西安地铁5号线多个站名翻译不当，网民建议排查更正。",
        "宝鸡渭滨区公交一直没来，居民希望解决。",
    )

    for text in samples:
        relevant, reason = is_government_relevant(_post(text))
        assert relevant, (text, reason)


def test_personal_life_and_marketing_posts_are_filtered():
    samples = (
        "赵子洲、王立新等人铺天盖地搞营销，黑心医生，大家赶紧标记避雷。",
        "榆林进入过敏最严重时段，我眼睛发红、鼻塞流涕，晚上呼吸不畅睡不着。",
        "苹果手机或充电器坏了，身边没人能借充电器测试，只能回榆林再排查。",
    )

    for text in samples:
        relevant, reason = is_government_relevant(_post(text))
        assert not relevant, (text, reason)


def test_generic_labor_guide_without_case_is_filtered():
    relevant, reason = is_government_relevant(_post(
        "神木劳动纠纷维权攻略网帖发布，以揭秘姿态传播专业律师经验、案例与维权建议。"
    ))

    assert not relevant
    assert reason == "泛化攻略/经验文章"
