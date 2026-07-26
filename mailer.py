"""mailer.py — 邮件发送"""

from __future__ import annotations

import logging
import os
import smtplib
from email.header import Header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from email import encoders

from config import Settings

log = logging.getLogger(__name__)


def send_email(settings: Settings, subject: str, html_body: str,
               attachments: list[str] | None = None) -> bool:
    if not settings.email_ready:
        log.warning("邮件配置不完整，跳过发送")
        return False

    msg = MIMEMultipart()
    msg["From"] = formataddr((str(Header("舆情监测", "utf-8")), settings.email_sender))
    msg["To"] = ", ".join(settings.email_receivers)
    msg["Subject"] = Header(subject, "utf-8")
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    for filepath in attachments or []:
        if not os.path.exists(filepath):
            log.warning("附件不存在: %s", filepath)
            continue
        part = MIMEBase("application", "octet-stream")
        with open(filepath, "rb") as f:
            part.set_payload(f.read())
        encoders.encode_base64(part)
        # 三元组形式确保中文附件名按 RFC2231 编码，各客户端兼容性最好
        part.add_header("Content-Disposition", "attachment",
                        filename=("utf-8", "", os.path.basename(filepath)))
        msg.attach(part)

    try:
        if settings.smtp_port == 465:
            ctx = smtplib.SMTP_SSL(settings.smtp_server, settings.smtp_port, timeout=30)
        else:
            ctx = smtplib.SMTP(settings.smtp_server, settings.smtp_port, timeout=30)
        with ctx as server:              # with 确保任何异常下连接都被关闭
            if settings.smtp_port != 465:
                server.starttls()
            server.login(settings.email_sender, settings.email_password)
            server.sendmail(settings.email_sender, settings.email_receivers,
                            msg.as_string())
        log.info("邮件发送成功 → %s", ", ".join(settings.email_receivers))
        return True
    except (smtplib.SMTPException, OSError) as e:
        log.error("邮件发送失败: %s", e)
        return False
