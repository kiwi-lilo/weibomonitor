from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analyzer import llm_summarize
from config import Settings
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
    assert "转发3次" not in prompt
    assert "发布时间为" not in prompt
    assert f"原帖内容：{source_text}" in prompt
    assert "上一版不合格" in requests[1]["json"]["messages"][-1]["content"]
    assert weibo.summary.startswith("△")
    assert "300户" in weibo.summary
    assert "7个月" in weibo.summary
    assert "\n" not in weibo.summary
