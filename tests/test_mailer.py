from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import Settings
from mailer import send_email


def test_send_email_uses_smtp_ssl(monkeypatch):
    calls = {}

    class SMTP:
        def __init__(self, host, port, timeout):
            calls.update(host=host, port=port, timeout=timeout)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def login(self, sender, password):
            calls.update(sender=sender, password=password)

        def sendmail(self, sender, receivers, message):
            calls.update(receivers=receivers, message=message)

    monkeypatch.setattr("mailer.smtplib.SMTP_SSL", SMTP)
    settings = Settings(
        cookie="cookie",
        smtp_server="smtp.example.com",
        smtp_port=465,
        email_sender="sender@example.com",
        email_password="secret",
        email_receivers=["receiver@example.com"],
    )

    assert send_email(settings, "测试日报", "<b>正文</b>")
    assert calls["host"] == "smtp.example.com"
    assert calls["port"] == 465
    assert calls["receivers"] == ["receiver@example.com"]
    assert "Content-Type: text/html" in calls["message"]


def test_send_email_skips_incomplete_settings(monkeypatch):
    monkeypatch.setattr(
        "mailer.smtplib.SMTP_SSL",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应连接 SMTP")),
    )
    assert not send_email(Settings(cookie="cookie"), "标题", "<b>正文</b>")
