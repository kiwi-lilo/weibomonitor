"""企业微信机器人通知：使用原生 Markdown 做移动端友好的日报排版。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
import requests

from config import Settings
from models import Weibo

log = logging.getLogger(__name__)

MAX_RECOMMENDATIONS = 10
PER_MESSAGE = 5
MESSAGE_BODY_BUDGET_BYTES = 3100


@dataclass(frozen=True)
class WeComMessage:
    content: str


def _compact(text: str, limit: int = 110) -> str:
    text = re.sub(r"\s+", " ", text or "").strip().lstrip("△").strip()
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + "…"


def _full_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lstrip("△").strip()


def _overview(sections: list[dict], period: str, prefix: str = "") -> list[str]:
    total_new = sum(section.get("new_neg", 0) for section in sections)
    total_posts = sum(section.get("total", 0) for section in sections)
    healthy = sum(bool(section.get("health_ok", True)) for section in sections)
    city_stats = "  ".join(
        f"`{section.get('city', '-')}` {section.get('new_neg', 0)} 条"
        for section in sections
    ) or "暂无城市数据"
    health_color = "info" if healthy == len(sections) else "warning"
    lines = [
        "## <font color=\"info\">陕西舆情日报</font>",
        f"> **监测周期：**{period}",
        (
            f"> **新增关注：**<font color=\"{'warning' if total_new else 'info'}\">"
            f"{total_new} 条</font>　**采集微博：**{total_posts} 条　"
            f"**采集健康：**<font color=\"{health_color}\">{healthy}/{len(sections)}</font>"
        ),
        f"> **城市分布：**{city_stats}",
    ]
    if prefix:
        lines.extend(["", prefix])
    return lines


def _candidate_markdown(city: str, weibo: Weibo, index: int) -> str:
    region = "、".join(weibo.regions[:2]) or city
    label_color = "warning" if weibo.sentiment_label in ("负面", "偏负面") else "comment"
    lines = [
        f"**{index:02d}｜{city} · <font color=\"{label_color}\">{weibo.sentiment_label}</font> · {region} · 热度 {weibo.heat}**",
        f"> △{_full_text(getattr(weibo, 'summary', '') or weibo.text)}",
    ]
    if weibo.url:
        lines.append(f"> [查看原微博]({weibo.url})　@{_compact(weibo.user, 18)}")
    else:
        lines.append(f"> @{_compact(weibo.user, 18)}")
    return "\n".join(lines)


def build_digest_messages(
    sections: list[dict],
    period: str,
    highlights: list[tuple[str, Weibo]],
    run_url: str = "",
    report_url: str = "",
) -> list[WeComMessage]:
    highlights = highlights[:MAX_RECOMMENDATIONS]
    total_new = sum(section.get("new_neg", 0) for section in sections)
    messages: list[WeComMessage] = []

    if report_url:
        lines = _overview(sections, period)
        if highlights:
            lines.extend([
                "",
                (
                    "### <font color=\"warning\">"
                    f"今日推荐候选 {len(highlights)} 条</font>"
                ),
                f"> [打开今日舆情清单]({report_url})",
                "> 每条内容可在页面中单独复制。",
            ])
        else:
            lines.extend([
                "",
                "### <font color=\"info\">今日结论</font>",
                "> 未发现新增个人负面舆情。",
                f"> [查看今日日报]({report_url})",
            ])
        return [WeComMessage("\n".join(lines))]

    if not highlights:
        lines = _overview(sections, period)
        lines.extend([
            "",
            "### <font color=\"info\">今日结论</font>",
            "> 未发现新增个人负面舆情。",
            "",
            "<font color=\"comment\">完整 HTML 日报及附件已同步发送至邮箱。</font>",
        ])
        return [WeComMessage("\n".join(lines))]

    batches: list[list[tuple[int, str, Weibo]]] = []
    current: list[tuple[int, str, Weibo]] = []
    for index, (city, weibo) in enumerate(highlights, 1):
        candidate = (index, city, weibo)
        trial = current + [candidate]
        trial_body = "\n\n".join(
            _candidate_markdown(item_city, item_weibo, item_index)
            for item_index, item_city, item_weibo in trial
        )
        if current and (
            len(current) >= PER_MESSAGE
            or len(trial_body.encode("utf-8")) > MESSAGE_BODY_BUDGET_BYTES
        ):
            batches.append(current)
            current = [candidate]
        else:
            current = trial
    if current:
        batches.append(current)

    for page, batch in enumerate(batches):
        start, end = batch[0][0], batch[-1][0]
        heading = (
            f"### <font color=\"warning\">今日推荐候选 {start:02d}–{end:02d}</font>\n"
            "> 选择需要转发的条目，点击链接查看原文。"
        )
        if page == 0:
            lines = _overview(sections, period, heading)
        else:
            lines = [
                "## <font color=\"info\">陕西舆情日报 · 推荐续页</font>",
                f"> **监测周期：**{period}",
                "",
                heading,
            ]
        lines.extend(["", "\n\n".join(
            _candidate_markdown(city, weibo, index)
            for index, city, weibo in batch
        )])
        lines.extend([
            "",
            "<font color=\"comment\">完整 HTML 日报及附件已同步发送至邮箱。</font>",
        ])
        messages.append(WeComMessage("\n".join(lines)))
    return messages


def build_alert_message(reason: str) -> WeComMessage:
    return WeComMessage(
        "\n".join([
            "## <font color=\"warning\">舆情监测采集异常</font>",
            "> **本轮任务已中止**",
            f"> **异常原因：**{_compact(reason, 220)}",
            "",
            "> 请检查微博 Cookie、接口限流和运行日志。",
        ])
    )


def send_wecom(settings: Settings, message: WeComMessage) -> bool:
    if not settings.wecom_ready:
        log.warning("企业微信机器人未配置，跳过推送")
        return False
    payload = {
        "msgtype": "markdown",
        "markdown": {"content": message.content},
    }
    try:
        response = requests.post(
            settings.wecom_webhook,
            json=payload,
            timeout=(5, 20),
        )
        response.raise_for_status()
        result = response.json()
        if result.get("errcode", 0) != 0:
            log.error("企业微信机器人拒绝推送（errcode=%s）", result.get("errcode"))
            return False
        log.info("企业微信推送成功")
        return True
    except (requests.RequestException, ValueError) as exc:
        log.error("企业微信推送失败（%s）", type(exc).__name__)
        return False
