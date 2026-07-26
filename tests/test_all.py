"""针对上一版实际踩过的坑写的回归测试。运行：pytest tests/ -v"""

from __future__ import annotations

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import TZ
from wb_parser import parse_time, within_days, clean_text
from analyzer import analyze, is_official
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
    analyze(w)
    assert w.sentiment_label in ("中性", "正面"), w.sentiment_label


def test_enforcement_news_not_negative():
    """警方整治新闻含'黑恶势力'不应判负面（正面语境否决）"""
    w = _w("汉中警方开展扫黑除恶专项行动，严厉打击黑恶势力，专项整治取得成效，市民纷纷点赞")
    analyze(w)
    assert w.sentiment_label != "负面", (w.sentiment_label, w.strong_neg, w.positive_ctx)


def test_real_complaint_is_negative():
    w = _w("汉中某小区烂尾三年，我们交了钱不交房，血汗钱打了水漂，投诉无门，没人管，求扩散！")
    analyze(w)
    assert w.sentiment_label == "负面"
    assert w.strong_neg


def test_medium_complaint():
    w = _w("城固县政务大厅办事难，工作人员态度恶劣，来回踢皮球")
    analyze(w)
    assert w.sentiment_label in ("负面", "偏负面")


def test_region_tagging():
    w = _w("南郑区某小区烂尾了，交了钱不交房，业主走投无路")
    analyze(w)
    assert "南郑区" in w.regions


# ── 官方号过滤 ──

def test_blue_v_filtered():
    w = _w("正常内容正常内容", user="某某机构号", verified=True, verified_type=3)
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


# ── 去重 ──

def test_dedup_by_id():
    from main import Monitor
    from config import Settings
    m = Monitor.__new__(Monitor)
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
        analyzer.analyze(w)
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
    analyzer.analyze(w)
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
        analyzer.analyze(w)
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
