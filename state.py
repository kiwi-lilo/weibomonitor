"""state.py — 跨天状态（每个城市各一份已见微博 id）

作用：同一条求助贴不再连续多天出现在"新增负面"里。
文件路径 state/seen_{城市简称}.json，GitHub Actions 用 cache 持久化整个 state/ 目录。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from config import STATE_DIR, SEEN_MAX, TZ

log = logging.getLogger(__name__)


def _path(city_short: str) -> str:
    return os.path.join(STATE_DIR, f"seen_{city_short}.json")


def load_seen(city_short: str) -> set[str]:
    path = _path(city_short)
    if not os.path.exists(path):
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        ids = set(data.get("ids", []))
        log.info("[%s] 载入历史 seen: %d 条 (更新于 %s)",
                 city_short, len(ids), data.get("updated", "?"))
        return ids
    except (OSError, ValueError) as e:
        log.warning("[%s] seen 状态读取失败，按空处理: %s", city_short, e)
        return set()


def save_seen(city_short: str, seen: set[str]) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    path = _path(city_short)
    ids = list(seen)[-SEEN_MAX:]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"ids": ids,
                   "updated": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")},
                  f, ensure_ascii=False)
    os.replace(tmp, path)
    log.info("[%s] 保存 seen: %d 条", city_short, len(ids))
