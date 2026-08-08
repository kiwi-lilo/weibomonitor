const assert = require("assert");
const config = require("../config/index");
const mock = require("../mock/data");
const reports = require("../utils/report");
const reportService = require("../services/report");

const normalized = reports.normalizeReports(mock);
assert.strictEqual(normalized.personal.items.length, 3);
assert.strictEqual(normalized.media.featured.length, 3);
assert.strictEqual(normalized.personal.stats.total_posts, 46);

const personalView = reports.buildDashboard(mock, "personal", "西安", "施工");
assert.strictEqual(personalView.selectedFilter, "西安");
assert.strictEqual(personalView.issues.length, 1);
assert.ok(personalView.issues[0].copyText.startsWith("△"));
assert.ok(personalView.filters.some((item) => item.value === "汉中"));
assert.strictEqual(personalView.visual.rows[0].name, "西安");

const mediaView = reports.buildDashboard(mock, "media", "all", "项目");
assert.strictEqual(mediaView.issues.length, 1);
assert.strictEqual(mediaView.issues[0].levelClass, "neutral");
assert.strictEqual(mediaView.secondary.items.length, 1);

const browser = reports.buildBrowser(mock, "personal", "monitored_posts");
assert.strictEqual(browser.visible, true);
assert.strictEqual(browser.items.length, 2);
assert.ok(browser.items[0].copyText.includes("新浪微博"));

assert.strictEqual(
  reports.summaryRemainder("第一句。第二句。"),
  "第二句。"
);

assert.strictEqual(reportService.isConfigured(), false);
config.gitee.owner = "demo-owner";
config.gitee.repo = "demo-repo";
const rawUrl = reportService.buildRawUrl("personal.json");
assert.ok(rawUrl.startsWith("https://gitee.com/demo-owner/demo-repo/raw/master/personal.json?t="));
assert.deepStrictEqual(reportService.parseJsonPayload('{"stats":{}}', "demo.json"), { stats: {} });

console.log("report.test.js: all assertions passed");
