from __future__ import annotations

"""
mailer.py — 邮件发送 (修复版)
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
# 👇 新增：引入头部编码工具
from email.header import Header
from email.utils import formataddr

def send_email(smtp_server, smtp_port, sender, password,
               receivers, subject, html_body, attachments=None):
    # type: (str, int, str, str, list, str, str, list) -> bool
    """
    发送HTML邮件 + 附件
    """
    msg = MIMEMultipart()
    
    # 👇 修改 1：使用 formataddr 和 Header 标准化发件人
    # 格式： "显示名称 <邮箱地址>" (显示名称需要 utf-8 编码)
    msg["From"] = formataddr((str(Header("舆情监测", "utf-8")), sender))
    
    # 👇 修改 2：收件人列表如果包含中文名也建议处理，这里暂时只处理简单的 join
    msg["To"] = ", ".join(receivers)
    
    # 👇 修改 3：Subject 最好也显式编码，防止乱码（虽然有些客户端能自动处理）
    msg["Subject"] = Header(subject, "utf-8")

    # HTML正文
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # 附件
    if attachments:
        for filepath in attachments:
            if not os.path.exists(filepath):
                print("  ⚠️ 附件不存在: {}".format(filepath))
                continue
            
            with open(filepath, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            
            encoders.encode_base64(part)
            filename = os.path.basename(filepath)
            
            # 处理附件名称中的中文
            part.add_header(
                "Content-Disposition",
                "attachment",
                filename=filename  # Python 3 email 库会自动处理这里的文件名编码
            )
            msg.attach(part)

    # 发送
    try:
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
            server.starttls()

        server.login(sender, password)
        server.sendmail(sender, receivers, msg.as_string())
        server.quit()
        print("  ✅ 邮件发送成功 → {}".format(", ".join(receivers)))
        return True

    except Exception as e:
        print("  ❌ 邮件发送失败: {}".format(e))
        return False