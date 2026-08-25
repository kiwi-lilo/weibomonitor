from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analyzer import _clean_summary, llm_summarize
from config import DEFAULT_LLM_API_BASE, DEFAULT_LLM_MODEL, Settings
from models import Weibo


def test_personal_summary_accepts_single_model_output(monkeypatch):
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
    assert len(requests) == 1
    assert requests[0]["timeout"] == 60
    assert "文本必须以“△”开头" in prompt
    assert "政策类突出执行落差" in prompt
    assert "地区或核心对象＋具体问题＋关键影响或状态" in prompt
    assert "通常控制在20至45字" in prompt
    assert "不得只写“存在问题”“引发关注”“引发质疑”" in prompt
    assert "专有名词、图片文字说明、现场细节" in prompt
    assert "原文提出的建议可以转述" in prompt
    assert "原文没有的信息直接省略" in prompt
    assert "通常写180至260字；信息丰富时可适当延长" in prompt
    assert "尚待核实" not in prompt
    assert "绝对不允许在文本中提出任何解决建议" not in prompt
    assert "转发3次" not in prompt
    assert "发布时间为" not in prompt
    assert f"原帖内容：{source_text}" in prompt
    assert weibo.summary.startswith("△")
    assert "\n" not in weibo.summary


def test_personal_summary_does_not_locally_rewrite_model_output(monkeypatch):
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
            "△西安雁塔区某小区楼顶违建多年未整改，近期降雨后屋面积水且物业清理受阻。"
            "有业主反映，该小区屋面违建长期存续，连续降雨后出现严重积水，"
            "违建业主锁闭通道，物业无法进场清理。业主称此前曾多次举报，"
            "但拆除仅涉及部分设施，屋面防水和排水系统受损。"
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

    assert len(requests) == 1
    assert requests[0]["model"] == DEFAULT_LLM_MODEL
    assert weibo.summary.startswith("△")
    assert "信息来源为" not in weibo.summary
    assert "争议或疑似原因" not in weibo.summary
    assert "材料未提及" not in weibo.summary
    assert "截至材料所述时间，尚无明确处置结果" not in weibo.summary


def test_llm_settings_default_to_deepseek(monkeypatch):
    monkeypatch.delenv("LLM_API_BASE", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    settings = Settings(cookie="cookie", llm_api_key="test-key")

    assert settings.llm_api_base == DEFAULT_LLM_API_BASE
    assert settings.llm_model == DEFAULT_LLM_MODEL
    assert settings.llm_ready


def test_summary_removes_verification_disclaimer_templates():
    assert _clean_summary(
        "△西安地铁5号线站名翻译问题引发质疑。目前，相关方面尚未公开回应。"
    ) == "△西安地铁5号线站名翻译问题引发质疑。"
    assert _clean_summary("△榆林游客反映深夜噪音扰民。前述情况尚待核实。") == (
        "△榆林游客反映深夜噪音扰民。"
    )
    assert _clean_summary(
        "△定边13岁少年被指遭公职人员殴打。"
        "截至当前，上述网络帖文内容尚未获得有关官方证实，相关情况尚待官方进一步核实。"
    ) == "△定边13岁少年被指遭公职人员殴打。"
    assert _clean_summary(
        "△定边一男孩被指遭民警掌掴。涉事二人被处以行政拘留十日，"
        "有关说法尚未获官方证实，仍有待进一步核实。"
    ) == "△定边一男孩被指遭民警掌掴。涉事二人被处以行政拘留十日。"


def test_personal_summary_sends_weibo_images_to_vision_model(monkeypatch):
    weibo = Weibo(
        id="summary-with-images",
        user="地铁观察",
        text="西安地铁5号线多个站名翻译不当，具体情况见配图。",
        time="2026-08-25 09:00",
        url="https://weibo.com/summary-with-images",
        keyword="地铁",
        image_urls=["https://img.example.com/one.jpg", "https://img.example.com/two.jpg"],
    )
    requests = []

    class Response:
        ok = True
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "△西安地铁5号线部分站名翻译不规范。配图显示多个站名仅使用拼音。"}}]}

    def fake_post(url, *, headers, timeout, json):
        requests.append(json)
        return Response()

    monkeypatch.setattr("analyzer.requests.post", fake_post)
    llm_summarize(
        [weibo],
        Settings(
            cookie="cookie",
            llm_api_key="test-key",
            llm_model="text-model",
            llm_vision_model="vision-model",
        ),
    )

    assert len(requests) == 1
    assert requests[0]["model"] == "vision-model"
    content = requests[0]["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert "随附图片" in content[0]["text"]
    assert [part["image_url"]["url"] for part in content[1:]] == weibo.image_urls


def test_personal_summary_falls_back_when_vision_model_rejects_images(monkeypatch):
    weibo = Weibo(
        id="vision-fallback",
        user="普通用户",
        text="某公共设施存在问题，详细情况见图片说明。",
        time="2026-08-25 09:00",
        url="https://weibo.com/vision-fallback",
        keyword="设施",
        image_urls=["https://img.example.com/evidence.jpg"],
    )
    requests = []

    class Response:
        status_code = 400

        def __init__(self, ok):
            self.ok = ok
            if ok:
                self.status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "△某公共设施被反映存在问题。网民通过图片说明有关情况。"}}]}

    def fake_post(url, *, headers, timeout, json):
        requests.append(json.copy())
        return Response(ok=len(requests) > 1)

    monkeypatch.setattr("analyzer.requests.post", fake_post)
    llm_summarize(
        [weibo],
        Settings(
            cookie="cookie",
            llm_api_key="test-key",
            llm_model="text-model",
            llm_vision_model="vision-model",
        ),
    )

    assert [request["model"] for request in requests] == ["vision-model", "text-model"]
    assert isinstance(requests[0]["messages"][0]["content"], list)
    assert isinstance(requests[1]["messages"][0]["content"], str)
