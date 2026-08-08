# 陕西舆情工作台小程序（Gitee 版）

这是原 `weibomonitor` 仓库中的独立原生微信小程序目录。现有微博监测、阿里云函数和 GitHub Pages 页面继续保留；Gitee 同步工具放在独立的 `aliyun-opinion-report` 仓库中。

数据链路：

```text
现有 GitHub Pages personal.json / media.json
                    ↓ aliyun-opinion-report 的 Actions 定时同步
              Gitee 公开数据仓库
                    ↓ wx.request
                 微信小程序
```

## 已实现功能

- 个人舆情和央媒涉陕切换
- 统计指标和指标明细展开
- 城市、媒体筛选和关键词搜索
- 精选列表、其他新增内容和 RSS 候选
- 摘要、完整内容和原文链接复制
- 城市、媒体态势条
- 下拉刷新、单项数据失败容错和本地缓存
- 演示数据模式，未配置 Gitee 时也可以直接预览

个人主体小程序不能使用 `web-view`，因此原文操作采用“复制链接”。

## 1. 立即预览

1. 打开微信开发者工具。
2. 选择“导入项目”。
3. 项目目录选择本文件夹。
4. 使用测试号，或者把 `project.config.json` 中的 `touristappid` 换成自己的 AppID。
5. 编译后会显示演示数据。

当前 [`config/index.js`](config/index.js) 使用：

```js
dataMode: "mock"
```

## 2. 创建 Gitee 数据仓库

1. 在 Gitee 新建一个**公开仓库**，例如 `weibo-report-data`。
2. 初始化仓库，并确认默认分支是 `master` 或 `main`。
3. 在 Gitee 创建私人令牌，赋予该数据仓库的写入权限。

公开仓库是零服务器成本方案的前提。任何人只要知道地址，就能读取其中的日报 JSON；不要上传 Cookie、AppSecret、API Key 或其他凭据。

## 3. 启用自动同步

Gitee 同步不在小程序目录中运行，操作说明在另一个仓库的 [`GITEE_SYNC.md`](../../aliyun-opinion-report/GITEE_SYNC.md)：

进入 `aliyun-opinion-report` 仓库的 GitHub Actions，手动运行一次“同步舆情数据到 Gitee”。成功后检查下面两个地址能否直接返回 JSON：

```text
https://gitee.com/你的用户名/weibo-report-data/raw/master/personal.json
https://gitee.com/你的用户名/weibo-report-data/raw/master/media.json
```

定时任务会在工作日北京时间 `08:15` 和 `09:00` 各同步一次。第二次用于覆盖上游 GitHub Actions 偶发延迟。同步内容没有变化时不会创建无意义的 Gitee 提交。

## 4. 切换到真实数据

修改 [`config/index.js`](config/index.js)：

```js
module.exports = {
  dataMode: "gitee",
  gitee: {
    owner: "你的 Gitee 用户名",
    repo: "weibo-report-data",
    branch: "master",
    personalFile: "personal.json",
    mediaFile: "media.json"
  },
  requestTimeout: 12000,
  cacheKey: "weibo-miniapp-report-cache-v1",
  maxBrowserItems: 100,
  maxSecondaryItems: 10
};
```

如果 Gitee 默认分支是 `main`，同步工作流变量和小程序配置必须同时改成 `main`。

## 5. 配置微信请求域名

在微信公众平台进入：

```text
开发管理 → 开发设置 → 服务器域名 → request 合法域名
```

添加：

```text
https://gitee.com
```

开发者工具中的“不校验合法域名”只能用于本地调试，不能替代后台配置。Gitee 属于第三方共享域名，能否添加最终以微信公众平台后台当时的校验结果为准。

## 6. 给少量用户体验

1. 在微信开发者工具中上传代码。
2. 在小程序后台把上传版本设为体验版。
3. 在成员管理中添加需要查看的微信号为体验成员。
4. 把体验版二维码发给这些成员。

这条路线不需要把小程序公开给所有用户。注意：体验成员限制的是小程序入口，Gitee 中的公开 JSON 本身仍然是公开数据。

## 本地验证

小程序项目没有第三方运行时依赖：

```bash
npm test
```

测试会验证报告标准化、筛选、搜索、复制文本、明细列表和 Gitee 同步数据校验。

## 常见问题

### 小程序提示“Gitee 数据源尚未配置”

确认 `dataMode` 已改为 `gitee`，并替换了 `owner`、`repo` 和 `branch`。

### 请求返回 404

确认 Gitee 仓库是公开仓库，分支名正确，并且两个 JSON 已由同步任务创建。

### 只有一类报告能打开

小程序会保留另一类报告的本地缓存，并在页面顶部显示具体错误。先在浏览器中分别检查两个 Gitee raw 地址。

### 原文为什么不能直接打开

个人主体小程序不支持通用 `web-view`，而微博和央媒链接分属多个外部域名，因此统一采用复制链接，避免发布或体验时出现域名拦截。
