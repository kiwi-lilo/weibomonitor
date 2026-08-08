module.exports = {
  // Keep "mock" for an immediate preview. Change it to "gitee" after setup.
  dataMode: "mock",

  gitee: {
    owner: "your-gitee-account",
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

