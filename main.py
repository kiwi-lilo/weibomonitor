from __future__ import annotations

"""
main.py — 汉中市微博舆情监测 v4
支持本地运行 / GitHub Actions 定时运行
"""

import os
import time
import random
import requests
from datetime import datetime, timedelta
from hashlib import md5

from config import (
    REGIONS, ALL_REGION_KW, build_queries,
    SEARCH_DISTRICTS, SEARCH_NEGATIVE_KW,
)
from searcher import search_mobile, search_pc, search_general
from analyzer import is_official, has_official_phrases, analyze
from reporter import print_report, save_files, build_html_report
from mailer import send_email


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  配置（优先读环境变量，读不到用默认值）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 微博Cookie
COOKIE = os.environ.get("WEIBO_COOKIE", "在这里填你的默认Cookie")

# 邮件配置
EMAIL_CONFIG = {
    "enabled":     True,
    "smtp_server": os.environ.get("SMTP_SERVER", "smtp.qq.com"),
    "smtp_port":   int(os.environ.get("SMTP_PORT", "465")),
    "sender":      os.environ.get("EMAIL_SENDER", ""),
    "password":    os.environ.get("EMAIL_PASSWORD", ""),
    "receivers":   os.environ.get("EMAIL_RECEIVERS", "").split(","),
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  监测主类
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class WeiboMonitor(object):

    def __init__(self, cookie):
        # type: (str) -> None
        self.session = requests.Session()
        self.session.headers["Cookie"] = cookie
        self.results = []
        self.negative_results = []
        self.seen = set()
        self.filtered_official = 0
        self.today = datetime.now().strftime("%Y-%m-%d")
        self.two_days_ago = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")

    def _add(self, w):
        # type: (dict) -> bool
        fp = md5(w["text"][:60].encode()).hexdigest()[:16]
        if fp in self.seen:
            return False
        self.seen.add(fp)

        if not any(kw in w["text"] for kw in ALL_REGION_KW):
            return False

        if is_official(w) or has_official_phrases(w["text"]):
            self.filtered_official += 1
            return False

        sent = analyze(w["text"])
        w["sentiment_score"] = sent["score"]
        w["sentiment_label"] = sent["label"]
        w["strong_neg"]      = sent["strong_neg"]
        w["medium_neg"]      = sent["medium_neg"]
        w["mild_neg"]        = sent["mild_neg"]
        w["positive_ctx"]    = sent["positive_ctx"]

        regions = []
        for name, kws in REGIONS.items():
            if any(kw in w["text"] for kw in kws):
                regions.append(name)
        w["regions"] = regions if regions else ["汉中市"]

        w["heat"] = w.get("reposts", 0) * 3 + w.get("comments", 0) * 2 + w.get("likes", 0)

        vtype = w.get("verified_type", -1)
        if vtype == 0:
            w["user_type"] = "个人认证(黄V)"
        else:
            w["user_type"] = "普通用户"

        if sent["label"] in ("负面", "偏负面"):
            print("  🔴 [捕获] {}...".format(w["text"][:40]))

        self.results.append(w)
        if sent["label"] in ("负面", "偏负面", "关注"):
            self.negative_results.append(w)
        return True

    def diagnose(self):
        # type: () -> bool
        print("\n  🩺 接口诊断...")
        total = 0
        tests = [
            ("移动端",   lambda: search_mobile(self.session, "汉中", 1, self.today)),
            ("PC端",     lambda: search_pc(self.session, "汉中", 1, self.today, self.two_days_ago)),
            ("通用兜底", lambda: search_general(self.session, "汉中", 1, self.today)),
        ]
        for name, func in tests:
            print("    {}: ".format(name), end="", flush=True)
            r = func()
            if r:
                print("✅ {}条".format(len(r)))
            else:
                print("❌ 0条")
            total += len(r)
            time.sleep(2)

        ok = total > 0
        if ok:
            print("\n  ✅ 可运行\n")
        else:
            print("\n  ⚠️ 无数据\n")
        return ok

    def run(self, max_pages=3):
        # type: (int) -> tuple
        print("""
{line}
 🔍  汉中市微博舆情监测 v4
 📅  {ago} ~ {today}
 🕐  {now}
 📍  覆盖区域: {d} 个
 💣  监测重词: {k} 个
{line}""".format(
            line="═" * 60,
            ago=self.two_days_ago,
            today=self.today,
            now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            d=len(SEARCH_DISTRICTS),
            k=len(SEARCH_NEGATIVE_KW),
        ))

        self.diagnose()

        queries = build_queries()
        total = len(queries)
        print("  📋 共 {} 个搜索任务\n".format(total))

        for idx, query in enumerate(queries, 1):
            pct = idx / total * 100
            print("  [{:3d}/{}] ({:5.1f}%) 「{}」".format(idx, total, pct, query),
                  end="", flush=True)
            before = len(self.results)

            for page in range(1, max_pages + 1):
                for w in search_mobile(self.session, query, page, self.today):
                    self._add(w)
                time.sleep(random.uniform(2, 4))

                if page == 1:
                    for w in search_pc(self.session, query, page,
                                       self.today, self.two_days_ago):
                        self._add(w)
                    time.sleep(random.uniform(1.5, 3))

                if page == 1 and idx <= len(SEARCH_DISTRICTS):
                    for w in search_general(self.session, query, page, self.today):
                        self._add(w)
                    time.sleep(random.uniform(1, 2))

            added = len(self.results) - before
            if added:
                print("  → +{}".format(added))
            else:
                print("  → 0")

        print_report(self.results, self.negative_results, self.filtered_official)

        files = save_files(
            self.results, self.negative_results, self.filtered_official,
            self.today, self.two_days_ago,
        )

        html = build_html_report(
            self.results, self.negative_results, self.filtered_official,
            self.today, self.two_days_ago,
        )

        return files, html


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  执行
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_once():
    print("\n🚀 开始执行 [{}]".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    # 检查Cookie
    if not COOKIE or COOKIE == "在这里填你的默认Cookie":
        print("❌ 未配置 WEIBO_COOKIE，请设置环境变量或修改代码")
        return

    monitor = WeiboMonitor(cookie=COOKIE)
    files, html = monitor.run(max_pages=3)

    # 发邮件
    cfg = EMAIL_CONFIG
    if cfg["enabled"] and cfg["sender"] and cfg["password"]:
        print("\n  📧 正在发送邮件...")
        today = datetime.now().strftime("%Y-%m-%d")
        neg_count = len(monitor.negative_results)

        if neg_count > 0:
            subject = "🔴 汉中舆情日报 {} | 发现{}条负面".format(today, neg_count)
        else:
            subject = "✅ 汉中舆情日报 {} | 未发现负面".format(today)

        send_email(
            smtp_server=cfg["smtp_server"],
            smtp_port=cfg["smtp_port"],
            sender=cfg["sender"],
            password=cfg["password"],
            receivers=cfg["receivers"],
            subject=subject,
            html_body=html,
            attachments=files,
        )
    else:
        print("\n  ⚠️ 邮件未配置，跳过发送")

    print("\n✅ 本次执行完成 [{}]".format(datetime.now().strftime("%H:%M:%S")))


if __name__ == "__main__":
    run_once()
