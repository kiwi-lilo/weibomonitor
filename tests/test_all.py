"""针对上一版实际踩过的坑写的回归测试。运行：pytest tests/ -v"""

from __future__ import annotations

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import TZ
from wb_parser import parse_time, within_days, clean_text
from analyzer import analyze, is_entertainment_news, is_official
from cities import HANZHONG
from models import Weibo


def _w(text, **kw) -> Weibo:
    return Weibo(id="1", user=kw.pop("user", "普通用户小张"), text=text,
                 time="2026-07-25 10:00", url="", keyword="", **kw)


# ── 时间解析 ──

NOW = datetime(2026, 7, 26, 23, 0, tzinfo=TZ)


def test_relative_time():
    assert parse_time("5分钟前", NOW) == "2026-07-26 22:55"
    assert parse_time("2小时前", NOW) == "2026-07-26 21:00"
    assert parse_time("刚刚", NOW) == "2026-07-26 23:00"


def test_today_yesterday():
    assert parse_time("今天 9:30", NOW) == "2026-07-26 09:30"
    assert parse_time("昨天 23:15", NOW) == "2026-07-25 23:15"


def test_cross_year():
    """v4 bug：元旦跑时 12-31 的帖子被补成明年 → 应补去年"""
    jan1 = datetime(2027, 1, 1, 1, 0, tzinfo=TZ)
    assert parse_time("12-31 22:00", jan1).startswith("2026-12-31")


def test_standard_format():
    assert parse_time("Sat Jul 25 20:31:02 +0800 2026", NOW) == "2026-07-25 20:31"


def test_within_days():
    assert within_days("2026-07-25 10:00", 2, NOW)
    assert not within_days("2026-07-20 10:00", 2, NOW)
    assert within_days("解析不了的字符串", 2, NOW)  # 保守保留


def test_clean_text():
    assert clean_text('求助<a href="x">链接</a>  多个   空格') == "求助链接 多个 空格"


# ── 情感研判 ──

def test_youyu_not_negative():
    """v4 最大误报源：中性连词"由于"曾在强负面词库里"""
    w = _w("由于近期下雨，汉中的桂花开得晚了一些，大家周末可以去看看")
    analyze(w, HANZHONG)
    assert w.sentiment_label in ("中性", "正面"), w.sentiment_label


def test_enforcement_news_not_negative():
    """警方整治新闻含'黑恶势力'不应判负面（正面语境否决）"""
    w = _w("汉中警方开展扫黑除恶专项行动，严厉打击黑恶势力，专项整治取得成效，市民纷纷点赞")
    analyze(w, HANZHONG)
    assert w.sentiment_label != "负面", (w.sentiment_label, w.strong_neg, w.positive_ctx)


def test_real_complaint_is_negative():
    w = _w("汉中某小区烂尾三年，我们交了钱不交房，血汗钱打了水漂，投诉无门，没人管，求扩散！")
    analyze(w, HANZHONG)
    assert w.sentiment_label == "负面"
    assert w.strong_neg


def test_medium_complaint():
    w = _w("城固县政务大厅办事难，工作人员态度恶劣，来回踢皮球")
    analyze(w, HANZHONG)
    assert w.sentiment_label in ("负面", "偏负面")


def test_region_tagging():
    w = _w("南郑区某小区烂尾了，交了钱不交房，业主走投无路")
    analyze(w, HANZHONG)
    assert "南郑区" in w.regions


# ── 官方号过滤 ──

def test_blue_v_filtered():
    w = _w("正常内容正常内容", user="某某机构号", verified=True, verified_type=3)
    assert is_official(w)[0]


def test_personal_yellow_v_is_kept():
    w = _w(
        "西安某小区物业乱收费，居民投诉多次仍未解决",
        user="热心记者小张",
        verified=True,
        verified_type=0,
        verified_reason="新闻记者",
    )
    assert not is_official(w)[0]


def test_explicit_official_yellow_v_is_filtered():
    w = _w(
        "正常内容正常内容",
        user="西安日报",
        verified=True,
        verified_type=0,
        verified_reason="官方账号",
    )
    assert is_official(w)[0]


def test_strong_name_filtered():
    w = _w("正常内容正常内容", user="汉中日报")
    assert is_official(w)[0]


def test_weak_name_not_filtered_for_ordinary_user():
    """v4 bug：昵称含'平安'的普通用户被误杀"""
    w = _w("我在汉中遇到了麻烦想求助", user="平安喜乐的小张", verified=False)
    assert not is_official(w)[0]


def test_single_phrase_not_filtered():
    """v4 bug：普通人写'据说/据了解'一个短语就被过滤"""
    w = _w("据了解汉中这家店经常乱收费，大家注意避雷", user="爱吃的小李", verified=False)
    assert not is_official(w)[0]


def test_two_phrases_filtered():
    w = _w("我市召开专题会议，会议强调要贯彻落实相关精神", user="热心网友", verified=False)
    assert is_official(w)[0]


def test_city_focus_queries_add_high_signal_terms_without_district_expansion():
    from keywords import build_queries, CITY_FOCUS_KW, SEARCH_NEGATIVE_KW

    queries = build_queries(["西安", "新城"])
    assert ("西安", "西安 物业费") in queries
    assert ("西安", "西安 拖欠工资") in queries
    assert len(queries) == 2 * len(SEARCH_NEGATIVE_KW) + len(CITY_FOCUS_KW)


# ── 内容范围过滤 ──

def test_entertainment_rumor_is_filtered():
    samples = (
        "网传周杰伦与刘姓女股东产子，娱乐圈狗仔匿名爆料私生子传闻，"
        "相关话题因西安公司登上热搜，目前各方正在辟谣澄清",
        "周杰伦与昆凌相识相恋，早年西安KTV股东同框素材被重新传播，"
        "经纪公司面对不实传闻被批公关不作为，造谣话题持续发酵",
    )

    for text in samples:
        filtered, reason = is_entertainment_news(_w(text))
        assert filtered, text
        assert reason.startswith("娱乐新闻")


def test_entertainment_filter_is_applied_before_sentiment_analysis():
    from main import CityMonitor

    monitor = CityMonitor.__new__(CityMonitor)
    monitor.city = HANZHONG
    monitor.seen_ids, monitor.seen_fp = set(), set()
    monitor.results, monitor.filtered = [], []
    weibo = _w("汉中某明星私生子传闻登上热搜，狗仔爆料后工作室发布辟谣声明")

    assert not monitor._add(weibo)
    assert not monitor.results
    assert monitor.filtered[0]["reason"].startswith("娱乐新闻")


def test_concert_refund_complaint_is_not_filtered_as_entertainment_news():
    w = _w("西安某演唱会取消后主办方迟迟不退款，消费者投诉票务平台没人处理")

    assert not is_entertainment_news(w)[0]


def test_film_crew_noise_complaint_is_not_filtered_as_entertainment_news():
    w = _w("西安某剧组连续多日半夜施工扰民，附近居民投诉后仍未停止")

    assert not is_entertainment_news(w)[0]


# ── 去重 ──

def test_dedup_by_id():
    from main import CityMonitor
    m = CityMonitor.__new__(CityMonitor)
    m.city = HANZHONG
    m.seen_ids, m.seen_fp = set(), set()
    m.results, m.filtered = [], []
    w1 = _w("汉中某小区烂尾了，交了钱不交房，业主走投无路，求扩散")
    w2 = _w("汉中某小区烂尾了！（文本略有不同）交了钱不交房，业主走投无路")
    w2.id = "1"  # 同 id 不同文本 → 只收一条
    assert m._add(w1)
    assert not m._add(w2)


# ── 本地模型融合逻辑（注入假打分器测试，不依赖真模型） ──

def test_model_refine_fusion():
    import analyzer, local_model
    ws = [
        _w("汉中天汉大道修了三年了还没修好，每天上班绕路，真的服了"),       # 词库漏报（无关键词）
        _w("汉中今天天气不错，去汉江边散步很舒服"),                          # 真中性
        _w("城固县这家店态度恶劣，乱收费，避雷"),                            # 词库判负、模型也判负 → 保持
        _w("汉中办事拖延？不存在的，今天去政务大厅体验特别好，点个赞"),      # 词库可能误报、模型判正 → 降级
    ]
    for w in ws:
        analyzer.analyze(w, HANZHONG)
    assert ws[0].sentiment_label == "中性"          # 词库确实漏了
    fake_scores = [0.97, 0.30, 0.95, 0.05]
    orig_st, orig_av = local_model.score_texts, local_model.available
    local_model.score_texts = lambda texts, **k: fake_scores[:len(texts)]
    local_model.available = lambda: True
    try:
        changed = analyzer.model_refine(ws)
    finally:
        local_model.score_texts, local_model.available = orig_st, orig_av
    assert ws[0].sentiment_label == "关注", "模型高置信负面应补上词库漏报"
    assert ws[0].model_score == 0.97
    assert ws[1].sentiment_label == "中性", "低置信不应干预"
    assert ws[2].sentiment_label in ("负面", "偏负面"), "两边一致时保持"
    if ws[3].sentiment_label in ("偏负面", "关注"):
        raise AssertionError("模型高置信正面应消除词库误报: " + ws[3].sentiment_label)
    assert changed >= 1


def test_model_unavailable_graceful():
    """transformer 未安装时降级到 lite 引擎；强负面词命中的结论不被降级"""
    import analyzer, local_model
    w = _w("汉中某小区烂尾，交了钱不交房，投诉无门求扩散")
    analyzer.analyze(w, HANZHONG)
    assert w.sentiment_label == "负面" and w.strong_neg
    orig = local_model.available
    local_model.available = lambda: False
    try:
        analyzer.model_refine([w])
    finally:
        local_model.available = orig
    assert w.sentiment_label == "负面", "有强负面词命中时任何引擎都不得降级"
    assert w.model_score is not None, "lite 引擎应已打分"


def test_lite_engine_end_to_end():
    """未安装 torch 时应自动降级到 lite 引擎并完成双向修正"""
    import analyzer, local_model
    ws = [
        _w("汉中天汉大道修了三年还没修好，每天绕路上班真的服了！！"),   # 词库漏报
        _w("问题已解决，感谢相关部门高效处理"),                          # 词库因'问题'可能误判
        _w("今天去汉江边散步，天气很舒服"),                              # 真中性
    ]
    for w in ws:
        analyzer.analyze(w, HANZHONG)
    orig = local_model.available
    local_model.available = lambda: False       # 模拟未装 torch
    try:
        analyzer.model_refine(ws)
    finally:
        local_model.available = orig
    assert ws[0].sentiment_label == "关注", (ws[0].sentiment_label, ws[0].model_score)
    assert ws[1].sentiment_label in ("中性", "正面"), (ws[1].sentiment_label, ws[1].model_score)
    assert ws[2].sentiment_label in ("中性", "正面")
    assert all(w.model_score is not None for w in ws)


def test_lite_scorer_directly():
    from lite_sentiment import score_texts
    s = score_texts(["小区电梯坏了半个月物业一直没人管，投诉了也白投诉",
                     "政务大厅办事效率很高，工作人员态度特别好，点赞"])
    assert s[0] > 0.75 and s[1] < 0.35, s


# ── 同名及歧义地名消歧 ──

from cities import BAOJI, XIAN, XIANYANG, YULIN


def test_shenzhen_xixiang_rejected():
    """深圳宝安西乡街道的投诉不应算作汉中西乡县"""
    for t in ("深圳西乡这边的中介太黑了，押金不退，投诉无门",
              "宝安西乡街道乱收费没人管，曝光一下",
              "南宁西乡塘区半夜施工扰民，投诉了也不处理"):
        assert not HANZHONG.match_regions(t), t


def test_hanzhong_xixiang_kept():
    """真·汉中西乡的帖子要保留，含异地打工提及老家的场景"""
    for t in ("西乡县樱桃沟的路修了三年还没修好，没人管吗",
              "汉中西乡的物业乱收费，向谁投诉",
              "在深圳打工，老家西乡县的宅基地被占了，投诉无门"):
        r = HANZHONG.match_regions(t)
        assert "西乡县" in r, (t, r)


def test_xian_changan_disambiguation():
    """长安汽车/长安街噪声排除，西安长安区保留"""
    assert not XIAN.match_regions("长安汽车4S店太坑了，避雷，强制消费")
    assert "长安区" in XIAN.match_regions("西安长安区的公交太难等了，投诉没用")
    assert "长安区" in XIAN.match_regions("长安区韦曲街道垃圾遍地没人管")


def test_ambiguous_region_aliases_require_local_anchor():
    """项目名、片区名等裸简称不能单独证明属于目标城市。"""
    cases = (
        (XIAN, "贵州省普安县东方新城项目拖欠80余名农民工工资"),
        (XIAN, "北京丰台区三环新城店服务太差，消费者投诉"),
        (BAOJI, "济宁太白湖新区购物广场烂尾多年无人处理"),
        (XIANYANG, "江西萍乡武功山景区乱收费，游客投诉"),
        (YULIN, "外地横山镇道路施工扰民，居民多次投诉"),
        (HANZHONG, "西乡这边物业乱收费，一直没人管"),
        (XIAN, "镇江焦山碑林石刻清幽，但景区服务太差"),
        (XIAN, "北国李未央称偶像遭到区别对待，要求曝光"),
        (XIAN, "蓝田玉商家拒绝退款，消费者投诉无门"),
        (BAOJI, "弱柳扶风造型翻车，假睫毛需要避雷"),
        (BAOJI, "这家岐山臊子面餐馆服务太差"),
        (XIANYANG, "显示器三原色异常，售后一直不处理"),
        (XIANYANG, "网店出售的淳化元宝疑似假货"),
        (YULIN, "京剧中的张定边足智多谋，表演精彩"),
    )
    for city, text in cases:
        assert not city.match_regions(text), (city.short, text)


def test_ambiguous_region_aliases_with_local_anchor_are_kept():
    """目标市、省或完整行政区名可确认歧义简称的属地。"""
    cases = (
        (XIAN, "西安航天新城项目停工，业主投诉无门", "西安市"),
        (XIAN, "航天新城星河九号多年烂尾，业主要求解决", "西安市"),
        (XIAN, "新城区某小区长期停水，居民多次反映", "新城区"),
        (BAOJI, "宝鸡太白一处工地拖欠工资", "太白县"),
        (BAOJI, "太白县某小区物业乱收费", "太白县"),
        (XIANYANG, "咸阳武功一企业长期拖欠工资", "武功县"),
        (YULIN, "榆林横山一煤矿拖欠工人工资", "横山区"),
        (HANZHONG, "汉中西乡的道路一直没人修", "西乡县"),
        (XIAN, "西安市未央区一小区长期停水", "未央区"),
        (XIAN, "碑林区一施工现场夜间噪音扰民", "碑林区"),
        (XIAN, "西安莲湖一商场存在消防隐患", "莲湖区"),
        (XIAN, "蓝田县某项目拖欠农民工工资", "蓝田县"),
        (BAOJI, "宝鸡金台一物业长期乱收费", "金台区"),
        (BAOJI, "扶风县某企业欠薪数月", "扶风县"),
        (XIANYANG, "咸阳三原一工地扬尘扰民", "三原县"),
        (XIANYANG, "淳化县某道路多年未维修", "淳化县"),
        (YULIN, "榆林定边一项目拖欠工程款", "定边县"),
    )
    for city, text, expected_region in cases:
        assert expected_region in city.match_regions(text), (city.short, text)


def test_guizhou_oriental_new_city_is_not_xian():
    text = (
        "贵州普安县东方新城项目超80名农民工被长期拖欠117.45万元工资。"
        "2021年1月至2022.5期间，袁国红等80余名农民工在该属地政府监管的城建项目务工，"
        "总计产生167.45万元欠薪，开发商仅支付50万元，剩余款项长期被拖欠。"
        "针对该事件，住建局与人社局存在违规审批分包问题，未要求总承包企业缴纳农民工工资保证金，"
        "住建局未落实实名制及分账管理要求，劳动监察大队履职不力且推诿卸责。"
    )
    assert not XIAN.match_regions(text)


def test_named_local_new_city_is_city_level_only():
    assert XIAN.match_regions("西安航天新城项目停工，业主投诉无门") == ["西安市"]


def test_explicit_external_place_conflicts_are_rejected():
    cases = (
        (XIAN, "黑龙江省牡丹江市西安区一饭店油烟扰民"),
        (XIAN, "呼和浩特市新城区某汽车店拒绝退款"),
        (XIAN, "石家庄市长安区一小区物业乱收费"),
        (YULIN, "甘肃敦煌榆林窟景区服务差，游客投诉"),
        (HANZHONG, "南京汉中路一家商场强制消费"),
        (XIAN, "西安网友转发：呼和浩特市新城区某汽车店拒绝退款"),
        (BAOJI, "陕西网友关注济宁太白湖新区项目烂尾"),
        (XIANYANG, "咸阳网友转发江西武功山景区投诉"),
        (HANZHONG, "汉中网友转发：深圳西乡中介押金不退"),
        (XIAN, "西安网友关注：东莞市长安区小区投诉"),
        (BAOJI, "宝鸡网友转发：山东岐山小区投诉"),
        (XIANYANG, "咸阳网友转发：外地渭城项目投诉"),
        (XIAN, "西安网友关注：北京丰台三环新城项目投诉"),
        (XIAN, "察县新城区某购物中心噪音扰民"),
        (XIAN, "韩城市新城区文秀园业主投诉"),
        (XIAN, "郑州市新城区某商场强制消费"),
        (XIAN, "河南省新城区某商场强制消费"),
        (HANZHONG, "南京市西乡县某小区物业投诉"),
        (HANZHONG, "四川省西乡县某小区物业投诉"),
        (XIAN, "西安网友转发：外地新城项目投诉"),
        (XIAN, "陕西省某地新城项目投诉"),
    )
    for city, text in cases:
        assert not city.match_regions(text), (city.short, text)


def test_mentions_alone_are_not_location_evidence():
    assert not XIAN.match_regions(
        "微众银行每天打骚扰电话，请停止联系 @西安网警 @广州网警 @深圳网警"
    )
    assert not XIAN.match_regions(
        "//@北国李未央:归还五代现top高铭阳，应当曝光区别对待"
    )


def test_mention_without_separator_does_not_hide_location():
    regions = XIAN.match_regions("@西安网警请关注西安市未央区某小区连续停水")
    assert "西安市" in regions
    assert "未央区" in regions


def test_external_reject_terms_ignore_spacing():
    assert not XIAN.match_regions("黑龙江省牡丹江市 西安区一饭店油烟扰民")
    assert not HANZHONG.match_regions("深圳市 宝安区 西乡街道乱收费")


def test_location_outside_mentions_is_still_kept():
    text = "@西安网警 请关注：西安市未央区某小区连续停水三天"
    regions = XIAN.match_regions(text)
    assert "西安市" in regions
    assert "未央区" in regions


def test_source_identity_is_not_a_city_anchor():
    assert not XIAN.match_regions("陕西网友关注：某地新城项目投诉")
    assert not XIAN.match_regions("西安市网友转发：呼和浩特市新城区某店投诉")
    regions = XIAN.match_regions("西安网友反映：西安市未央区某小区连续停水")
    assert "未央区" in regions


def test_city_names_inside_external_road_names_are_rejected():
    assert not XIAN.match_regions("大连西安路一家商场强制消费")
    assert not XIAN.match_regions("大连市西安区一家商场强制消费")
    assert not XIANYANG.match_regions("天津咸阳路小区物业不作为")
    assert not XIANYANG.match_regions("天津市咸阳路小区物业不作为")
    assert not HANZHONG.match_regions("南京汉中路一家商场强制消费")


def test_local_full_name_survives_external_reference():
    assert "未央区" in XIAN.match_regions(
        "西安市未央区小区停水，同时提及牡丹江市西安区"
    )
    assert "太白县" in BAOJI.match_regions(
        "宝鸡太白县小区投诉，同时对比济宁太白湖"
    )
    assert "武功县" in XIANYANG.match_regions(
        "咸阳武功县项目投诉，文中提及武功山旅游"
    )


def test_specific_conflict_does_not_block_real_dingbian_project():
    assert "定边县" in YULIN.match_regions(
        "我在定边项目部施工三个月，承包方一直拖欠工资"
    )
    assert not YULIN.match_regions("京剧人物张定边的故事引发关注")
    assert not YULIN.match_regions("施工方尚未确定边界，双方发生争议")
    assert "定边县" in YULIN.match_regions(
        "定边县施工方尚未确定边界，群众要求尽快处理"
    )


def test_disambiguation_configuration_uses_known_region_keywords():
    for city in (YULIN, HANZHONG, XIAN, BAOJI, XIANYANG):
        keywords = set(city.all_region_kw)
        assert set(city.deny) <= keywords
        assert set(city.anchor_required) <= keywords
        assert len(city.reject_terms) == len(set(city.reject_terms))
        assert all(city.anchor_required.values())
