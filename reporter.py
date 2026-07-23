from __future__ import annotations
import csv
import json
from datetime import datetime
from collections import defaultdict

def save_files(results, today):
    """保存 CSV + JSON"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    files = []
    if results:
        fn = f"央媒涉陕报道_{today}.csv"
        # 写入CSV，包含字段：时间, 媒体, 账号名, 文本, 标签, 链接
        with open(fn, "w", encoding="utf-8-sig", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["发布时间", "所属央媒", "微博账号", "新闻分类", "内容", "链接", "转", "评", "赞"])
            for w in results:
                wr.writerow([
                    w["time"], w["media_std"], w["user"], 
                    ", ".join(w["tags"]), w["text"], w["url"],
                    w["reposts"], w["comments"], w["likes"]
                ])
        files.append(fn)
    return files

def build_html_report(results, today):
    """生成政务简报风的HTML邮件"""
    
    if not results:
        return f"<h3>{today} 暂未监测到央媒发布涉陕报道。</h3>"

    # 按所属央媒对新闻进行分组
    grouped_news = defaultdict(list)
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
                            🕐 {w["time"][-5:]} &nbsp;|&nbsp; 
                            👤 {w["user"]} &nbsp;|&nbsp; 
                            <a href="{w["url"]}" style="color: #0366d6; text-decoration: none;">查看原文 🔗</a>
                        </div>
                    </div>
                </div>
            """
        news_html += "</div></div>"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; color: #333;">

        <div style="background: linear-gradient(135deg, #1a73e8, #0b5394); color: #fff; padding: 25px; border-radius: 8px; text-align: center; margin-bottom: 20px;">
            <h1 style="margin: 0; font-size: 24px; letter-spacing: 2px;">🗞️ 中央媒体涉陕报道简报</h1>
            <p style="margin: 10px 0 0; font-size: 14px; opacity: 0.9;">
                监测日期：{today} &nbsp;|&nbsp; 共计收录：{len(results)} 篇
            </p>
        </div>

        {news_html}

        <div style="margin-top: 30px; padding: 15px; background: #f8f9fa; border-radius: 6px; text-align: center; font-size: 12px; color: #6c757d;">
            * 此简报由系统自动聚合生成，监测范围覆盖人民日报、新华社、央视等11家中央媒体。<br>
            完整数据请见邮件附件 CSV 文件。
        </div>
    </body>
    </html>
    """
    return html
