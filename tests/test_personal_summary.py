from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analyzer import llm_summarize
from config import DEFAULT_LLM_API_BASE, DEFAULT_LLM_MODEL, Settings
from models import Weibo


def test_llm_settings_default_to_deepseek(monkeypatch):
    monkeypatch.delenv("LLM_API_BASE", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    settings = Settings(cookie="cookie", llm_api_key="test-key")

    assert settings.llm_api_base == DEFAULT_LLM_API_BASE
    assert settings.llm_model == DEFAULT_LLM_MODEL
    assert settings.llm_ready


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
    assert "配图" in content[0]["text"]
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
