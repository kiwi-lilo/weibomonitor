"""reporter.py — 终端报告 + 文件保存 + HTML 邮件正文（Jinja2 自动转义）"""

from __future__ import annotations

import csv
import json
import logging
import os
from collections import defaultdict
from datetime import datetime

from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import TZ
from keywords import LABEL_ICONS, CITY_NAME, CITY_SHORT
from models import Weibo

log = logging.getLogger(__name__)

LABEL_COLORS = {"负面": "#e74c3c", "偏负面": "#e67e22", "关注": "#f1c40f",
                "中性": "#95a5a6", "正面": "#2ecc71"}

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

def save_files(results: list[Weibo], negatives: list[Weibo],
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
        _csv(f"{CITY_SHORT}舆情_全部_{ts}.csv",
             sorted(results, key=lambda x: x.heat, reverse=True))
    if negatives:
        _csv(f"{CITY_SHORT}舆情_负面_{ts}.csv",
             sorted(negatives, key=lambda x: x.sentiment_score))

    jpath = os.path.join(out_dir, f"{CITY_SHORT}舆情_{ts}.json")
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


# ══════════════ HTML 报告 ══════════════

_env = Environment(
    loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), "templates")),
    autoescape=select_autoescape(["html", "j2"]),
)


def build_html_report(results: list[Weibo], new_negatives: list[Weibo],
                      old_negative_count: int, filtered_count: int,
                      period: str, health_summary: str, health_ok: bool) -> str:
    tpl = _env.get_template("report.html.j2")
    return tpl.render(
        city_name=CITY_NAME,
        period=period,
        generated_at=datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
        results=results,
        new_negatives=sorted(new_negatives, key=lambda x: (x.sentiment_score, -x.heat)),
        old_negative_count=old_negative_count,
        filtered_count=filtered_count,
        region_stats=_region_stats(results),
        label_colors=LABEL_COLORS,
        health_summary=health_summary or "全部正常",
        health_ok=health_ok,
    )


def build_alert_html(reason: str, health_summary: str) -> str:
    """采集异常告警邮件（简单内联，无需模板）"""
    import html
    return (
        '<div style="font-family:sans-serif;max-width:640px;margin:0 auto;">'
        '<div style="background:#c0392b;color:#fff;padding:16px 20px;border-radius:8px 8px 0 0;">'
        "<b>⚠️ 舆情监测采集异常</b></div>"
        '<div style="background:#fff;border:1px solid #eee;padding:16px 20px;">'
        f"<p>{html.escape(reason)}</p>"
        f"<p style='color:#888;font-size:13px;'>接口状态：{html.escape(health_summary)}</p>"
        "<p style='color:#888;font-size:13px;'>常见原因：WEIBO_COOKIE 过期（请重新抓取并更新 "
        "GitHub Secrets）、触发风控限流、微博接口改版。</p>"
        "</div></div>"
    )
