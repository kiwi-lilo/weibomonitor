from __future__ import annotations

"""
reporter.py — 终端报告 + CSV/JSON保存 + HTML邮件报告
"""

import csv
import json
from datetime import datetime
from collections import defaultdict

from config import REGIONS, LABEL_ICONS


# ══════════════════════════════════════════════
#  终端报告
# ══════════════════════════════════════════════

def print_report(results, negatives, filtered):
    # type: (list, list, int) -> None
    """打印完整监测报告"""

    print("\n" + "▓" * 65)
    print("  📊  监测结果")
    print("▓" * 65)
    print("\n  个人发布微博: {} 条".format(len(results)))
    print("  负面/关注:    {} 条".format(len(negatives)))
    print("  已过滤官方号: {} 条".format(filtered))

    # 区县分布
    rs = defaultdict(lambda: {"t": 0, "n": 0})
    for w in results:
        for r in w.get("regions", []):
            rs[r]["t"] += 1
            if w["sentiment_label"] in ("负面", "偏负面"):
                rs[r]["n"] += 1
    if rs:
        print("\n  {:<10} {:>5} {:>5} {:>7}".format("区县", "总量", "负面", "占比"))
        print("  " + "─" * 35)
        for r, s in sorted(rs.items(), key=lambda x: x[1]["n"], reverse=True):
            ratio = s["n"] / s["t"] * 100 if s["t"] else 0
            flag = " 🔴" if ratio > 30 else (" 🟡" if ratio > 15 else "")
            print("  {:<10} {:>5} {:>5} {:>6.1f}%{}".format(r, s["t"], s["n"], ratio, flag))

    # 情感分布
    lc = defaultdict(int)
    for w in results:
        lc[w["sentiment_label"]] += 1
    print("\n  情感分布:")
    for lb in ["负面", "偏负面", "关注", "中性", "正面"]:
        c = lc.get(lb, 0)
        print("    {} {:<6} {:>4}  {}".format(LABEL_ICONS[lb], lb, c, "█" * min(c, 50)))

    # 负面详情
    print("\n" + "▓" * 65)
    print("  🔴  负面信息（仅个人发布）")
    print("▓" * 65)

    if not negatives:
        print("\n  ✅ 最近2天未发现个人发布的明显负面舆情。\n")
    else:
        sorted_neg = sorted(negatives, key=lambda x: (x["sentiment_score"], -x.get("heat", 0)))
        for i, w in enumerate(sorted_neg, 1):
            ic = {"负面": "🔴", "偏负面": "🟠", "关注": "🟡"}.get(w["sentiment_label"], "⚪")
            print("\n" + "─" * 58)
            print("  {} [{}] {}  分:{:.2f}  热度:{}".format(
                ic, i, w["sentiment_label"], w["sentiment_score"], w.get("heat", 0)))
            print("  👤 {} ({})  粉丝:{}".format(
                w["user"], w.get("user_type", "普通"), w.get("followers", "?")))
            print("  🕐 {}".format(w["time"]))
            print("  📍 {}".format(", ".join(w.get("regions", []))))
            print("  🔗 {}".format(w["url"]))

            txt = w["text"][:400]
            if len(w["text"]) > 400:
                txt += "..."
            print("  📝 {}".format(txt))

            tags = []
            if w.get("strong_neg"):
                tags.append("🔴强负面:[{}]".format(", ".join(w["strong_neg"])))
            if w.get("medium_neg"):
                tags.append("🟠中负面:[{}]".format(", ".join(w["medium_neg"])))
            if w.get("mild_neg"):
                tags.append("🟡轻负面:[{}]".format(", ".join(w["mild_neg"])))
            if tags:
                print("  🏷️  {}".format("  ".join(tags)))
            print("  💬 转发:{} 评论:{} 赞:{}".format(w["reposts"], w["comments"], w["likes"]))

    # 全部列表前50
    if results:
        print("\n" + "▓" * 65)
        print("  📋  全部个人微博（前50条，按热度排序）")
        print("▓" * 65 + "\n")
        sorted_all = sorted(results, key=lambda x: x.get("heat", 0), reverse=True)
        for i, w in enumerate(sorted_all[:50], 1):
            ic = LABEL_ICONS.get(w["sentiment_label"], "⚪")
            short = w["text"][:60].replace("\n", " ")
            if len(w["text"]) > 60:
                short += "…"
            utype = "V" if w.get("verified") else " "
            print("  {} {:>3}. [{}] [{}]@{:<8} {}".format(
                ic, i, w["time"][:16], utype, w["user"][:8], short))


# ══════════════════════════════════════════════
#  文件保存
# ══════════════════════════════════════════════

FIELDS = [
    "time", "user", "user_type", "verified", "text",
    "sentiment_label", "sentiment_score",
    "regions", "strong_neg", "medium_neg", "mild_neg",
    "heat", "reposts", "comments", "likes", "url", "keyword",
]


def save_files(results, negatives, filtered, today, two_days_ago):
    # type: (list, list, int, str, str) -> list
    """保存 CSV + JSON，返回文件路径列表"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    files = []

    if results:
        fn = "汉中舆情_个人_{}.csv".format(ts)
        _write_csv(fn, sorted(results, key=lambda x: x.get("heat", 0), reverse=True))
        print("\n📁 全部: {}".format(fn))
        files.append(fn)

    if negatives:
        fn = "汉中舆情_负面_{}.csv".format(ts)
        _write_csv(fn, sorted(negatives, key=lambda x: x["sentiment_score"]))
        print("📁 负面: {}".format(fn))
        files.append(fn)

    fn = "汉中舆情_{}.json".format(ts)
    with open(fn, "w", encoding="utf-8") as f:
        json.dump({
            "period": "{} ~ {}".format(two_days_ago, today),
            "total_personal": len(results),
            "negative": len(negatives),
            "filtered_official": filtered,
            "all": results,
            "neg": negatives,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("📁 JSON: {}".format(fn))
    files.append(fn)

    return files


def _write_csv(filename, data):
    # type: (str, list) -> None
    with open(filename, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=FIELDS)
        wr.writeheader()
        for w in data:
            row = {}
            for k in FIELDS:
                row[k] = w.get(k, "")
            for k in ("regions", "strong_neg", "medium_neg", "mild_neg", "positive_ctx"):
                if k in row and isinstance(row[k], list):
                    row[k] = ", ".join(row[k])
            wr.writerow(row)


# ══════════════════════════════════════════════
#  HTML邮件报告
# ══════════════════════════════════════════════

def build_html_report(results, negatives, filtered, today, two_days_ago):
    # type: (list, list, int, str, str) -> str
    """生成HTML格式邮件正文"""

    # 区县统计
    rs = defaultdict(lambda: {"t": 0, "n": 0})
    for w in results:
        for r in w.get("regions", []):
            rs[r]["t"] += 1
            if w["sentiment_label"] in ("负面", "偏负面"):
                rs[r]["n"] += 1

    region_rows = ""
    for r, s in sorted(rs.items(), key=lambda x: x[1]["n"], reverse=True):
        ratio = s["n"] / s["t"] * 100 if s["t"] else 0
        if ratio > 30:
            color = "#e74c3c"
        elif ratio > 15:
            color = "#f39c12"
        else:
            color = "#2ecc71"
        region_rows += """
        <tr>
            <td style="padding:6px 10px">{}</td>
            <td align="center">{}</td>
            <td align="center" style="color:{};font-weight:bold">{}</td>
            <td align="center">{:.1f}%</td>
        </tr>""".format(r, s["t"], color, s["n"], ratio)

    # 情感统计
    lc = defaultdict(int)
    for w in results:
        lc[w["sentiment_label"]] += 1

    color_map = {
        "负面": "#e74c3c", "偏负面": "#e67e22", "关注": "#f1c40f",
        "中性": "#95a5a6", "正面": "#2ecc71",
    }
    sentiment_rows = ""
    for lb in ["负面", "偏负面", "关注", "中性", "正面"]:
        c = lc.get(lb, 0)
        sentiment_rows += """
        <tr>
            <td style="padding:4px 10px"><span style="color:{}">●</span> {}</td>
            <td align="center">{}</td>
        </tr>""".format(color_map[lb], lb, c)

    # 负面详情
    neg_html = ""
    if not negatives:
        neg_html = (
            '<p style="color:#2ecc71;font-size:16px;text-align:center;padding:20px;">'
            '✅ 最近2天未发现个人发布的明显负面舆情</p>'
        )
    else:
        sorted_neg = sorted(negatives, key=lambda x: (x["sentiment_score"], -x.get("heat", 0)))
        for i, w in enumerate(sorted_neg, 1):
            label_color = {
                "负面": "#e74c3c", "偏负面": "#e67e22", "关注": "#f1c40f",
            }.get(w["sentiment_label"], "#95a5a6")

            tag_html = ""
            if w.get("strong_neg"):
                tag_html += (
                    '<span style="background:#e74c3c;color:#fff;padding:2px 6px;'
                    'border-radius:3px;font-size:12px;margin-right:4px;">'
                    '强负面: {}</span>'.format(", ".join(w["strong_neg"]))
                )
            if w.get("medium_neg"):
                tag_html += (
                    '<span style="background:#e67e22;color:#fff;padding:2px 6px;'
                    'border-radius:3px;font-size:12px;margin-right:4px;">'
                    '中负面: {}</span>'.format(", ".join(w["medium_neg"]))
                )
            if w.get("mild_neg"):
                tag_html += (
                    '<span style="background:#f1c40f;color:#333;padding:2px 6px;'
                    'border-radius:3px;font-size:12px;">'
                    '轻负面: {}</span>'.format(", ".join(w["mild_neg"]))
                )

            txt = w["text"][:300]
            if len(w["text"]) > 300:
                txt += "..."

            neg_html += """
            <div style="border-left:4px solid {label_color};padding:12px 16px;
                        margin:12px 0;background:#fafafa;border-radius:0 6px 6px 0;">
                <div style="margin-bottom:8px;">
                    <span style="background:{label_color};color:#fff;padding:3px 10px;
                                 border-radius:12px;font-size:13px;font-weight:bold;">
                        #{idx} {label}
                    </span>
                    <span style="color:#888;font-size:12px;margin-left:10px;">
                        热度:{heat} | 分数:{score:.2f}
                    </span>
                </div>
                <div style="font-size:13px;color:#666;margin-bottom:6px;">
                    👤 {user} ({utype})
                    &nbsp;&nbsp;📍 {regions}
                    &nbsp;&nbsp;🕐 {time}
                </div>
                <div style="font-size:14px;color:#333;line-height:1.6;margin:8px 0;">
                    {txt}
                </div>
                <div style="margin:6px 0;">{tags}</div>
                <div style="font-size:12px;color:#888;">
                    转发:{reposts} 评论:{comments} 赞:{likes}
                    &nbsp;&nbsp;
                    <a href="{url}" style="color:#1e90ff;">查看原文→</a>
                </div>
            </div>""".format(
                label_color=label_color,
                idx=i,
                label=w["sentiment_label"],
                heat=w.get("heat", 0),
                score=w["sentiment_score"],
                user=w["user"],
                utype=w.get("user_type", "普通"),
                regions=", ".join(w.get("regions", [])),
                time=w["time"],
                txt=txt,
                tags=tag_html,
                reposts=w["reposts"],
                comments=w["comments"],
                likes=w["likes"],
                url=w["url"],
            )

    # 组装完整HTML
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = """
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family:'Microsoft YaHei',Arial,sans-serif;
                 max-width:800px;margin:0 auto;padding:20px;color:#333;">

        <div style="background:linear-gradient(135deg,#2c3e50,#3498db);
                    color:#fff;padding:24px;border-radius:10px;text-align:center;">
            <h1 style="margin:0;font-size:22px;">📊 汉中市微博舆情日报</h1>
            <p style="margin:8px 0 0;font-size:14px;opacity:0.9;">
                {period} &nbsp;|&nbsp; 生成时间: {now}
            </p>
        </div>

        <table width="100%%" style="margin:20px 0;border-spacing:8px;">
        <tr>
            <td align="center" style="padding:16px;background:#f0f7ff;border-radius:8px;">
                <div style="font-size:28px;font-weight:bold;color:#2c3e50;">{total}</div>
                <div style="font-size:13px;color:#666;">个人微博总量</div>
            </td>
            <td align="center" style="padding:16px;background:#fff5f5;border-radius:8px;">
                <div style="font-size:28px;font-weight:bold;color:#e74c3c;">{neg_count}</div>
                <div style="font-size:13px;color:#666;">负面/关注</div>
            </td>
            <td align="center" style="padding:16px;background:#f0fff0;border-radius:8px;">
                <div style="font-size:28px;font-weight:bold;color:#95a5a6;">{filtered}</div>
                <div style="font-size:13px;color:#666;">已过滤官方号</div>
            </td>
        </tr>
        </table>

        <h2 style="border-bottom:2px solid #3498db;padding-bottom:8px;font-size:16px;">
            📍 区县分布
        </h2>
        <table style="width:100%%;border-collapse:collapse;font-size:14px;">
            <tr style="background:#f5f5f5;">
                <th style="padding:8px;text-align:left;">区县</th>
                <th style="padding:8px;">总量</th>
                <th style="padding:8px;">负面</th>
                <th style="padding:8px;">占比</th>
            </tr>
            {region_rows}
        </table>

        <h2 style="border-bottom:2px solid #3498db;padding-bottom:8px;
                   font-size:16px;margin-top:24px;">
            📈 情感分布
        </h2>
        <table style="width:60%%;border-collapse:collapse;font-size:14px;">
            {sentiment_rows}
        </table>

        <h2 style="border-bottom:2px solid #e74c3c;padding-bottom:8px;
                   font-size:16px;margin-top:24px;">
            🔴 负面舆情详情（共{neg_count}条）
        </h2>
        {neg_html}

        <div style="margin-top:30px;padding:16px;background:#f5f5f5;
                    border-radius:6px;text-align:center;font-size:12px;color:#999;">
            此邮件由【汉中市微博舆情监测系统 v4】自动生成<br>
            详细数据见附件CSV文件
        </div>

    </body>
    </html>
    """.format(
        period="{} ~ {}".format(two_days_ago, today),
        now=now_str,
        total=len(results),
        neg_count=len(negatives),
        filtered=filtered,
        region_rows=region_rows,
        sentiment_rows=sentiment_rows,
        neg_html=neg_html,
    )

    return html