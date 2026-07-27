"""main.py — 陕西多市微博舆情监测 v5

一次运行遍历 cities.py 中的所有城市：共用一个 Cookie、一次装依赖、
情感模型只加载一次，最后发一封汇总日报（各市一节 + 附件）。

关键行为：
  · 按微博 id 去重，seen 状态每城市各一份、跨天持久化，日报只突出"新增"
  · Cookie 失效 / 首城市三接口全挂 → 中止整轮并发异常告警邮件
  · 每组合翻 1 页、首页为空即早停
  · 情感研判：词库 → 本地模型(transformer/lite) → 可选 LLM
"""

from __future__ import annotations

import logging
import random
import sys
import time
from datetime import datetime, timedelta
from hashlib import md5

from config import Settings, TZ, MAX_PAGES, DAYS_BACK
from cities import City, CITIES
from keywords import build_queries
from models import Weibo
from fetcher import build_session, search_mobile, search_general, Health, Status
from analyzer import is_official, analyze, llm_refine, model_refine
from state import load_seen, save_seen
from reporter import (print_report, save_files, build_city_section,
                      build_digest_html, build_alert_html)
from mailer import send_email

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("main")

AUTH_ABORT_THRESHOLD = 3


class AuthAborted(Exception):
    """Cookie 失效，需中止整轮"""


class CityMonitor:
    """单个城市的采集与研判"""

    def __init__(self, settings: Settings, city: City, session, now: datetime):
        self.settings = settings
        self.city = city
        self.session = session
        self.health = Health()
        self.results: list[Weibo] = []
        self.filtered: list[dict] = []
        self.seen_ids: set[str] = set()
        self.seen_fp: set[str] = set()
        self.today = now.strftime("%Y-%m-%d")
        self.date_from = (now - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")

    def _add(self, w: Weibo) -> bool:
        if w.id in self.seen_ids:
            return False
        fp = md5(w.text[:80].encode()).hexdigest()
        if fp in self.seen_fp:
            return False
        self.seen_ids.add(w.id)
        self.seen_fp.add(fp)

        if not self.city.match_regions(w.text):   # 含外地同名地名消歧（如深圳西乡）
            return False

        official, reason = is_official(w)
        if official:
            self.filtered.append({"user": w.user, "reason": reason,
                                  "text": w.text[:120], "url": w.url})
            return False

        analyze(w, self.city)
        self.results.append(w)
        if w.is_negative:
            log.info("[%s] 🔴 [%s] %s…", self.city.short, w.sentiment_label, w.text[:36])
        return True

    def _consume(self, result) -> int:
        self.health.record(result.status)
        return sum(1 for w in result.items if self._add(w))

    def _check_abort(self) -> None:
        if self.health.auth_failures >= AUTH_ABORT_THRESHOLD:
            raise AuthAborted(f"[{self.city.short}] Cookie 失效（多次返回登录页）")

    def collect(self, probe: bool) -> None:
        """probe=True 时（首个城市）先做接口自检，全挂则中止整轮"""
        districts = self.city.districts
        queries = build_queries(districts)
        log.info("─" * 48)
        log.info("🔍 %s  区县%d 任务%d", self.city.name, len(districts), len(queries))

        if probe:
            alive = 0
            for name, fn in (("移动端", lambda: search_mobile(self.session, districts[0], 1)),
                             ("兜底", lambda: search_general(self.session, districts[0], 1))):
                r = fn()
                n = self._consume(r)
                log.info("  自检 %s: %s (%d条,收录%d)", name, r.status.value, len(r.items), n)
                alive += 1 if r.status == Status.OK else 0
                time.sleep(2)
            self._check_abort()
            if alive == 0:
                raise AuthAborted("首个城市两接口自检均无数据，疑似 Cookie 失效或被风控")

        prev_dist = None
        for dist, query in queries:
            if dist != prev_dist:
                self._consume(search_general(self.session, query, 1))
                time.sleep(random.uniform(1, 2))
                prev_dist = dist

            got_any = False
            for page in range(1, MAX_PAGES + 1):
                got_any |= self._consume(search_mobile(self.session, query, page)) > 0
                time.sleep(random.uniform(2, 4))
                self._check_abort()
                if page == 1 and not got_any:
                    break

    def finalize(self) -> dict:
        """跨天状态 + 研判复核 + 存档，返回汇总片段数据"""
        historical = load_seen(self.city.short)
        for w in self.results:
            w.is_new = w.id not in historical
        save_seen(self.city.short, historical | {w.id for w in self.results})

        model_refine(self.results)  # 本地模型对全部结果打分融合

        negatives = [w for w in self.results if w.is_negative]
        new_negatives = [w for w in negatives if w.is_new]
        llm_refine(new_negatives, self.settings, self.city.name)  # 可选 LLM 覆盖
        negatives = [w for w in self.results if w.is_negative]
        new_negatives = [w for w in negatives if w.is_new]
        old_neg = len(negatives) - len(new_negatives)

        err = self.health.counts[Status.ERROR] + self.health.counts[Status.BLOCKED]
        health_ok = err / max(self.health.total, 1) < 0.2 and self.health.auth_failures == 0

        print_report(self.results, new_negatives, len(self.filtered),
                     f"[{self.city.short}] " + self.health.summary())
        period = f"{self.date_from} ~ {self.today}"
        files = save_files(self.city.short, self.results, negatives,
                           self.filtered, period)
        section = build_city_section(self.city, self.results, new_negatives,
                                     old_neg, len(self.filtered),
                                     self.health.summary(), health_ok)
        section["files"] = files
        section["new_negatives_list"] = new_negatives  # ✅ 新增这行：供主流程提取
        return section


def run(settings: Settings) -> None:
    session = build_session(settings.cookie)
    now = datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")
    period = f"{(now - timedelta(days=DAYS_BACK)).strftime('%Y-%m-%d')} ~ {today}"

    log.info("═" * 52)
    log.info("陕西多市舆情监测 v5  城市: %s", "、".join(c.short for c in CITIES))
    log.info("═" * 52)

    sections: list[dict] = []
    try:
        for i, city in enumerate(CITIES):
            mon = CityMonitor(settings, city, session, now)
            mon.collect(probe=(i == 0))
            sections.append(mon.finalize())
    except AuthAborted as e:
        log.error("⛔ %s，中止整轮", e)
        send_email(settings, f"⚠️ 陕西舆情监测采集异常 {today}",
                   build_alert_html(str(e), "见运行日志"))
        sys.exit(1)

    # 汇总一封日报
# ================ main.py 主循环结束，下面是组装发送阶段 ================

    # 0. 提取所有城市的附件合并成一个大列表
    all_files = [f for s in sections for f in s.get("files", [])]

    # ---------------- 1. 提取 Top 10 领导专报 ----------------
    from analyzer import llm_summarize
    from reporter import build_leader_summary_text, build_digest_html
    from datetime import datetime
    
    # 汇总所有城市的新增负面，并通过 id 去重（防止跨城同名导致的重复）
    unique_neg = {}
    for s in sections:
        for w in s.get("new_negatives_list", []):
            unique_neg[w.id] = w
    all_new_neg = list(unique_neg.values())
    
    # 核心排榜逻辑：按照 情感分越低越危险(正序) + 热度越高越受关注(倒序) 排序
    all_new_neg.sort(key=lambda x: (getattr(x, 'sentiment_score', 0), -getattr(x, 'heat', 0)))
    top10 = all_new_neg[:10]  # 只取全省前 10 条
    
    # 调动大模型生成摘要
    leader_text = ""
    if top10:
        llm_summarize(top10, settings)
        leader_text = build_leader_summary_text(top10)
        # 打印到 GitHub Actions 控制台，方便日志追溯
        print("\n" + "👑" * 30)
        print("  领导舆情专报 (Top 10 极简版)")
        print("👑" * 30 + "\n")
        print(leader_text)
        print("\n" + "═" * 60)
        
    # ---------------- 2. 生成 HTML 邮件正文 ----------------
    # 传入 leader_text 供模板渲染顶部的黄框
    html = build_digest_html(sections, period, leader_text=leader_text)
    
    # ---------------- 3. 生成动态邮件标题 ----------------
    try:
        from config import TZ
    except ImportError:
        import pytz
        TZ = pytz.timezone('Asia/Shanghai')
        
    today = datetime.now(TZ).strftime("%m-%d")
    total_new = sum(s.get("new_neg", 0) for s in sections)
    any_bad = any(not s.get("health_ok", True) for s in sections)

    if total_new > 0:
        subject = f"🔴 陕西舆情日报 {today} | 新增负面合计 {total_new} 条"
    elif any_bad:
        subject = f"⚠️ 陕西舆情日报 {today} | 部分城市采集异常"
    else:
        subject = f"✅ 陕西舆情日报 {today} | 各市均无新增负面"

    # ---------------- 4. 执行发送邮件 ----------------
    # 带有动态标题、带大模型专报的HTML正文、带上所有城市的附件
    send_email(settings, subject, html, attachments=all_files)
    log.info("✅ 全部 %d 市执行完成", len(CITIES))


def main() -> None:
    settings = Settings()
    for p in settings.validate():
        log.warning("配置提示: %s", p)
    if not settings.cookie:
        log.error("❌ 未配置 WEIBO_COOKIE，退出")
        sys.exit(1)
    run(settings)


if __name__ == "__main__":
    main()
