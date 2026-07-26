"""state.py — 跨天状态（已见微博 id）

作用：同一条求助贴不再连续多天出现在"新增负面"里。
在 GitHub Actions 中配合 actions/cache 持久化（见 workflow）。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from config import STATE_FILE, SEEN_MAX, TZ

log = logging.getLogger(__name__)


def load_seen() -> set[str]:
    if not os.path.exists(STATE_FILE):
        return set()
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        ids = set(data.get("ids", []))
        log.info("载入历史 seen: %d 条 (更新于 %s)", len(ids), data.get("updated", "?"))
        return ids
    except (OSError, ValueError) as e:
        log.warning("seen 状态读取失败，按空处理: %s", e)
        return set()


def save_seen(seen: set[str]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    ids = list(seen)[-SEEN_MAX:]
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"ids": ids,
                   "updated": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")},
                  f, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)
    log.info("保存 seen: %d 条", len(ids))
