"""cities.py — 监测城市配置（增删城市只改这里）

每个 City 的 regions 是 {区县全称: [搜索/匹配关键词]}。
· districts 属性自动派生出搜索用的区县词（每个区县取第一个关键词）
· all_region_kw 用于"正文必须提到本市某区县"的相关性过滤

想换城市：改 CITIES 列表即可。想临时停用某城市：注释掉那一项。
备选（复制格式即可加入）：
  榆林市（陕北能源重镇，煤矿/欠薪舆情高发）、安康市（陕南）、延安市、商洛市
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache


# 中文用户名后常直接接“请关注/求助”等正文，没有空格；在常见动作词前截断，
# 避免把后续的真实行政区名一并当成用户名吞掉。
_MENTION_RE = re.compile(
    r"(?<![A-Za-z0-9_.+-])@[^@\s:：,，。！？!?、/]{1,30}?"
    r"(?=请|求|望|转发|关注|反映|举报|曝光|归还|要求|：|:|[，。！？!?、\s]|$)"
)


@lru_cache(maxsize=16)
def _source_re(short: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?:陕西省?|{re.escape(short)}市?)"
        r"(?:网友|网民|市民|居民|用户|网警|媒体|发布|转发|关注)"
    )


@lru_cache(maxsize=16)
def _external_admin_re(region_names: tuple[str, ...]) -> re.Pattern[str]:
    names = "|".join(re.escape(name) for name in sorted(region_names, key=len, reverse=True))
    return re.compile(
        rf"(?P<prefix>[\u4e00-\u9fff]{{2,10}}(?:省|市|州|区|县|镇|旗))"
        rf"(?P<region>{names})"
    )


@lru_cache(maxsize=16)
def _external_city_alias_re(short: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?P<prefix>[\u4e00-\u9fff]{{2,10}}(?:省|市|州|区|县|镇|旗))"
        rf"(?P<alias>{re.escape(short)})(?:市|区|县|镇|路|街|门)"
    )


def _has_unblocked_occurrence(
    text: str,
    needle: str,
    blocked_spans: list[tuple[int, int]],
) -> bool:
    """判断关键词是否至少有一次不落在明确外地实体内部。"""
    if not needle:
        return False
    start = 0
    while True:
        start = text.find(needle, start)
        if start < 0:
            return False
        end = start + len(needle)
        if not any(left <= start and end <= right for left, right in blocked_spans):
            return True
        start = end


@dataclass(frozen=True)
class City:
    name: str                          # 全称，如 "汉中市"
    short: str                         # 简称，如 "汉中"（用于文件名/通知）
    regions: dict[str, tuple[str, ...]]  # {区县全称: (关键词, ...)}
    deny: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # deny 中的普通词义冲突可由完整行政区名覆盖。
    reject_terms: tuple[str, ...] = ()
    # reject_terms 中的明确外地实体优先屏蔽其覆盖的命中；若另有明确本地证据，
    # 仍保留未被外地实体覆盖的本地区域。
    anchor_required: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # anchor_required = {歧义简称: (属地锚点, ...)}。简称无锚点时不算匹配。

    @property
    def districts(self) -> list[str]:
        """搜索用的区县词：市本身 + 每个区县的首个关键词"""
        seen, out = set(), []
        for kws in self.regions.values():
            kw = kws[0]
            if kw not in seen:
                seen.add(kw)
                out.append(kw)
        return out

    @property
    def all_region_kw(self) -> list[str]:
        return sorted({kw for kws in self.regions.values() for kw in kws})

    def match_regions(self, text: str) -> list[str]:
        """带消歧的区县匹配。返回命中的区县全称列表（可能为空）。

        规则：@用户名不作为属地证据；普通关键词命中即算；anchor_required
        中的歧义简称必须同时命中其属地锚点；reject_terms 中的明确外地
        实体优先于同名命中，避免“牡丹江西安区”等外地同名误报；若同文
        另有未被外地实体覆盖的本地全称，则保留该本地命中。
        例：深圳宝安"西乡街道"的帖子含"西乡"但也含"深圳"，会被排除；
        "在深圳打工，老家西乡县…"因含锚定词"西乡县"仍保留。
        """
        location_text = _MENTION_RE.sub("", text or "")
        # “西安网友/陕西网友转发”是来源身份，不是事件属地；去掉后再做锚点判断。
        location_text = _source_re(self.short).sub("", location_text)
        # 搜索结果偶尔会在行政区之间插入空格；压缩空白后再检查明确外地实体。
        compact_location_text = re.sub(r"[\s\u3000]+", "", location_text)
        rejected_terms = tuple(
            normalized
            for term in self.reject_terms
            for normalized in (re.sub(r"[\s\u3000]+", "", term),)
            if normalized
        )
        blocked_spans: list[tuple[int, int]] = []
        for term in rejected_terms:
            start = 0
            while True:
                start = compact_location_text.find(term, start)
                if start < 0:
                    break
                blocked_spans.append((start, start + len(term)))
                start += len(term)
        # 未列入 reject_terms 的同名行政区也要识别，例如“郑州市新城区”。
        for match in _external_admin_re(tuple(self.regions)).finditer(compact_location_text):
            prefix = match.group("prefix")
            if ("陕西" not in prefix
                    and self.short not in prefix
                    and self.name not in prefix):
                blocked_spans.append((match.start(), match.end()))
        for match in _external_city_alias_re(self.short).finditer(compact_location_text):
            prefix = match.group("prefix")
            if ("陕西" not in prefix
                    and self.short not in prefix
                    and self.name not in prefix):
                blocked_spans.append((match.start(), match.end()))
        local_evidence = any(
            _has_unblocked_occurrence(compact_location_text, name, blocked_spans)
            for name in self.regions
        ) or _has_unblocked_occurrence(compact_location_text, self.short, blocked_spans)
        if blocked_spans and not local_evidence:
            return []
        out = []
        for name, kws in self.regions.items():
            for kw in kws:
                if kw not in location_text:
                    continue
                if blocked_spans and not _has_unblocked_occurrence(
                        compact_location_text, kw, blocked_spans):
                    continue
                if (name not in location_text and kw in self.deny
                        and any(term in location_text for term in self.deny[kw])):
                    continue
                required_anchors = self.anchor_required.get(kw)
                if (required_anchors
                        and not any(
                            _has_unblocked_occurrence(
                                compact_location_text, anchor, blocked_spans
                            )
                            for anchor in required_anchors
                        )):
                    continue
                out.append(name)
                break
        return out

# ══════════════ 陕西·榆林（陕北中心城市） ══════════════
YULIN = City("榆林市", "榆林", {
    "榆林市": ("榆林",),
    "榆阳区": ("榆阳",),
    "横山区": ("横山",),
    "神木市": ("神木",),
    "府谷县": ("府谷",),
    "靖边县": ("靖边",),
    "定边县": ("定边",),
    "绥德县": ("绥德",),
    "米脂县": ("米脂",),
    "佳县": ("佳县",),
    "吴堡县": ("吴堡",),
    "清涧县": ("清涧",),
    "子洲县": ("子洲",),
}, deny={
    "榆林": ("榆林路",),
    "定边": ("张定边", "确定边"),
}, reject_terms=(
    "榆林窟",
), anchor_required={
    "横山": ("陕西", "榆林", "横山区"),
})


# ══════════════ 陕西·汉中（原有） ══════════════
HANZHONG = City("汉中市", "汉中", {
    "汉中市": ("汉中",), "汉台区": ("汉台",), "南郑区": ("南郑",),
    "城固县": ("城固",), "洋县": ("洋县",), "西乡县": ("西乡",),
    "勉县": ("勉县",), "宁强县": ("宁强",), "略阳县": ("略阳",),
    "镇巴县": ("镇巴",), "留坝县": ("留坝",), "佛坪县": ("佛坪",),
}, deny={
    "汉中": ("汉中路", "汉中门"),
}, reject_terms=(
    # "西乡"重灾区：深圳宝安西乡街道、南宁西乡塘区（子串也含"西乡"）
    "南京汉中路", "南京市汉中路", "汉中门", "西乡街道", "西乡塘",
    "深圳西乡", "深圳市西乡", "深圳市宝安区西乡", "宝安西乡", "宝安区西乡",
    "南宁西乡", "南宁市西乡",
), anchor_required={
    "西乡": ("陕西", "汉中", "西乡县"),
})

# ══════════════ 陕西·西安（省会，声量最大；部分区县名较通用，噪声偏高） ══════════════
XIAN = City("西安市", "西安", {
    # 航天新城是西安本地项目名，但不属于行政上的新城区，单独归到市级。
    "西安市": ("西安", "航天新城"), "新城区": ("新城",), "碑林区": ("碑林",),
    "莲湖区": ("莲湖",), "灞桥区": ("灞桥",), "未央区": ("未央",),
    "雁塔区": ("雁塔",), "阎良区": ("阎良",), "临潼区": ("临潼",),
    "长安区": ("长安",), "高陵区": ("高陵",), "鄠邑区": ("鄠邑",),
    "蓝田县": ("蓝田",), "周至县": ("周至",),
}, deny={
    "西安": ("西安路", "西安街", "西安门"),
    "新城": ("航天新城",),
    "长安": ("长安汽车", "长安欧尚", "长安福特", "长安街"),
    "蓝田": ("蓝田玉",),
}, reject_terms=(
    # 完整名称在外地也成立，不能由“新城区/长安区”等字样反向放行。
    "牡丹江市西安区", "牡丹江西安区",
    "呼和浩特市新城区", "呼和浩特新城区", "察县新城区", "韩城市新城区", "韩城新城区",
    "东莞长安镇", "东莞市长安镇", "东莞长安区", "东莞市长安区", "长安镇",
    "石家庄市长安区", "石家庄长安区",
    # 转发外地项目时常保留本市账号名；这些完整前缀优先于“西安网友”等锚点。
    "北京三环新城", "丰台三环新城", "贵州普安县东方新城", "普安县东方新城",
    "外地新城", "异地新城",
    "桂林碑林", "焦山碑林",
), anchor_required={
    "新城": ("西安", "新城区"),
    "长安": ("陕西", "西安", "长安区"),
    "碑林": ("陕西", "西安", "碑林区"),
    "莲湖": ("陕西", "西安", "莲湖区"),
    "未央": ("陕西", "西安", "未央区"),
    "蓝田": ("陕西", "西安", "蓝田县"),
})

# ══════════════ 陕西·宝鸡（关中第二大城） ══════════════
BAOJI = City("宝鸡市", "宝鸡", {
    "宝鸡市": ("宝鸡",), "渭滨区": ("渭滨",), "金台区": ("金台",),
    "陈仓区": ("陈仓",), "凤翔区": ("凤翔",), "岐山县": ("岐山",),
    "扶风县": ("扶风",), "眉县": ("眉县",), "陇县": ("陇县",),
    "千阳县": ("千阳",), "麟游县": ("麟游",), "凤县": ("凤县",),
    "太白县": ("太白",),
}, deny={
    "宝鸡": ("宝鸡路",),
    "金台": ("金台资讯", "金台寺", "金台观"),
    "陈仓": ("暗度陈仓",),
    "岐山": ("岐山臊子", "岐山臊子面", "岐山面"),
    "扶风": ("弱柳扶风",),
    "太白": ("太白金星", "太白酒"),
}, reject_terms=(
    "太白湖", "山东岐山", "济宁岐山",
), anchor_required={
    "金台": ("陕西", "宝鸡", "金台区"),
    "陈仓": ("陕西", "宝鸡", "陈仓区"),
    "岐山": ("陕西", "宝鸡", "岐山县"),
    "扶风": ("陕西", "宝鸡", "扶风县"),
    "太白": ("陕西", "宝鸡", "太白县"),
})

# ══════════════ 陕西·咸阳（紧邻西安，关中核心） ══════════════
XIANYANG = City("咸阳市", "咸阳", {
    "咸阳市": ("咸阳",), "秦都区": ("秦都",), "渭城区": ("渭城",),
    "兴平市": ("兴平",), "彬州市": ("彬州",), "三原县": ("三原",),
    "泾阳县": ("泾阳",), "乾县": ("乾县",), "礼泉县": ("礼泉",),
    "永寿县": ("永寿",), "长武县": ("长武",), "旬邑县": ("旬邑",),
    "淳化县": ("淳化",), "武功县": ("武功",),
}, deny={
    "咸阳": ("咸阳路",),
    "渭城": ("渭城曲",),
    "三原": ("三原色",),
    "淳化": ("淳化元宝", "淳化阁帖"),
}, reject_terms=(
    "武功山", "外地渭城", "异地渭城",
), anchor_required={
    "渭城": ("陕西", "咸阳", "渭城区"),
    "三原": ("陕西", "咸阳", "三原县"),
    "永寿": ("陕西", "咸阳", "永寿县"),
    "淳化": ("陕西", "咸阳", "淳化县"),
    "武功": ("陕西", "咸阳", "武功县"),
})


# 实际监测的城市列表（增删/换序在此）
CITIES: list[City] = [YULIN, XIAN, BAOJI, XIANYANG]
