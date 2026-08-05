"""Bark 推送客户端与移动端日报排版。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import requests

from config import Settings
from models import Weibo

log = logging.getLogger(__name__)

MAX_RECOMMENDATIONS = 10
RECOMMENDATIONS_PER_MESSAGE = 5


@dataclass(frozen=True)
class BarkMessage:
    title: str
    body: str
    subtitle: str = ""
    level: str = "active"
    url: str = ""


def _compact(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + "…"


def _recommendation_lines(
    highlights: list[tuple[str, Weibo]], start_index: int
) -> list[str]:
    lines: list[str] = []
    for index, (city, weibo) in enumerate(highlights, start_index):
        summary = (getattr(weibo, "summary", "") or weibo.text).lstrip("△").strip()
        region = "、".join(weibo.regions[:2]) or city
        lines.append(
            f"{index:02d}｜{city} · {weibo.sentiment_label} · {region} · 热度 {weibo.heat}"
        )
        lines.append(f"{summary}\n{weibo.url}" if weibo.url else summary)
        lines.append("")
    if lines:
        lines.pop()
    return lines


def build_digest_messages(
    sections: list[dict],
    period: str,
    highlights: list[tuple[str, Weibo]],
    run_url: str = "",
) -> list[BarkMessage]:
    """生成最多两条汇总通知，每条放 5 条完整推荐。"""
    highlights = highlights[:MAX_RECOMMENDATIONS]
    total_new = sum(section.get("new_neg", 0) for section in sections)
    total_posts = sum(section.get("total", 0) for section in sections)
    healthy_count = sum(bool(section.get("health_ok", True)) for section in sections)
    any_unhealthy = healthy_count != len(sections)

    if total_new:
        title = f"🔴 陕西舆情日报｜新增 {total_new} 条"
        level = "timeSensitive"
    elif any_unhealthy:
        title = "⚠️ 陕西舆情日报｜采集状态异常"
        level = "timeSensitive"
    else:
        title = "✅ 陕西舆情日报｜今日平稳"
        level = "passive"

    city_stats = " · ".join(
        f"{section.get('city', '-')} {section.get('new_neg', 0)}"
        for section in sections
    ) or "暂无城市数据"
    health_icon = "✅" if not any_unhealthy else "⚠️"

    lines = [
        "📊 今日总览",
        f"新增关注 {total_new} 条｜采集微博 {total_posts} 条",
        city_stats,
        f"{health_icon} 采集健康 {healthy_count}/{len(sections)}",
    ]

    first_batch = highlights[:RECOMMENDATIONS_PER_MESSAGE]
    if first_batch:
        lines.extend(
            [
                "",
                f"📌 今日推荐候选 1–{len(first_batch)}",
                "点击通知展开完整内容",
                "",
            ]
        )
        lines.extend(_recommendation_lines(first_batch, 1))
    elif total_new == 0:
        lines.extend(["", "未发现新增个人负面舆情。"])

    lines.extend(["", "完整 HTML 日报及附件已同步发送至邮箱。"])
    subtitle = period.replace(" ~ ", " 至 ")
    messages = [
        BarkMessage(
            title=title,
            subtitle=subtitle,
            body="\n".join(lines),
            level=level,
            url="" if first_batch else run_url,
        )
    ]

    remaining = highlights[RECOMMENDATIONS_PER_MESSAGE:]
    if remaining:
        start = RECOMMENDATIONS_PER_MESSAGE + 1
        end = start + len(remaining) - 1
        messages.append(
            BarkMessage(
                title=f"📌 今日推荐候选 {start}–{end}",
                subtitle="点击通知展开完整内容",
                body="\n".join(_recommendation_lines(remaining, start)),
                level="active",
                url="",
            )
        )
    return messages


def build_alert_message(reason: str, run_url: str = "") -> BarkMessage:
    return BarkMessage(
        title="⚠️ 舆情监测采集异常",
        subtitle="本轮任务已中止",
        body=(
            f"异常原因\n{_compact(reason, 240)}\n\n"
            "请优先检查 WEIBO_COOKIE 是否过期；也可能是接口限流或微博接口变更。"
        ),
        level="timeSensitive",
        url=run_url,
    )


def send_bark(settings: Settings, message: BarkMessage) -> bool:
    if not settings.bark_ready:
        log.warning("Bark 配置不完整，跳过推送")
        return False

    payload = {
        "title": message.title,
        "subtitle": message.subtitle,
        "body": message.body,
        "group": settings.bark_group,
        "level": message.level,
    }
    if settings.bark_icon:
        payload["icon"] = settings.bark_icon
    if message.url:
        payload["url"] = message.url

    try:
        response = requests.post(settings.bark_url, json=payload, timeout=(5, 20))
        response.raise_for_status()
        try:
            result = response.json()
        except ValueError:
            result = {}
        if result.get("code", 200) != 200:
            log.error("Bark 服务拒绝推送（code=%s）", result.get("code"))
            return False
        log.info("Bark 推送成功：%s", message.title)
        return True
    except requests.RequestException as exc:
        # Bark URL 含设备 Key，异常日志只保留类型，避免泄露凭据。
        log.error("Bark 推送失败：网络请求异常（%s）", type(exc).__name__)
        return False
