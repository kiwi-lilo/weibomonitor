from __future__ import annotations
import os, time, random
from datetime import datetime, timedelta, timezone
from hashlib import md5

from config import build_queries, SHAANXI_KEYWORDS
from searcher import search_mobile, search_pc, search_general
from analyzer import get_target_media_name, analyze_news
from wb_parser import get_beijing_today
from reporter import save_files, build_html_report
from mailer import send_email

COOKIE = os.environ.get("WEIBO_COOKIE", "在这里填你的默认Cookie")
EMAIL_CONFIG = {
    "enabled":     True,
    "smtp_server": os.environ.get("SMTP_SERVER", "smtp.qq.com"),
    "smtp_port":   int(os.environ.get("SMTP_PORT", "465")),
    "sender":      os.environ.get("EMAIL_SENDER", ""),
    "password":    os.environ.get("EMAIL_PASSWORD", ""),
    "receivers":   os.environ.get("EMAIL_RECEIVERS", "").split(","),
}

class MediaMonitor(object):
    def __init__(self, cookie):
        import requests
        self.session = requests.Session()
        self.session.headers["Cookie"] = cookie
        self.results = []
        self.seen = set()
        self.today = get_beijing_today()

    def _add(self, w):
        if not w: return False
        
        # 去重
        fp = md5(w["text"][:60].encode()).hexdigest()[:16]
        if fp in self.seen: return False
        
        # 1. 判断是否包含陕西关键词
        if not any(kw in w["text"] for kw in SHAANXI_KEYWORDS):
            return False

        # 2. 判断是否属于目标央媒
        media_std_name = get_target_media_name(w["user"])
        if not media_std_name:
            return False # 丢弃普通账号和非目标媒体

        self.seen.add(fp)
        
        # 打标签与丰富字段
        w["media_std"] = media_std_name
        w["tags"] = analyze_news(w["text"])
        
        print(f"  ✅ [收录] {w['media_std']} : {w['text'][:30]}...")
        self.results.append(w)
        return True

    def run(self, max_pages=2):
        print(f" 🔍 央媒涉陕新闻监测 | 目标日期: {self.today}")
        queries = build_queries()
        
        for idx, query in enumerate(queries, 1):
            print(f"\n  ▶ 正在检索 ({idx}/{len(queries)})：{query}")
            
            for page in range(1, max_pages + 1):
                # 移动端检索
                for w in search_mobile(self.session, query, page, self.today):
                    self._add(w)
                time.sleep(random.uniform(2, 4))
                
                # PC端检索补充
                if page == 1:
                    for w in search_pc(self.session, query, page, self.today, self.today):
                        self._add(w)
                    time.sleep(random.uniform(1, 3))

        print(f"\n📊 监测完成！共收录当日央媒报道 {len(self.results)} 篇。")
        files = save_files(self.results, self.today)
        html = build_html_report(self.results, self.today)
        return files, html

def run_once():
    monitor = MediaMonitor(cookie=COOKIE)
    files, html = monitor.run(max_pages=2)

    cfg = EMAIL_CONFIG
    if cfg["enabled"] and cfg["sender"]:
        print("\n📧 正在发送新闻简报邮件...")
        subject = f"🗞️ 央媒涉陕报道简报 ({monitor.today}) | 共收录{len(monitor.results)}篇"
        send_email(
            smtp_server=cfg["smtp_server"], smtp_port=cfg["smtp_port"],
            sender=cfg["sender"], password=cfg["password"], receivers=cfg["receivers"],
            subject=subject, html_body=html, attachments=files
        )

if __name__ == "__main__":
    run_once()
