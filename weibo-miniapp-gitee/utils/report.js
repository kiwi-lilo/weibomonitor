const config = require("../config/index");

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function firstNonEmptyArray(data, keys) {
  for (let index = 0; index < keys.length; index += 1) {
    const value = asArray(data && data[keys[index]]);
    if (value.length) return value;
  }
  return [];
}

function cleanText(value) {
  return String(value == null ? "" : value).replace(/\s+/g, " ").trim();
}

function firstSentence(value) {
  const text = cleanText(value);
  const match = text.match(/^.*?[。！？!?]/);
  return cleanText(match ? match[0] : text);
}

function summaryRemainder(value) {
  const text = cleanText(value);
  const first = firstSentence(text);
  return first && text.indexOf(first) === 0 ? cleanText(text.slice(first.length)) : "";
}

function personalCopyText(item) {
  const sourceItem = item || {};
  const link = cleanText(sourceItem.url || sourceItem.link);
  let body = cleanText(sourceItem.summary || sourceItem.text || sourceItem.title).replace(/^△\s*/, "");
  if (link && body.slice(-link.length) === link) body = cleanText(body.slice(0, -link.length));

  const user = cleanText(sourceItem.user);
  const markers = [`（新浪微博：${user}）`, `（新浪微博:${user}）`];
  markers.forEach((marker) => {
    if (user && body.slice(-marker.length) === marker) body = cleanText(body.slice(0, -marker.length));
  });

  const source = user ? `（新浪微博：${user}）` : "";
  return `△${body}${source}${link}`.trim();
}

function genericCopyText(item) {
  const sourceItem = item || {};
  return [
    cleanText(sourceItem.copy_text || sourceItem.summary || sourceItem.text || sourceItem.title),
    cleanText(sourceItem.url || sourceItem.link)
  ].filter(Boolean).join("\n");
}

function withPersonalCopy(item) {
  return Object.assign({}, item, { copy_text: personalCopyText(item) });
}

function normalizePersonal(data) {
  const source = data && typeof data === "object" ? data : {};
  const items = firstNonEmptyArray(source, ["recommendations", "items"]).map(withPersonalCopy);
  const unsummarized = firstNonEmptyArray(source, ["unsummarized", "other_items", "unsummarized_items", "all"]).map(withPersonalCopy);
  const monitoredPosts = firstNonEmptyArray(source, ["monitored_posts", "posts", "all"]).map(withPersonalCopy);
  const newNegatives = firstNonEmptyArray(source, ["new_negatives"]).map(withPersonalCopy);
  const cities = asArray(source.cities);
  const stats = Object.assign({}, source.stats || {});

  if (stats.total_posts == null) stats.total_posts = monitoredPosts.length;
  if (stats.new_neg == null) stats.new_neg = newNegatives.length;
  if (stats.city_count == null) stats.city_count = cities.length;
  if (stats.healthy == null) {
    stats.healthy = cities.filter((city) => Number(city.new_neg || 0) === 0).length;
  }

  return Object.assign({}, source, {
    stats,
    cities,
    items,
    unsummarized,
    monitored_posts: monitoredPosts,
    new_negatives: newNegatives
  });
}

function normalizeMedia(data) {
  const source = data && typeof data === "object" ? data : {};
  const items = firstNonEmptyArray(source, ["items", "top10", "recommendations"]);
  const featured = firstNonEmptyArray(source, ["top10", "recommendations", "items"]);
  const rssCandidates = asArray(source.rss_candidates);
  const stats = Object.assign({}, source.stats || {});

  if (stats.verified == null) stats.verified = items.filter((item) => item.verified).length;
  if (stats.rss_candidates == null) stats.rss_candidates = rssCandidates.length;
  if (stats.summary_candidates == null) stats.summary_candidates = featured.length;

  return Object.assign({}, source, {
    stats,
    items,
    featured,
    rss_candidates: rssCandidates
  });
}

function normalizeReports(reports) {
  const source = reports || {};
  return {
    personal: source.personal ? normalizePersonal(source.personal) : null,
    media: source.media ? normalizeMedia(source.media) : null
  };
}

function makeKey(item, index, prefix) {
  return cleanText(item.id || item.url || item.link || `${prefix}-${index}`);
}

function padNumber(value) {
  return String(value).padStart(2, "0");
}

function itemLevel(item) {
  const label = cleanText(item.label || item.sentiment_label);
  if (/负面|关注/.test(label)) return "negative";
  if (/正面|正向/.test(label)) return "positive";
  return "neutral";
}

function makeIssue(item, index, personal) {
  const summary = cleanText(item.summary || item.text);
  const link = cleanText(item.url || item.link);
  const label = cleanText(item.label || item.sentiment_label || (personal ? "舆情" : "报道"));
  const heading = personal
    ? firstSentence(summary || item.title || "暂无摘要")
    : `${cleanText(item.media || "央媒")} · ${cleanText(item.title || "未命名报道")}`;
  const meta = personal
    ? [cleanText(item.region || item.city), cleanText(item.time)].filter(Boolean).join(" · ")
    : cleanText(item.time);

  return {
    key: makeKey(item, index, personal ? "personal" : "media"),
    indexLabel: padNumber(index + 1),
    heading,
    label,
    levelClass: itemLevel(item),
    meta,
    body: personal ? summaryRemainder(summary) : summary,
    author: personal && item.user ? `@${cleanText(item.user)}` : "",
    copyText: personal ? personalCopyText(item) : genericCopyText(item),
    link,
    hasLink: Boolean(link)
  };
}

function buildTabs(reports) {
  const personal = reports.personal;
  const media = reports.media;
  const personalCount = personal
    ? (asArray(personal.monitored_posts).length || Number((personal.stats || {}).total_posts || 0))
    : null;
  const mediaCount = media ? asArray(media.items).length : null;

  return [
    { id: "personal", label: "个人舆情", count: personalCount == null ? "--" : padNumber(personalCount) },
    { id: "media", label: "央媒涉陕", count: mediaCount == null ? "--" : padNumber(mediaCount) }
  ];
}

function buildMetrics(report, active) {
  const stats = (report && report.stats) || {};
  if (active === "personal") {
    return [
      { value: Number(stats.new_neg || 0), label: "新增负面", action: "new_negatives" },
      { value: Number(stats.total_posts || 0), label: "监测帖子", action: "monitored_posts" },
      { value: Number(stats.healthy || 0), label: "健康城市", action: "" },
      { value: Number(stats.city_count || 0), label: "覆盖城市", action: "" }
    ];
  }

  const items = report ? asArray(report.items) : [];
  return [
    { value: items.length, label: "有效报道", action: "" },
    { value: Number(stats.verified || 0), label: "原文核验", action: "" },
    { value: Number(stats.rss_candidates || 0), label: "RSS 候选", action: "rss_candidates" },
    { value: Number(stats.summary_candidates || 0), label: "精选候选", action: "" }
  ];
}

function filterValues(items, personal) {
  const seen = {};
  const values = [];
  items.forEach((item) => {
    const value = cleanText(personal ? (item.city || item.region || "其他") : (item.media || "其他")) || "其他";
    if (!seen[value]) {
      seen[value] = true;
      values.push(value);
    }
  });
  values.sort((left, right) => left.localeCompare(right, "zh-CN"));
  return values;
}

function buildFilters(items, personal, selectedFilter) {
  const values = filterValues(items, personal);
  const selected = values.indexOf(selectedFilter) >= 0 ? selectedFilter : "all";
  return {
    selected,
    filters: [
      { value: "all", label: personal ? "全部城市" : "全部媒体", selected: selected === "all" }
    ].concat(values.map((value) => ({ value, label: value, selected: value === selected })))
  };
}

function filterIssues(items, personal, selectedFilter, query) {
  const needle = cleanText(query).toLowerCase();
  return items.filter((item) => {
    const filterValue = cleanText(personal ? (item.city || item.region || "其他") : (item.media || "其他")) || "其他";
    const haystack = [item.city, item.media, item.title, item.summary, item.text, item.user, item.region]
      .map(cleanText)
      .join(" ")
      .toLowerCase();
    return (selectedFilter === "all" || filterValue === selectedFilter) && (!needle || haystack.indexOf(needle) >= 0);
  });
}

function buildVisual(report, active) {
  const personal = active === "personal";
  const stats = (report && report.stats) || {};
  const items = report ? asArray(report.items) : [];
  const total = personal ? Number(stats.total_posts || 0) : items.length;
  const focus = personal ? Number(stats.new_neg || 0) : Number(stats.verified || 0);
  const ratio = total ? Math.min(100, Math.round((focus / total) * 100)) : 0;
  let rows = [];

  if (personal) {
    rows = asArray(report && report.cities).map((city) => ({
      name: cleanText(city.city || "其他"),
      total: Number(city.total || 0),
      focus: Number(city.new_neg || 0)
    }));
  } else {
    const grouped = {};
    items.forEach((item) => {
      const name = cleanText(item.media || "其他") || "其他";
      grouped[name] = (grouped[name] || 0) + 1;
    });
    rows = Object.keys(grouped).map((name) => ({ name, total: grouped[name], focus: grouped[name] }));
  }

  rows.sort((left, right) => right.total - left.total);
  rows = rows.slice(0, 6);
  const max = Math.max.apply(null, [1].concat(rows.map((row) => row.total)));

  return {
    title: personal ? "城市态势" : "媒体态势",
    ratio,
    focusLabel: personal ? "新增关注" : "原文核验",
    totalLabel: personal ? "监测总量" : "有效报道",
    total,
    secondLabel: personal ? "健康城市" : "RSS 候选",
    secondValue: personal ? Number(stats.healthy || 0) : Number(stats.rss_candidates || 0),
    rows: rows.map((row) => ({
      name: row.name,
      detail: personal ? `${row.focus} 负面 / ${row.total} 条` : `${row.total} 条`,
      percent: Math.max(4, Math.round((row.total / max) * 100))
    }))
  };
}

function itemIdentity(item) {
  return cleanText(item.id || item.url || item.link || `${item.user || ""}${item.time || ""}${item.text || ""}`);
}

function makeSecondaryItem(item, index, personal) {
  const link = cleanText(item.url || item.link);
  return {
    key: makeKey(item, index, personal ? "other-personal" : "other-media"),
    title: cleanText(item.title || firstSentence(item.text || item.summary) || "未命名内容"),
    meta: personal
      ? [item.user ? `@${cleanText(item.user)}` : "用户未知", cleanText(item.time || "时间未知")].join(" · ")
      : [cleanText(item.media || "央媒"), cleanText(item.time || "时间未知")].join(" · "),
    link,
    hasLink: Boolean(link),
    copyText: personal ? personalCopyText(item) : genericCopyText(item)
  };
}

function buildSecondary(report, active) {
  if (!report) return { visible: false, title: "", label: "", countText: "", items: [] };
  const personal = active === "personal";
  let items;

  if (personal) {
    const recommended = {};
    asArray(report.items).forEach((item) => { recommended[itemIdentity(item)] = true; });
    items = asArray(report.unsummarized).filter((item) => !recommended[itemIdentity(item)]);
  } else {
    const featured = {};
    asArray(report.featured).forEach((item) => { featured[itemIdentity(item)] = true; });
    items = asArray(report.items).filter((item) => !featured[itemIdentity(item)]);
  }

  const visibleItems = items.slice(0, config.maxSecondaryItems).map((item, index) => makeSecondaryItem(item, index, personal));
  return {
    visible: visibleItems.length > 0,
    label: personal ? "UNSUMMARIZED SIGNALS" : "OTHER VERIFIED REPORTS",
    title: personal ? "其他新增舆情" : "其他有效报道",
    countText: `共 ${visibleItems.length} 条`,
    items: visibleItems
  };
}

function buildDashboard(reports, active, selectedFilter, query) {
  const normalized = normalizeReports(reports);
  const currentActive = active === "media" ? "media" : "personal";
  const report = normalized[currentActive];
  const personal = currentActive === "personal";
  const baseItems = report ? (personal ? asArray(report.items) : asArray(report.featured)) : [];
  const filterResult = buildFilters(baseItems, personal, selectedFilter || "all");
  const visibleItems = filterIssues(baseItems, personal, filterResult.selected, query);

  return {
    normalized,
    tabs: buildTabs(normalized).map((tab) => Object.assign({}, tab, { selected: tab.id === currentActive })),
    metrics: buildMetrics(report, currentActive),
    filters: filterResult.filters,
    selectedFilter: filterResult.selected,
    issues: visibleItems.map((item, index) => makeIssue(item, index, personal)),
    resultCount: `共 ${visibleItems.length} 条`,
    sectionLabel: personal ? "PERSONAL / 01" : "VERIFIED SOURCES / 02",
    panelTitle: personal ? "精选舆情" : "精选报道",
    updatedLine: report
      ? `${cleanText(report.period || "最新报告")} · 更新于 ${cleanText(report.updated_at || "未知时间")}`
      : "等待最新日报",
    visual: buildVisual(report, currentActive),
    secondary: buildSecondary(report, currentActive),
    hasReport: Boolean(report)
  };
}

function buildBrowser(reports, active, mode) {
  const normalized = normalizeReports(reports);
  const currentActive = active === "media" ? "media" : "personal";
  const rssMode = mode === "rss_candidates";
  const report = rssMode ? normalized.media : normalized.personal;
  let sourceItems = [];

  if (report) sourceItems = rssMode ? asArray(report.rss_candidates) : asArray(report[mode]);
  const items = sourceItems.slice(0, config.maxBrowserItems).map((item, index) => {
    const excerpt = rssMode ? "" : cleanText(item.excerpt || item.text || item.summary);
    const link = cleanText(item.url || item.link);
    const title = cleanText(item.title || firstSentence(excerpt) || "暂无标题");
    const meta = rssMode
      ? [cleanText(item.media || "央媒"), cleanText(item.time || "时间未知"), item.verified ? "已核验原文" : "待核验 RSS 跳转"].join(" · ")
      : [cleanText(item.city || item.region), cleanText(item.time), item.user ? `@${cleanText(item.user)}` : "", cleanText(item.label)].filter(Boolean).join(" · ");
    return {
      key: makeKey(item, index, "browser"),
      indexLabel: padNumber(index + 1),
      title,
      excerpt,
      meta,
      link,
      hasLink: Boolean(link),
      copyText: rssMode ? genericCopyText(item) : personalCopyText(item)
    };
  });

  return {
    visible: (rssMode && currentActive === "media") || (!rssMode && currentActive === "personal"),
    label: rssMode ? "RSS DISCOVERY" : "PERSONAL RECORDS",
    title: rssMode ? "RSS 候选标题" : (mode === "new_negatives" ? "新增负面" : "监测帖子"),
    countText: `共 ${items.length} 条`,
    items
  };
}

module.exports = {
  asArray,
  buildBrowser,
  buildDashboard,
  cleanText,
  firstSentence,
  genericCopyText,
  normalizeMedia,
  normalizePersonal,
  normalizeReports,
  personalCopyText,
  summaryRemainder
};

