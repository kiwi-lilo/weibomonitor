const personal = {
  source: "mock-personal",
  updated_at: "2026-08-08 09:30",
  period: "2026-08-06 ~ 2026-08-08",
  stats: {
    new_neg: 3,
    total_posts: 46,
    healthy: 2,
    city_count: 4
  },
  cities: [
    { city: "西安", total: 18, new_neg: 2 },
    { city: "汉中", total: 12, new_neg: 1 },
    { city: "宝鸡", total: 9, new_neg: 0 },
    { city: "咸阳", total: 7, new_neg: 0 }
  ],
  recommendations: [
    {
      id: "demo-p-1",
      city: "西安",
      region: "西安",
      time: "08-08 08:42",
      user: "演示用户A",
      label: "负面",
      summary: "某小区居民反映夜间施工噪声持续，希望有关部门尽快协调处理。现场情况仍需进一步核实。",
      url: "https://weibo.com/"
    },
    {
      id: "demo-p-2",
      city: "汉中",
      region: "汉中",
      time: "08-08 08:15",
      user: "演示用户B",
      label: "关注",
      summary: "网友反映公交站牌信息更新不及时。相关线路已经恢复，但站点提示仍需要完善。",
      url: "https://weibo.com/"
    },
    {
      id: "demo-p-3",
      city: "西安",
      region: "西安",
      time: "08-08 07:54",
      user: "演示用户C",
      label: "正面",
      summary: "市民表扬窗口工作人员耐心协助办理业务。现场秩序良好，办理过程顺畅。",
      url: "https://weibo.com/"
    }
  ],
  unsummarized: [
    {
      id: "demo-u-1",
      city: "宝鸡",
      time: "08-08 07:20",
      user: "演示用户D",
      text: "道路积水问题得到关注，等待后续处置反馈。",
      url: "https://weibo.com/"
    }
  ],
  monitored_posts: [
    {
      id: "demo-m-1",
      city: "西安",
      time: "08-08 08:42",
      user: "演示用户A",
      label: "负面",
      text: "某小区居民反映夜间施工噪声持续，希望有关部门尽快协调处理。",
      url: "https://weibo.com/"
    },
    {
      id: "demo-m-2",
      city: "汉中",
      time: "08-08 08:15",
      user: "演示用户B",
      label: "关注",
      text: "网友反映公交站牌信息更新不及时。",
      url: "https://weibo.com/"
    }
  ],
  new_negatives: [
    {
      id: "demo-n-1",
      city: "西安",
      time: "08-08 08:42",
      user: "演示用户A",
      label: "负面",
      text: "某小区居民反映夜间施工噪声持续，希望有关部门尽快协调处理。",
      url: "https://weibo.com/"
    }
  ]
};

const media = {
  source: "mock-media",
  updated_at: "2026-08-08 08:10",
  period: "最近 48 小时",
  stats: {
    verified: 6,
    rss_candidates: 12,
    summary_candidates: 3
  },
  items: [
    {
      id: "demo-news-1",
      media: "人民网",
      time: "08-08 07:45",
      title: "陕西持续完善公共服务设施",
      summary: "报道关注多地公共服务设施建设和便民服务举措。",
      link: "https://www.people.com.cn/",
      verified: true
    },
    {
      id: "demo-news-2",
      media: "新华网",
      time: "08-08 07:10",
      title: "重点项目建设稳步推进",
      summary: "报道梳理重点项目近期建设进展。",
      link: "https://www.news.cn/",
      verified: true
    },
    {
      id: "demo-news-3",
      media: "央视网",
      time: "08-07 20:30",
      title: "文旅消费场景不断丰富",
      summary: "报道介绍暑期文旅市场的新场景和新服务。",
      link: "https://www.cctv.com/",
      verified: true
    },
    {
      id: "demo-news-4",
      media: "光明网",
      time: "08-07 18:20",
      title: "基层治理服务进一步下沉",
      summary: "报道关注社区服务和基层协同治理。",
      link: "https://www.gmw.cn/",
      verified: true
    }
  ],
  top10: [
    {
      id: "demo-news-1",
      media: "人民网",
      time: "08-08 07:45",
      title: "陕西持续完善公共服务设施",
      summary: "报道关注多地公共服务设施建设和便民服务举措。",
      link: "https://www.people.com.cn/",
      verified: true
    },
    {
      id: "demo-news-2",
      media: "新华网",
      time: "08-08 07:10",
      title: "重点项目建设稳步推进",
      summary: "报道梳理重点项目近期建设进展。",
      link: "https://www.news.cn/",
      verified: true
    },
    {
      id: "demo-news-3",
      media: "央视网",
      time: "08-07 20:30",
      title: "文旅消费场景不断丰富",
      summary: "报道介绍暑期文旅市场的新场景和新服务。",
      link: "https://www.cctv.com/",
      verified: true
    }
  ],
  rss_candidates: [
    {
      id: "demo-rss-1",
      media: "中国新闻网",
      time: "08-08 06:40",
      title: "区域协同发展释放新活力",
      link: "https://www.chinanews.com.cn/",
      verified: false
    }
  ]
};

module.exports = { personal, media };

