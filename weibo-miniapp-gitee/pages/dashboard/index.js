const config = require("../../config/index");
const reportService = require("../../services/report");
const reportUtils = require("../../utils/report");

Page({
  data: {
    activeTab: "personal",
    selectedFilter: "all",
    query: "",
    loading: true,
    refreshing: false,
    fatalError: "",
    warnings: [],
    statusText: "正在读取日报",
    statusKind: "loading",
    sourceBadge: config.dataMode === "mock" ? "演示" : "Gitee",
    tabs: [
      { id: "personal", label: "个人舆情", count: "--", selected: true },
      { id: "media", label: "央媒涉陕", count: "--", selected: false }
    ],
    updatedLine: "等待最新日报",
    sectionLabel: "PERSONAL / 01",
    panelTitle: "精选舆情",
    resultCount: "共 0 条",
    metrics: [],
    filters: [],
    issues: [],
    visual: {
      title: "城市态势",
      ratio: 0,
      focusLabel: "新增关注",
      totalLabel: "监测总量",
      total: 0,
      secondLabel: "健康城市",
      secondValue: 0,
      rows: []
    },
    secondary: { visible: false, items: [] },
    browser: { visible: false, items: [] }
  },

  onLoad() {
    this.reports = { personal: null, media: null };
    this.loadMeta = { source: config.dataMode === "mock" ? "mock" : "gitee", errors: [] };

    if (config.dataMode === "gitee") {
      const cached = reportService.readCache();
      if (cached && cached.reports) {
        this.reports = cached.reports;
        this.loadMeta = { source: "cache", errors: [] };
        this.renderDashboard();
      }
    }

    this.refreshReports({ showLoading: !this.reports.personal && !this.reports.media });
  },

  onPullDownRefresh() {
    this.refreshReports({ pullDown: true });
  },

  onShareAppMessage() {
    return {
      title: "陕西舆情工作台",
      path: "/pages/dashboard/index"
    };
  },

  async refreshReports(options) {
    const settings = options || {};
    this.setData({
      loading: Boolean(settings.showLoading),
      refreshing: true,
      fatalError: ""
    });

    try {
      const result = await reportService.loadReports();
      this.reports = result.reports;
      this.loadMeta = { source: result.source, errors: result.errors || [], usedCache: result.usedCache };
      this.renderDashboard();
    } catch (error) {
      const hasExistingData = Boolean(this.reports.personal || this.reports.media);
      this.loadMeta = { source: hasExistingData ? "cache" : "error", errors: [error.message || "日报加载失败"] };
      if (hasExistingData) {
        this.renderDashboard();
      } else {
        this.setData({
          fatalError: error.message || "日报加载失败",
          statusText: "数据加载失败",
          statusKind: "error"
        });
      }
    } finally {
      this.setData({ loading: false, refreshing: false });
      if (settings.pullDown) wx.stopPullDownRefresh();
    }
  },

  renderDashboard() {
    const view = reportUtils.buildDashboard(
      this.reports,
      this.data.activeTab,
      this.data.selectedFilter,
      this.data.query
    );
    this.reports = view.normalized;

    const source = this.loadMeta.source;
    const statusMap = {
      mock: ["演示数据", "mock", "演示"],
      gitee: ["数据已同步", "online", "Gitee"],
      partial: ["部分数据来自缓存", "warning", "缓存"],
      cache: ["正在显示本地缓存", "warning", "缓存"],
      error: ["数据加载失败", "error", "异常"]
    };
    const status = statusMap[source] || statusMap.gitee;

    this.setData({
      tabs: view.tabs,
      metrics: view.metrics,
      filters: view.filters,
      selectedFilter: view.selectedFilter,
      issues: view.issues,
      resultCount: view.resultCount,
      sectionLabel: view.sectionLabel,
      panelTitle: view.panelTitle,
      updatedLine: view.updatedLine,
      visual: view.visual,
      secondary: view.secondary,
      warnings: this.loadMeta.errors || [],
      statusText: status[0],
      statusKind: status[1],
      sourceBadge: status[2],
      fatalError: ""
    });
  },

  onTabTap(event) {
    const activeTab = event.currentTarget.dataset.tab;
    if (!activeTab || activeTab === this.data.activeTab) return;
    this.setData({
      activeTab,
      selectedFilter: "all",
      query: "",
      browser: { visible: false, items: [] }
    });
    this.renderDashboard();
  },

  onFilterTap(event) {
    const selectedFilter = event.currentTarget.dataset.filter || "all";
    this.setData({ selectedFilter });
    this.renderDashboard();
  },

  onSearchInput(event) {
    this.setData({ query: event.detail.value || "" });
    this.renderDashboard();
  },

  onClearSearch() {
    this.setData({ query: "" });
    this.renderDashboard();
  },

  onMetricTap(event) {
    const mode = event.currentTarget.dataset.action;
    if (!mode) return;
    const browser = reportUtils.buildBrowser(this.reports, this.data.activeTab, mode);
    this.setData({ browser });
    setTimeout(() => {
      wx.pageScrollTo({ selector: "#record-browser", duration: 250 });
    }, 30);
  },

  onCloseBrowser() {
    this.setData({ browser: { visible: false, items: [] } });
  },

  onRefreshTap() {
    if (!this.data.refreshing) this.refreshReports({ showLoading: false });
  },

  onRetry() {
    this.refreshReports({ showLoading: true });
  },

  onCopyIssue(event) {
    const item = this.data.issues[Number(event.currentTarget.dataset.index)];
    this.copyValue(item && item.copyText, "摘要已复制");
  },

  onCopyIssueLink(event) {
    const item = this.data.issues[Number(event.currentTarget.dataset.index)];
    this.copyValue(item && item.link, "链接已复制");
  },

  onCopySecondary(event) {
    const item = this.data.secondary.items[Number(event.currentTarget.dataset.index)];
    this.copyValue(item && item.copyText, "内容已复制");
  },

  onCopySecondaryLink(event) {
    const item = this.data.secondary.items[Number(event.currentTarget.dataset.index)];
    this.copyValue(item && item.link, "链接已复制");
  },

  onCopyBrowser(event) {
    const item = this.data.browser.items[Number(event.currentTarget.dataset.index)];
    this.copyValue(item && item.copyText, "内容已复制");
  },

  onCopyBrowserLink(event) {
    const item = this.data.browser.items[Number(event.currentTarget.dataset.index)];
    this.copyValue(item && item.link, "链接已复制");
  },

  copyValue(value, successTitle) {
    if (!value) {
      wx.showToast({ title: "没有可复制的内容", icon: "none" });
      return;
    }
    wx.setClipboardData({
      data: String(value),
      success() {
        wx.showToast({ title: successTitle, icon: "success", duration: 1200 });
      },
      fail() {
        wx.showToast({ title: "复制失败", icon: "none" });
      }
    });
  }
});

