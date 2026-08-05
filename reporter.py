"""reporter.py — 终端报告、文件保存与汇总数据整理。"""

from __future__ import annotations

import csv
import json
import logging
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import TZ
from keywords import LABEL_ICONS
from cities import City
from models import Weibo

log = logging.getLogger(__name__)

LABEL_COLORS = {
    "负面": "#c9362b",
    "偏负面": "#d97706",
    "关注": "#ca8a04",
    "中性": "#64748b",
    "正面": "#16845b",
}

CSV_FIELDS = ["time", "user", "user_type", "verified", "followers", "text",
              "sentiment_label", "sentiment_score", "model_score", "llm_reason", "regions",
              "strong_neg", "medium_neg", "mild_neg", "positive_ctx",
              "heat", "reposts", "comments", "likes", "is_new", "url", "keyword"]


def _region_stats(results: list[Weibo]) -> list[dict]:
    rs: dict[str, dict] = defaultdict(lambda: {"total": 0, "neg": 0})
    for w in results:
        for r in w.regions:
            rs[r]["total"] += 1
            if w.sentiment_label in ("负面", "偏负面"):
                rs[r]["neg"] += 1
    out = []
    for name, s in sorted(rs.items(), key=lambda x: x[1]["neg"], reverse=True):
        ratio = s["neg"] / s["total"] * 100 if s["total"] else 0
        color = "#e74c3c" if ratio > 30 else ("#f39c12" if ratio > 15 else "#2ecc71")
        out.append({"name": name, "total": s["total"], "neg": s["neg"],
                    "ratio": ratio, "color": color})
    return out


# ══════════════ 终端报告 ══════════════

def print_report(results: list[Weibo], new_negatives: list[Weibo],
                 filtered_count: int, health_summary: str) -> None:
    print("\n" + "▓" * 64)
    print("  📊 监测结果    采集健康度: {}".format(health_summary or "-"))
    print("▓" * 64)
    print(f"\n  个人微博总量: {len(results)}   新增负面/关注: {len(new_negatives)}   已过滤官方号: {filtered_count}")

    stats = _region_stats(results)
    if stats:
        print("\n  {:<10} {:>4} {:>4} {:>7}".format("区县", "总量", "负面", "占比"))
        print("  " + "─" * 34)
        for r in stats:
            flag = " 🔴" if r["ratio"] > 30 else (" 🟡" if r["ratio"] > 15 else "")
            print("  {:<10} {:>4} {:>4} {:>6.1f}%{}".format(
                r["name"], r["total"], r["neg"], r["ratio"], flag))

    lc: dict[str, int] = defaultdict(int)
    for w in results:
        lc[w.sentiment_label] += 1
    print("\n  情感分布:")
    for lb in ("负面", "偏负面", "关注", "中性", "正面"):
        c = lc.get(lb, 0)
        print("    {} {:<4} {:>4}  {}".format(LABEL_ICONS[lb], lb, c, "█" * min(c, 40)))

    if new_negatives:
        print("\n  🔴 新增负面（按严重度）:")
        for i, w in enumerate(sorted(new_negatives,
                                     key=lambda x: (x.sentiment_score, -x.heat)), 1):
            print("\n  ── [{}] {} {}  热度:{}".format(
                i, LABEL_ICONS.get(w.sentiment_label, ""), w.sentiment_label, w.heat))
            print("     👤 {} ({})  🕐 {}  📍 {}".format(
                w.user, w.user_type, w.time, "、".join(w.regions)))
            print("     📝 {}".format(w.text[:200] + ("…" if len(w.text) > 200 else "")))
            print("     🔗 {}".format(w.url))
    else:
        print("\n  ✅ 未发现新增的个人负面舆情")


# ══════════════ 文件保存 ══════════════

def save_files(city_short: str, results: list[Weibo], negatives: list[Weibo],
               filtered: list[dict], period: str, out_dir: str = ".") -> list[str]:
    ts = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
    files: list[str] = []

    def _csv(name: str, rows: list[Weibo]) -> None:
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
            wr.writeheader()
            for w in rows:
                row = w.to_dict()
                for k in ("regions", "strong_neg", "medium_neg", "mild_neg", "positive_ctx"):
                    row[k] = "、".join(row[k])
                wr.writerow(row)
        files.append(path)
        log.info("已保存 %s (%d 行)", path, len(rows))

    if results:
        _csv(f"{city_short}舆情_全部_{ts}.csv",
             sorted(results, key=lambda x: x.heat, reverse=True))
    if negatives:
        _csv(f"{city_short}舆情_负面_{ts}.csv",
             sorted(negatives, key=lambda x: x.sentiment_score))

    jpath = os.path.join(out_dir, f"{city_short}舆情_{ts}.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump({
            "period": period,
            "total_personal": len(results),
            "negative": len(negatives),
            "filtered_official": filtered,   # 含被过滤原文与原因，便于审计误杀
            "all": [w.to_dict() for w in results],
        }, f, ensure_ascii=False, indent=2)
    files.append(jpath)
    return files


def build_city_section(city: City, results: list[Weibo], new_negatives: list[Weibo],
                       old_negative_count: int, filtered_count: int,
                       health_summary: str, health_ok: bool) -> dict:
    """返回 Bark 汇总和存档所需的单城市统计。"""
    return {
        "city": city.short,
        "new_neg": len(new_negatives),
        "total": len(results),
        "old_neg": old_negative_count,
        "filtered": filtered_count,
        "health_summary": health_summary or "全部正常",
        "health_ok": health_ok,
        "region_stats": _region_stats(results),
        "new_negatives": sorted(
            new_negatives,
            key=lambda weibo: (weibo.sentiment_score, -weibo.heat),
        ),
    }


def _clean_personal_summary(weibo: Weibo) -> str:
    summary = (getattr(weibo, "summary", "") or weibo.text).lstrip("△").strip()
    if weibo.url and summary.endswith(weibo.url):
        summary = summary[:-len(weibo.url)].rstrip()
    return summary


def build_leader_summary_text(top_weibos: list) -> str:
    """生成领导要求的严格文本格式"""
    lines = []
    for w in top_weibos:
        # 如果大模型自己生成了△，这里用 lstrip('△') 给它去掉，防止变成双三角
        sum_text = _clean_personal_summary(w)
        lines.append(f"{sum_text}\n{w.url}" if w.url else sum_text)
    return "\n".join(lines)


_env = Environment(
    loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), "templates")),
    autoescape=select_autoescape(["html", "j2"]),
)


def build_digest_html(sections: list[dict], period: str, leader_text: str = "") -> str:
    """生成包含推荐候选、城市统计和明细的 HTML 邮件日报。"""
    template = _env.get_template("digest.html.j2")
    return template.render(
        period=period,
        generated_at=datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
        sections=sections,
        total_new_neg=sum(section.get("new_neg", 0) for section in sections),
        total_posts=sum(section.get("total", 0) for section in sections),
        healthy_count=sum(bool(section.get("health_ok", True)) for section in sections),
        any_unhealthy=any(not section.get("health_ok", True) for section in sections),
        leader_text=leader_text,
        recommendation_count=len(leader_text.splitlines()) if leader_text else 0,
        label_colors=LABEL_COLORS,
    )


def build_web_report_html(
    sections: list[dict],
    period: str,
    highlights: list[tuple[str, Weibo]],
) -> str:
    """Generate the GitHub Pages report with one-click copy controls."""
    recommendations = []
    for index, (city, weibo) in enumerate(highlights[:10], 1):
        summary = _clean_personal_summary(weibo)
        recommendations.append({
            "index": index,
            "city": city,
            "weibo": weibo,
            "summary": summary,
            "copy_text": f"{summary}\n{weibo.url}" if weibo.url else summary,
        })

    template = _env.get_template("web_report.html.j2")
    return template.render(
        period=period,
        generated_at=datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
        sections=sections,
        total_new_neg=sum(section.get("new_neg", 0) for section in sections),
        total_posts=sum(section.get("total", 0) for section in sections),
        healthy_count=sum(bool(section.get("health_ok", True)) for section in sections),
        any_unhealthy=any(not section.get("health_ok", True) for section in sections),
        recommendations=recommendations,
        label_colors=LABEL_COLORS,
    )


def save_web_report(html_content: str, out_dir: str = "public") -> str:
    """Save the fixed Pages entry point and return its path."""
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "latest.html"
    path.write_text(html_content, encoding="utf-8")
    (output_dir / "index.html").write_text(html_content, encoding="utf-8")
    log.info("已生成 GitHub Pages 日报 %s", path)
    return str(path)


def build_personal_report_payload(
    sections: list[dict],
    period: str,
    highlights: list[tuple[str, Weibo]],
    unsummarized_items: list[tuple[str, Weibo]] | None = None,
) -> dict:
    """Build the JSON contract consumed by the shared GitHub Pages dashboard."""
    recommendations = []
    for index, (city, weibo) in enumerate(highlights[:10], 1):
        summary = _clean_personal_summary(weibo)
        recommendations.append({
            "id": weibo.id,
            "index": index,
            "city": city,
            "label": weibo.sentiment_label,
            "region": "、".join(weibo.regions[:2]) or city,
            "heat": weibo.heat,
            "summary": summary,
            "user": weibo.user,
            "time": weibo.time,
            "url": weibo.url,
            "copy_text": f"{summary}\n{weibo.url}" if weibo.url else summary,
        })

    recommended_ids = {weibo.id for _, weibo in highlights[:10]}
    unsummarized = []
    for index, (city, weibo) in enumerate(unsummarized_items or [], 1):
        if weibo.id in recommended_ids:
            continue
        unsummarized.append({
            "id": weibo.id,
            "index": index,
            "city": city,
            "label": weibo.sentiment_label,
            "region": "、".join(weibo.regions[:2]) or city,
            "heat": weibo.heat,
            "text": weibo.text,
            "user": weibo.user,
            "time": weibo.time,
            "url": weibo.url,
            "copy_text": f"{weibo.text}\n{weibo.url}" if weibo.url else weibo.text,
        })

    return {
        "source": "personal",
        "updated_at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
        "period": period,
        "stats": {
            "new_neg": sum(section.get("new_neg", 0) for section in sections),
            "total_posts": sum(section.get("total", 0) for section in sections),
            "healthy": sum(bool(section.get("health_ok", True)) for section in sections),
            "city_count": len(sections),
        },
        "cities": [
            {
                "city": section.get("city", "-"),
                "new_neg": section.get("new_neg", 0),
                "total": section.get("total", 0),
                "health_ok": bool(section.get("health_ok", True)),
            }
            for section in sections
        ],
        "recommendations": recommendations,
        "unsummarized": unsummarized,
    }


def save_personal_report_json(
    payload: dict,
    path: str = "personal.json",
) -> str:
    """Write the personal-opinion payload for the shared Pages repository."""
    output_path = Path(path)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("已生成联合 Pages 数据 %s", output_path)
    return str(output_path)


def build_alert_html(reason: str, health_summary: str) -> str:
    """生成采集异常告警邮件。"""
    import html

    return (
        '<div style="background:#f4f5f7;padding:28px;font-family:-apple-system,'
        'BlinkMacSystemFont,Segoe UI,Microsoft YaHei,sans-serif;color:#20242c;">'
        '<div style="max-width:640px;margin:0 auto;background:#fff;border:1px solid '
        '#e4e7ec;border-radius:8px;overflow:hidden;">'
        '<div style="background:#292d35;color:#fff;padding:20px 24px;font-size:18px;">'
        '<b style="color:#ff786f;">采集异常</b> · 陕西舆情监测</div>'
        '<div style="padding:24px;line-height:1.75;">'
        f'<div style="font-size:16px;font-weight:600;">{html.escape(reason)}</div>'
        f'<p style="color:#667085;">接口状态：{html.escape(health_summary)}</p>'
        '<div style="border-left:3px solid #d63c32;padding:10px 14px;background:#fff5f4;'
        'color:#6b3030;">请优先检查 WEIBO_COOKIE 是否过期；也可能是接口限流或微博接口变更。</div>'
        "</div></div></div>"
    )
