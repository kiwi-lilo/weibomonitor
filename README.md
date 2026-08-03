# 陕西多市微博舆情监测 v5

每个工作日定时搜索微博上的负面民生反馈，研判分级后同时发送完整邮件日报与 Bark 推荐候选。

## 相对 v4 的主要变化
- **修复误报**：清除了混入强负面词库的中性连词"由于"；正面语境前置否决（整治/表彰类新闻不再判负面）
- **邮件完整日报**：保留 HTML 城市明细、今日推荐候选以及 CSV / JSON 附件
- **Bark 推荐候选**：每次推荐最多 10 条，分两条汇总推送；正文不截断，点击通知可在 Bark 中展开完整内容
- **不再假报平安**：Cookie 失效或接口全挂时中止运行，同时发送邮件与 Bark 异常告警，Actions 显示失败
- **按微博 id 去重** + **跨天记忆**（`state/seen.json`，Actions 用 cache 持久化）：日报只突出"新增"负面
- **推荐事件级去重**：不同用户转述同一地点、同一问题时，原始记录照常存档，但 Top 10 只保留一个代表事件
- **官方号两级过滤**：弱特征词（平安/青年/文明…）只对认证账号生效，减少误杀普通用户；被过滤内容留档到 JSON 供审计
- **提速**：关键词首页为空即跳过后续页
- **transformer 情感复核（GitHub 默认启用）**：Erlangshen-Roberta-110M 中文情感模型对全部微博打分并与词库结论融合，补漏报、消误报；依赖与模型均走 Actions 缓存，仅首次运行慢几分钟。模型不可用时自动降级为内置 lite 词典引擎（零依赖），词库始终保底
- **可选 LLM 复核**：配置 `LLM_API_BASE / LLM_API_KEY / LLM_MODEL`（任何 OpenAI 兼容接口，如 DeepSeek）后，对负面候选批量精判
- Python 3.12、logging、44 个回归测试

## 本地运行
```bash
pip install -r requirements.txt
export WEIBO_COOKIE="..."           # 必填
export EMAIL_SENDER="..." EMAIL_PASSWORD="..." EMAIL_RECEIVERS="a@x.com,b@y.com"
export BARK_URL="https://api.day.app/你的设备Key"
python main.py
pytest tests/ -v                    # 跑测试
```

## GitHub Actions
配置 Secrets：`WEIBO_COOKIE`、`SMTP_SERVER`、`SMTP_PORT`、`EMAIL_SENDER`、`EMAIL_PASSWORD`、`EMAIL_RECEIVERS`、`BARK_URL`，可选 `LLM_API_*`。
`BARK_URL` 填写 Bark App 中推送地址的前半段，例如 `https://api.day.app/你的设备Key`；自建 Bark 也填写包含设备 Key 的完整地址。可在 Actions Variables 中设置 `BARK_GROUP` 和 `BARK_ICON`。
默认每周一至周五北京时间 23:00 运行，也可手动触发。

## 阿里云央媒版

`index.py` 是无需第三方依赖的阿里云函数计算单文件版本。它会跨媒体合并同一新闻事件，排除天气、预警、灾害、事故等内容，只推荐能够体现陕西发展成效、创新实践、民生改善、文化生态或产业成果的正向报道。Top 10 通过邮件和 Bark 分两段发送。

## 增删城市
编辑 `cities.py` 的 `CITIES` 列表即可。已内置汉中、西安、宝鸡、咸阳，
文件里另附榆林/安康等备选的说明。所有城市汇总为一封邮件日报；Bark 将最多 10 条推荐合并为两条完整通知，并各存一份跨天状态。
当前 4 市每次约 46 分钟，GitHub 私有仓库 2000 分钟/月额度充裕。

## 词库维护
全部在 `keywords.py`。原则：搜索词求召回、研判词求精准；改完跑一遍测试防回归。
