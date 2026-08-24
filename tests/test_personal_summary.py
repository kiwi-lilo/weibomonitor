from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analyzer import llm_summarize
from config import DEFAULT_LLM_API_BASE, DEFAULT_LLM_MODEL, Settings
from models import Weibo


def test_personal_summary_keeps_format_and_retries_short_output(monkeypatch):
    source_text = (
        "2026年7月起，汉中某小区2栋共300户居民反映两部电梯频繁停运，"
        "其中一部已连续停运7个月。物业称正在联系维保单位，但截至发帖时仍未恢复，"
        "居民称老人上下楼不便，相关维修记录和处置进度尚未公开。"
    )
    weibo = Weibo(
        id="summary-1",
        user="普通居民",
        text=source_text,
        time="2026-08-04 09:00",
        url="https://weibo.com/summary-1",
        keyword="电梯",
        regions=["汉中", "汉台区"],
        reposts=3,
        comments=18,
        likes=25,
    )
    outputs = iter([
        "△汉中某小区电梯长期停运。物业正在联系维保单位。",
        (
            "△汉中某小区两栋住宅电梯长期停运，物业维保处置迟缓。"
            "2026年7月起，该小区2栋共300户居民持续反映两部电梯频繁停运，"
            "其中一部已连续停运7个月。物业表示正在联系维保单位，但截至发帖时设备仍未恢复运行，"
            "相关维修记录及具体处置进度尚未公开，事件反映出住宅公共设施维护衔接不畅。"
        ),
    ])
    requests = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": next(outputs)}}]}

    def fake_post(url, *, headers, timeout, json):
        requests.append({"url": url, "timeout": timeout, "json": json})
        return Response()

    monkeypatch.setattr("analyzer.requests.post", fake_post)
    settings = Settings(
        cookie="cookie",
        llm_api_base="https://llm.example.com/v1",
        llm_api_key="test-key",
        llm_model="test-model",
    )

    llm_summarize([weibo], settings)

    prompt = requests[0]["json"]["messages"][0]["content"]
    assert len(requests) == 2
    assert "文本最开头必须带有“△”符号" in prompt
    assert "必须采用纯粹的一段话形式输出" in prompt
    assert "不需要阐述事件的影响及群众诉求" in prompt
    assert "绝对不允许在文本中提出任何解决建议" in prompt
    assert "事发时间和具体地点" in prompt
    assert "不要机械写“信息来源为”" in prompt
    assert "转发3次" not in prompt
    assert "发布时间为" not in prompt
    assert f"原帖内容：{source_text}" in prompt
    assert "上一版不合格" in requests[1]["json"]["messages"][-1]["content"]
    assert weibo.summary.startswith("△")
    assert "300户" in weibo.summary
    assert "7个月" in weibo.summary
    assert "\n" not in weibo.summary


def test_personal_summary_retries_template_like_output(monkeypatch):
    source_text = (
        "西安市雁塔区某小区业主反映，楼顶违建多年未整改。近期连续降雨后，"
        "屋面出现严重积水，违建业主锁闭通道，物业无法进场清理。业主称此前多次举报，"
        "拆除仅涉及部分设施，屋面防水和排水系统受损，相关纠纷至今未彻底解决。"
    )
    weibo = Weibo(
        id="summary-template-1",
        user="业主观察",
        text=source_text,
        time="2026-08-04 09:00",
        url="https://weibo.com/summary-template-1",
        keyword="违建",
    )
    outputs = iter([
        (
            "△西安雁塔区某小区楼顶违建多年未整改，屋面积水问题仍待处理。"
            "信息来源为网络平台原帖。事件经过为业主反映，小区屋面违建长期存续，"
            "近期连续降雨后出现严重积水，违建业主锁闭通道，物业无法进场清理。"
            "争议或疑似原因在于此前拆除仅涉及部分设施，屋面防水和排水系统受损，"
            "群众反映及当前进展方面，相关纠纷至今未彻底解决。"
        ),
        (
            "△西安雁塔区某小区楼顶违建多年未整改，近期降雨后屋面积水且物业清理受阻。"
            "有业主反映，该小区屋面违建长期存续，连续降雨后出现严重积水，"
            "违建业主锁闭通道，物业无法进场清理。业主称此前曾多次举报，"
            "但拆除仅涉及部分设施，屋面防水和排水系统受损，相关纠纷至今未彻底解决。"
        ),
    ])
    requests = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": next(outputs)}}]}

    def fake_post(url, *, headers, timeout, json):
        requests.append(json)
        return Response()

    monkeypatch.setattr("analyzer.requests.post", fake_post)
    llm_summarize([weibo], Settings(cookie="cookie", llm_api_key="test-key"))

    assert len(requests) == 2
    assert requests[0]["model"] == DEFAULT_LLM_MODEL
    assert "模板化套话" in requests[1]["messages"][-1]["content"]
    assert weibo.summary.startswith("△")
    assert "信息来源为" not in weibo.summary
    assert "事件经过为" not in weibo.summary


def test_llm_settings_default_to_deepseek(monkeypatch):
    monkeypatch.delenv("LLM_API_BASE", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    settings = Settings(cookie="cookie", llm_api_key="test-key")

    assert settings.llm_api_base == DEFAULT_LLM_API_BASE
    assert settings.llm_model == DEFAULT_LLM_MODEL
    assert settings.llm_ready
