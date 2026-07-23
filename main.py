import os
import re
import csv
import json
import time
import random
import smtplib
import requests
from datetime import datetime, timedelta, timezone
from hashlib import md5
from urllib.parse import quote
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.header import Header
from email.utils import formataddr
from collections import defaultdict

# ==========================================
# 1. 配置区域
# ==========================================

COOKIE = os.environ.get("WEIBO_COOKIE", "在这里填你的最新微博Cookie")

EMAIL_CONFIG = {
    "enabled":     True,
    "smtp_server": os.environ.get("SMTP_SERVER", "smtp.qq.com"),
    "smtp_port":   int(os.environ.get("SMTP_PORT", "465")),
    "sender":      os.environ.get("EMAIL_SENDER", ""),       # 发件人邮箱
    "password":    os.environ.get("EMAIL_PASSWORD", ""),     # 授权码
    "receivers":   os.environ.get("EMAIL_RECEIVERS", "").split(","), # 收件人
}

TARGET_MEDIA = {
    "人民日报": ["人民日报"],
    "经济日报": ["经济日报"],
    "光明日报": ["光明日报"],
    "中国青年报": ["中国青年报", "中青报"],
    "新华每日电讯": ["新华每日电讯"],
    "人民网": ["人民网"],
    "新华网": ["新华网"],
    "中国经济网": ["中国经济网"],
    "央视网": ["央视网", "央视新闻"],
    "央广网": ["央广网"],
    "中国新闻网": ["中国新闻网", "中新网"],
}

SHAANXI_KEYWORDS = [
    "陕西", "西安", "咸阳", "宝鸡", "渭南", 
    "延安", "榆林", "汉中", "安康", "商洛", "铜川", "杨凌"
]

NEWS_CATEGORIES = {
    "💼 经济/产业": ["经济", "产业", "高质量发展", "项目", "投资", "企业", "产值", "农业", "工业", "新能源"],
    "🌸 文旅/生态": ["旅游", "文化", "生态", "秦岭", "黄河", "非遗", "景区", "文物", "博物馆", "绿化"],
    "👥 民生/社会": ["民生", "教育", "医疗", "就业", "群众", "社区", "交通", "天气", "暴雨", "救援"],
    "⭐ 时政/党建": ["会议", "强调", "调研", "党建", "干部", "落实", "精神", "视察", "改革"],
}

def build_queries():
    queries = []
    for media in TARGET_MEDIA.keys():
        for kw in SHAANXI_KEYWORDS:
            queries.append(f"{media} {kw}")
    return queries

# ==========================================
# 2. 日期与分析模块
# ==========================================

def get_date_range():
    """获取北京时间的今天和昨天日期"""
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    return today, yesterday

def get_target_media_name(username):
    for std_name, aliases in TARGET_MEDIA.items():
        for alias in aliases:
            if alias in username:
                return std_name
    return None

def analyze_news(text):
    tags = set()
    for cat, kws in NEWS_CATEGORIES.items():
        for kw in kws:
            if kw in text:
                tags.add(cat)
                break
    if not tags:
        tags.add("📰 综合资讯")
    return list(tags)

# ==========================================
# 3. 增强版时间解析与过滤模块
# ==========================================

def _clean(text):
    text = re.sub(r'<[^>]+>', '', text).strip()
    return re.sub(r'\s+', ' ', text)

def parse_time(s, today, yesterday):
    """能够智能识别微博的各类时间格式，统一转为 YYYY-MM-DD 格式"""
    now = datetime.now(timezone(timedelta(hours=8)))
    if not s: return ""
    s = str(s).strip()
    
    if "刚刚" in s: return now.strftime("%Y-%m-%d %H:%M")
    
    for pat, unit in [(r"(\d+)\s*秒前", "seconds"), (r"(\d+)\s*分钟前", "minutes"), (r"(\d+)\s*小时前", "hours")]:
        m = re.search(pat, s)
        if m:
            delta = timedelta(**{unit: int(m.group(1))})
            return (now - delta).strftime("%Y-%m-%d %H:%M")
            
    m = re.search(r"今天\s*(\d{1,2}):(\d{2})", s)
    if m: return f"{today} {m.group(1).zfill(2)}:{m.group(2)}"
    
    m = re.search(r"昨天\s*(\d{1,2}):(\d{2})", s)
    if m: return f"{yesterday} {m.group(1).zfill(2)}:{m.group(2)}"
    
    # 匹配无年份的 "10-24" 或 "10-24 15:30"
    m = re.search(r"^(\d{1,2})-(\d{1,2})", s)
    if m: return f"{now.year}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"
    
    # 匹配标准日期 "2023-10-24"
    m = re.search(r"(\d{4}-\d{1,2}-\d{1,2})", s)
    if m: return m.group(1)
    
    try:
        return datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y").strftime("%Y-%m-%d %H:%M")
    except:
        pass
    return s

def parse_mblog(mb, keyword, today, yesterday):
    if not mb: return None
    text = mb.get("text", "")
    if mb.get("isLongText"):
        lt = mb.get("longText", {})
        if isinstance(lt, dict) and lt.get("longTextContent"):
            text = lt["longTextContent"]
    text = _clean(text)
    if not text: return None

    created = mb.get("created_at", "")
    pt = parse_time(created, today, yesterday)
    
    # 【核心过滤】：严格只保留『今天』或『昨天』的内容
    if not (pt.startswith(today) or pt.startswith(yesterday)):
        return None

    user = mb.get("user") or {}
    wid = str(mb.get("id", ""))
    return {
        "id": wid, "user": user.get("screen_name", "未知"), "text": text,
        "time": pt or created, "reposts": mb.get("reposts_count", 0),
        "comments": mb.get("comments_count", 0), "likes": mb.get("attitudes_count", 0),
        "keyword": keyword, "url": f"https://m.weibo.cn/detail/{wid}"
    }

def parse_status(st, keyword, today, yesterday):
    if not st: return None
    text = st.get("text_raw", "") or re.sub(r'<[^>]+>', '', st.get("text", ""))
    text = _clean(text)
    if not text: return None

    created = st.get("created_at", "")
    pt = parse_time(created, today, yesterday)
    
    if not (pt.startswith(today) or pt.startswith(yesterday)):
        return None

    user = st.get("user") or {}
    wid = str(st.get("id", st.get("mid", "")))
    return {
        "id": wid, "user": user.get("screen_name", "未知"), "text": text,
        "time": pt or created, "reposts": st.get("reposts_count", 0),
        "comments": st.get("comments_count", 0), "likes": st.get("attitudes_count", 0),
        "keyword": keyword, "url": f"https://weibo.com/detail/{wid}"
    }

# ==========================================
# 4. 搜索模块
# ==========================================

def search_mobile(session, keyword, page, today, yesterday):
    weibos, mblogs = [], []
    cid = f"100103type=61&q={keyword}&t=0"
    params = {"containerid": cid, "page_type": "searchall", "page": page}
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5) AppleWebKit/605.1.15",
        "Accept": "application/json, text/plain, */*", "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://m.weibo.cn/search?containerid=" + quote(cid),
    }
    try:
        r = session.get("https://m.weibo.cn/api/container/getIndex", params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if data.get("ok") == 1:
                for card in data.get("data", {}).get("cards", []):
                    if card.get("card_type") == 9 and card.get("mblog"):
                        mblogs.append(card["mblog"])
                    elif card.get("card_type") == 11:
                        for sub in card.get("card_group", []):
                            if sub.get("card_type") == 9 and sub.get("mblog"):
                                mblogs.append(sub["mblog"])
                for mb in mblogs:
                    w = parse_mblog(mb, keyword, today, yesterday)
                    if w: weibos.append(w)
    except Exception: pass
    return weibos

def search_pc(session, keyword, page, today, yesterday):
    weibos = []
    # 限制搜索范围：昨天0点到今天23点
    params = {
        "q": keyword, "typeall": 1, "suball": 1,
        "timescope": f"custom:{yesterday}-0:{today}-23", "page": page,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0",
        "Accept": "application/json, text/plain, */*", "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://weibo.com/search?q={quote(keyword)}",
    }
    try:
        r = session.get("https://weibo.com/ajax/search/wb", params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            statuses = data.get("data", {}).get("statuses", []) if isinstance(data.get("data"), dict) else []
            for st in statuses:
                w = parse_status(st, keyword, today, yesterday)
                if w: weibos.append(w)
    except Exception: pass
    return weibos

# ==========================================
# 5. 生成报表与邮件发送
# ==========================================

def save_files(results, report_date_str):
    ts = datetime.now().strftime("%H%M%S")
    files = []
    if results:
        fn = f"央媒涉陕报道_{report_date_str}_{ts}.csv"
        with open(fn, "w", encoding="utf-8-sig", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["发布时间", "所属央媒", "微博账号", "新闻分类", "内容", "链接", "转", "评", "赞"])
            for w in results:
                wr.writerow([w["time"], w["media_std"], w["user"], ", ".join(w["tags"]), w["text"], w["url"], w["reposts"], w["comments"], w["likes"]])
        files.append(fn)
    return files

def build_html_report(results, report_date_str):
    if not results:
        return f"<h3>{report_date_str} 暂未监测到央媒发布涉陕报道。</h3>"
    
    grouped_news = defaultdict(list)
    # 按时间倒序排列新闻
    results = sorted(results, key=lambda x: x["time"], reverse=True)
    
    for w in results:
        grouped_news[w["media_std"]].append(w)

    news_html = ""
    for media_name, news_list in sorted(grouped_news.items(), key=lambda x: len(x[1]), reverse=True):
        news_html += f"""
        <div style="margin-bottom: 25px; border: 1px solid #e1e4e8; border-radius: 6px; overflow: hidden;">
            <div style="background-color: #f6f8fa; padding: 10px 15px; border-bottom: 1px solid #e1e4e8; font-weight: bold; color: #0366d6; font-size: 16px;">
                📰 {media_name} <span style="font-size:13px; color:#666; font-weight:normal;">({len(news_list)}篇)</span>
            </div>
            <div style="padding: 0 15px;">
        """
        for idx, w in enumerate(news_list, 1):
            tag_str = "".join([f'<span style="background:#e8f0fe; color:#1a73e8; padding:2px 8px; border-radius:12px; font-size:12px; margin-right:5px;">{t}</span>' for t in w["tags"]])
            border_bottom = "border-bottom: 1px dashed #eaecef;" if idx < len(news_list) else ""
            news_html += f"""
                <div style="padding: 12px 0; {border_bottom}">
                    <div style="font-size: 14px; color: #24292e; line-height: 1.6; margin-bottom: 8px;">
                        {w["text"][:200]}{'...' if len(w['text'])>200 else ''}
                    </div>
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>{tag_str}</div>
                        <div style="font-size: 12px; color: #586069;">
                            🕐 {w["time"]} &nbsp;|&nbsp; 👤 {w["user"]} &nbsp;|&nbsp; 
                            <a href="{w["url"]}" style="color: #0366d6; text-decoration: none;">原文 🔗</a>
                        </div>
                    </div>
                </div>
            """
        news_html += "</div></div>"

    return f"""
    <!DOCTYPE html>
    <html><head><meta charset="utf-8"></head>
    <body style="font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; color: #333;">
        <div style="background: linear-gradient(135deg, #1a73e8, #0b5394); color: #fff; padding: 25px; border-radius: 8px; text-align: center; margin-bottom: 20px;">
            <h1 style="margin: 0; font-size: 24px; letter-spacing: 2px;">🗞️ 央媒涉陕报道早报</h1>
            <p style="margin: 10px 0 0; font-size: 14px; opacity: 0.9;">监测日期：{report_date_str} &nbsp;|&nbsp; 共计收录：{len(results)} 篇</p>
        </div>
        {news_html}
    </body>
    </html>
    """

def send_email(smtp_server, smtp_port, sender, password, receivers, subject, html_body, attachments=None):
    if not sender or not password or not receivers or receivers == [""]:
        print("  ⚠️ 邮箱配置未完整填写，跳过发送邮件。")
        return False
    msg = MIMEMultipart()
    msg["From"] = formataddr((str(Header("央媒涉陕监测", "utf-8")), sender))
    msg["To"] = ", ".join(receivers)
    msg["Subject"] = Header(subject, "utf-8")
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if attachments:
        for filepath in attachments:
            if os.path.exists(filepath):
                with open(filepath, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", "attachment", filename=os.path.basename(filepath))
                msg.attach(part)
    try:
        server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30) if smtp_port == 465 else smtplib.SMTP(smtp_server, smtp_port, timeout=30)
        if smtp_port != 465: server.starttls()
        server.login(sender, password)
        server.sendmail(sender, receivers, msg.as_string())
        server.quit()
        print(f"  ✅ 邮件发送成功 → {', '.join(receivers)}")
        return True
    except Exception as e:
        print(f"  ❌ 邮件发送失败: {e}")
        return False

# ==========================================
# 6. 主执行类
# ==========================================

class MediaMonitor(object):
    def __init__(self, cookie):
        self.session = requests.Session()
        self.session.headers["Cookie"] = cookie
        self.results = []
        self.seen = set()
        
        # 智能获取今天和昨天的时间
        self.today, self.yesterday = get_date_range()
        self.report_date_str = f"{self.yesterday}至{self.today}"

    def _add(self, w):
        if not w: return False
        fp = md5(w["text"][:60].encode()).hexdigest()[:16]
        if fp in self.seen: return False
        if not any(kw in w["text"] for kw in SHAANXI_KEYWORDS): return False
        
        media_std_name = get_target_media_name(w["user"])
        if not media_std_name: return False

        self.seen.add(fp)
        w["media_std"] = media_std_name
        w["tags"] = analyze_news(w["text"])
        print(f"  ✅ [收录] {w['time']} | {w['media_std']} : {w['text'][:30]}...")
        self.results.append(w)
        return True

    def run(self, max_pages=3):
        print(f" 🔍 央媒涉陕新闻早报 | 目标范围: {self.report_date_str}")
        queries = build_queries()
        
        for idx, query in enumerate(queries, 1):
            print(f"\r  ▶ 正在检索 ({idx}/{len(queries)})：{query}    ", end="")
            for page in range(1, max_pages + 1):
                # 移动端检索
                for w in search_mobile(self.session, query, page, self.today, self.yesterday): 
                    self._add(w)
                time.sleep(random.uniform(2, 4))
                
                # PC端检索 (只用查第一页即可补充很多)
                if page == 1:
                    for w in search_pc(self.session, query, page, self.today, self.yesterday): 
                        self._add(w)
                    time.sleep(random.uniform(1, 3))

        print(f"\n📊 监测完成！共收录 【{self.report_date_str}】 央媒报道 {len(self.results)} 篇。")
        files = save_files(self.results, self.report_date_str)
        html = build_html_report(self.results, self.report_date_str)
        return files, html

def run_once():
    if not COOKIE or COOKIE == "在这里填你的最新微博Cookie":
        print("❌ 请先在代码顶部填入 WEIBO_COOKIE")
        return

    monitor = MediaMonitor(cookie=COOKIE)
    # 因为查2天的数据，适当把检索深度提高到 3 页
    files, html = monitor.run(max_pages=3)

    if EMAIL_CONFIG["enabled"]:
        subject = f"🗞️ 央媒涉陕报道早报 ({monitor.report_date_str}) | 共收录{len(monitor.results)}篇"
        send_email(
            EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"],
            EMAIL_CONFIG["sender"], EMAIL_CONFIG["password"], EMAIL_CONFIG["receivers"],
            subject, html, files
        )

if __name__ == "__main__":
    run_once()
