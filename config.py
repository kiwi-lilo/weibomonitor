"""config.py — 运行配置（环境变量集中读取 + 校验）"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

def _load_dotenv() -> None:
    """加载项目根目录 .env（KEY=VALUE 每行一条；不覆盖已有环境变量）"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

TZ = ZoneInfo("Asia/Shanghai")  # 全项目统一北京时间，避免 Actions 的 UTC 时钟造成日期偏移

STATE_FILE = os.environ.get("STATE_FILE", "state/seen.json")
SEEN_MAX = 20000          # seen 列表最多保留多少条 id
MAX_PAGES = int(os.environ.get("MAX_PAGES", "1"))  # 每个搜索组合翻几页
DAYS_BACK = 2             # 监测最近 N 天


def _split_receivers(raw: str) -> list[str]:
    return [r.strip() for r in raw.split(",") if r.strip()]


@dataclass
class Settings:
    cookie: str = field(default_factory=lambda: os.environ.get("WEIBO_COOKIE", ""))

    smtp_server: str = field(default_factory=lambda: os.environ.get("SMTP_SERVER", "smtp.qq.com"))
    smtp_port: int = field(default_factory=lambda: int(os.environ.get("SMTP_PORT", "465")))
    email_sender: str = field(default_factory=lambda: os.environ.get("EMAIL_SENDER", ""))
    email_password: str = field(default_factory=lambda: os.environ.get("EMAIL_PASSWORD", ""))
    email_receivers: list[str] = field(
        default_factory=lambda: _split_receivers(os.environ.get("EMAIL_RECEIVERS", ""))
    )

    # 可选：OpenAI 兼容接口（DeepSeek / 通义 / OpenAI 均可），不配则退回纯词库研判
    llm_api_base: str = field(default_factory=lambda: os.environ.get("LLM_API_BASE", ""))
    llm_api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", ""))

    @property
    def email_ready(self) -> bool:
        return bool(self.email_sender and self.email_password and self.email_receivers)

    @property
    def llm_ready(self) -> bool:
        return bool(self.llm_api_base and self.llm_api_key and self.llm_model)

    def validate(self) -> list[str]:
        """返回配置问题列表（空列表 = 通过）"""
        problems = []
        if not self.cookie:
            problems.append("未配置 WEIBO_COOKIE")
        if not self.email_ready:
            problems.append("邮件配置不完整（SENDER/PASSWORD/RECEIVERS），将跳过发信")
        return problems
