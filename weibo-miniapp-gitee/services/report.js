const config = require("../config/index");
const mockData = require("../mock/data");

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function isConfigured() {
  const gitee = config.gitee || {};
  return Boolean(
    gitee.owner &&
    gitee.repo &&
    !/^your-/i.test(gitee.owner) &&
    !/^your-/i.test(gitee.repo)
  );
}

function ensureConfigured() {
  if (!isConfigured()) {
    throw new Error("Gitee 数据源尚未配置");
  }
}

function buildRawUrl(fileName) {
  ensureConfigured();
  const gitee = config.gitee;
  const path = [gitee.owner, gitee.repo, "raw", gitee.branch || "master", fileName]
    .map((part) => encodeURIComponent(String(part)))
    .join("/");
  return `https://gitee.com/${path}?t=${Date.now()}`;
}

function parseJsonPayload(payload, fileName) {
  let value = payload;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch (error) {
      throw new Error(`${fileName} 不是有效 JSON`);
    }
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${fileName} 数据格式不正确`);
  }
  return value;
}

function requestFile(fileName) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: buildRawUrl(fileName),
      method: "GET",
      dataType: "json",
      timeout: config.requestTimeout,
      header: {
        Accept: "application/json",
        "Cache-Control": "no-cache"
      },
      success(response) {
        if (response.statusCode < 200 || response.statusCode >= 300) {
          reject(new Error(`${fileName} 请求失败（${response.statusCode}）`));
          return;
        }
        try {
          resolve(parseJsonPayload(response.data, fileName));
        } catch (error) {
          reject(error);
        }
      },
      fail(error) {
        reject(new Error(`${fileName} 请求失败：${error.errMsg || "网络异常"}`));
      }
    });
  });
}

function settle(promise) {
  return promise.then(
    (value) => ({ status: "fulfilled", value }),
    (reason) => ({ status: "rejected", reason })
  );
}

function readCache() {
  try {
    const value = wx.getStorageSync(config.cacheKey);
    if (!value || !value.reports) return null;
    return value;
  } catch (error) {
    return null;
  }
}

function writeCache(reports) {
  try {
    wx.setStorageSync(config.cacheKey, {
      savedAt: Date.now(),
      reports
    });
  } catch (error) {
    // A cache failure must not block fresh report data.
  }
}

function loadMockReports() {
  return Promise.resolve({
    reports: clone(mockData),
    errors: [],
    source: "mock",
    usedCache: false
  });
}

async function loadGiteeReports() {
  ensureConfigured();
  const gitee = config.gitee;
  const cached = readCache();
  const results = await Promise.all([
    settle(requestFile(gitee.personalFile || "personal.json")),
    settle(requestFile(gitee.mediaFile || "media.json"))
  ]);
  const names = ["personal", "media"];
  const reports = {};
  const errors = [];
  let freshCount = 0;

  results.forEach((result, index) => {
    const name = names[index];
    if (result.status === "fulfilled") {
      reports[name] = result.value;
      freshCount += 1;
      return;
    }
    if (cached && cached.reports && cached.reports[name]) {
      reports[name] = cached.reports[name];
    } else {
      reports[name] = null;
    }
    errors.push(result.reason.message || `${name} 加载失败`);
  });

  if (!reports.personal && !reports.media) {
    throw new Error(errors.join("；") || "日报加载失败");
  }

  if (freshCount) writeCache(reports);
  return {
    reports,
    errors,
    source: errors.length ? "partial" : "gitee",
    usedCache: errors.length > 0 && Boolean(cached)
  };
}

function loadReports() {
  return config.dataMode === "mock" ? loadMockReports() : loadGiteeReports();
}

module.exports = {
  buildRawUrl,
  isConfigured,
  loadReports,
  parseJsonPayload,
  readCache
};

