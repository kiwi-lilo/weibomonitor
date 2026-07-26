# 汉中市微博舆情监测 v5

每日定时搜索微博上关于汉中市及各区县的负面民生反馈，研判分级后邮件推送日报。

## 相对 v4 的主要变化
- **修复误报**：清除了混入强负面词库的中性连词"由于"；正面语境前置否决（整治/表彰类新闻不再判负面）
- **不再假报平安**：Cookie 失效或接口全挂时中止运行、发送异常告警邮件，Actions 显示失败
- **按微博 id 去重** + **跨天记忆**（`state/seen.json`，Actions 用 cache 持久化）：日报只突出"新增"负面
- **官方号两级过滤**：弱特征词（平安/青年/文明…）只对认证账号生效，减少误杀普通用户；被过滤内容留档到 JSON 供审计
- **提速**：关键词首页为空即跳过后续页
- **HTML 报告 Jinja2 自动转义**，报告含"采集健康度"一节
- **transformer 情感复核（GitHub 默认启用）**：Erlangshen-Roberta-110M 中文情感模型对全部微博打分并与词库结论融合，补漏报、消误报；依赖与模型均走 Actions 缓存，仅首次运行慢几分钟。模型不可用时自动降级为内置 lite 词典引擎（零依赖），词库始终保底
- **可选 LLM 复核**：配置 `LLM_API_BASE / LLM_API_KEY / LLM_MODEL`（任何 OpenAI 兼容接口，如 DeepSeek）后，对负面候选批量精判
- Python 3.12、logging、17 个回归测试

## 本地运行
```bash
pip install -r requirements.txt
export WEIBO_COOKIE="..."           # 必填
export EMAIL_SENDER=... EMAIL_PASSWORD=... EMAIL_RECEIVERS=a@x.com,b@y.com
python main.py
pytest tests/ -v                    # 跑测试
```

## GitHub Actions
配置 Secrets：`WEIBO_COOKIE`、`SMTP_SERVER`、`SMTP_PORT`、`EMAIL_SENDER`、`EMAIL_PASSWORD`、`EMAIL_RECEIVERS`，可选 `LLM_API_*`。
默认每天北京时间 23:00 运行，也可手动触发。

## 词库维护
全部在 `keywords.py`。原则：搜索词求召回、研判词求精准；改完跑一遍测试防回归。
