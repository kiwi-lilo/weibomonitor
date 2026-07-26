"""main.py — 汉中市微博舆情监测 v5

相对 v4 的关键行为变化：
  · 按微博 id 去重（文本指纹仅用于合并转发）
  · seen 状态跨天持久化，日报只突出"新增"负面
  · Cookie 失效 / 接口全挂 → 中止并发送异常告警邮件（绝不发假"平安报"）
  · 第 1 页为空则跳过该关键词后续页，整轮耗时大幅下降
  · 可选 LLM 复核负面候选（配置 LLM_API_* 即启用）
"""

from __future__ import annotations

import logging
import random
import sys
import time
from datetime import datetime, timedelta
from hashlib import md5

from config import Settings, TZ, MAX_PAGES, DAYS_BACK
from keywords import build_queries, ALL_REGION_KW, SEARCH_DISTRICTS, CITY_SHORT
from models import Weibo
from fetcher import build_session, search_mobile, search_general, Health, Status
from analyzer import is_official, analyze, llm_refine, model_refine
from state import load_seen, save_seen
from reporter import print_report, save_files, build_html_report, build_alert_html
from mailer import send_email

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("main")

AUTH_ABORT_THRESHOLD = 3      # 累计 N 次"需登录"即判定 Cookie 失效并中止


class Monitor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = build_session(settings.cookie)
        self.health = Health()
        self.results: list[Weibo] = []
        self.filtered: list[dict] = []          # 被过滤的官方号（留原文供审计）
        self.seen_ids: set[str] = set()         # 本轮内去重
        self.seen_fp: set[str] = set()          # 转发文本指纹去重
        now = datetime.now(TZ)
        self.today = now.strftime("%Y-%m-%d")
        self.date_from = (now - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")

    # ── 收录 ──
    def _add(self, w: Weibo) -> bool:
        if w.id in self.seen_ids:
            return False
        fp = md5(w.text[:80].encode()).hexdigest()
        if fp in self.seen_fp:
            return False
        self.seen_ids.add(w.id)
        self.seen_fp.add(fp)

        if not any(kw in w.text for kw in ALL_REGION_KW):
            return False

        official, reason = is_official(w)
        if official:
            self.filtered.append({"user": w.user, "reason": reason,
                                  "text": w.text[:120], "url": w.url})
            return False

        analyze(w)
        self.results.append(w)
        if w.is_negative:
            log.info("🔴 捕获[%s] %s…", w.sentiment_label, w.text[:40])
        return True

    def _consume(self, result) -> int:
        self.health.record(result.status)
        n = 0
        for w in result.items:
            if self._add(w):
                n += 1
        return n

    # ── 熔断检查 ──
    def _check_abort(self) -> str:
        if self.health.auth_failures >= AUTH_ABORT_THRESHOLD:
            return "微博 Cookie 已失效（多次返回登录页），本轮采集中止。"
        return ""

    # ── 主流程 ──
    def run(self) -> None:
        queries = build_queries()
        total = len(queries)
        log.info("═" * 52)
        log.info("🔍 %s舆情监测 v5  区间 %s ~ %s  任务 %d 个", CITY_SHORT,
                 self.date_from, self.today, total)
        log.info("═" * 52)

        # 开机自检：三接口各试一次
        probes = [
            ("移动端", lambda: search_mobile(self.session, SEARCH_DISTRICTS[0], 1)),
            ("兜底",   lambda: search_general(self.session, SEARCH_DISTRICTS[0], 1)),
        ]
        alive = 0
        for name, fn in probes:
            r = fn()
            n = self._consume(r)          # 自检数据同样收录，不浪费请求
            log.info("  自检 %s: %s (%d 条, 收录 %d)", name, r.status.value, len(r.items), n)
            alive += 1 if r.status == Status.OK else 0
            time.sleep(2)
        if alive == 0:
            reason = self._check_abort() or "三个搜索接口自检均无数据，疑似 Cookie 失效或被风控。"
            self._abort(reason)

        prev_dist = None
        for idx, (dist, query) in enumerate(queries, 1):
            log.info("[%3d/%d] 「%s」", idx, total, query)

            # 每进入一个新区县，先跑一次通用兜底
            if dist != prev_dist:
                self._consume(search_general(self.session, query, 1))
                time.sleep(random.uniform(1, 2))
                prev_dist = dist

            got_any = False

            for page in range(1, MAX_PAGES + 1):
                n = self._consume(search_mobile(self.session, query, page))
                got_any = got_any or n > 0
                time.sleep(random.uniform(2, 4))

                if reason := self._check_abort():
                    self._abort(reason)

                # 早停：首页无结果，后续页大概率也没有
                if page == 1 and not got_any:
                    break

        self._finish()

    def _abort(self, reason: str) -> None:
        log.error("⛔ %s", reason)
        html = build_alert_html(reason, self.health.summary())
        send_email(self.settings,
                   f"⚠️ {CITY_SHORT}舆情监测采集异常 {self.today}",
                   html)
        sys.exit(1)   # 让 Actions 显示为失败，一眼可见

    def _finish(self) -> None:
        # 跨天状态：区分新增 / 历史
        historical = load_seen()
        for w in self.results:
            w.is_new = w.id not in historical
        save_seen(historical | {w.id for w in self.results})

        # 可选：本地模型复核全部结果（免费，装了 torch/transformers 即启用）
        model_refine(self.results)

        negatives = [w for w in self.results if w.is_negative]
        new_negatives = [w for w in negatives if w.is_new]

        # 可选：LLM 复核新增负面候选（配置了 LLM_API_* 时覆盖模型结论），再重算
        llm_refine(new_negatives, self.settings)
        negatives = [w for w in self.results if w.is_negative]
        new_negatives = [w for w in negatives if w.is_new]
        old_neg_count = len(negatives) - len(new_negatives)

        error_rate = (self.health.counts[Status.ERROR] + self.health.counts[Status.BLOCKED]) \
            / max(self.health.total, 1)
        health_ok = error_rate < 0.2 and self.health.auth_failures == 0

        period = f"{self.date_from} ~ {self.today}"
        print_report(self.results, new_negatives, len(self.filtered), self.health.summary())
        files = save_files(self.results, negatives, self.filtered, period)
        html = build_html_report(self.results, new_negatives, old_neg_count,
                                 len(self.filtered), period,
                                 self.health.summary(), health_ok)

        if new_negatives:
            subject = f"🔴 {CITY_SHORT}舆情日报 {self.today} | 新增 {len(new_negatives)} 条负面"
        elif not health_ok:
            subject = f"⚠️ {CITY_SHORT}舆情日报 {self.today} | 采集部分异常"
        else:
            subject = f"✅ {CITY_SHORT}舆情日报 {self.today} | 无新增负面"
        send_email(self.settings, subject, html, attachments=files)
        log.info("✅ 本次执行完成")


def main() -> None:
    settings = Settings()
    for p in settings.validate():
        log.warning("配置提示: %s", p)
    if not settings.cookie:
        log.error("❌ 未配置 WEIBO_COOKIE，退出")
        sys.exit(1)
    Monitor(settings).run()


if __name__ == "__main__":
    main()
