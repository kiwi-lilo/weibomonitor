# 微博舆情监测

每日定时搜索微博上关于**市及各区县的负面民生反馈，研判分级后邮件推送日报。

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
