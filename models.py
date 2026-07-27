"""models.py — 数据模型"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class Weibo:
    id: str
    user: str
    text: str
    time: str                       # "YYYY-MM-DD HH:MM"
    url: str
    keyword: str
    verified: bool = False
    verified_type: int = -1
    verified_reason: str = ""
    followers: int = 0
    reposts: int = 0
    comments: int = 0
    likes: int = 0

    # 研判结果（analyze 之后填充）
    sentiment_label: str = "中性"
    sentiment_score: float = 0.5
    strong_neg: list[str] = field(default_factory=list)
    medium_neg: list[str] = field(default_factory=list)
    mild_neg: list[str] = field(default_factory=list)
    positive_ctx: list[str] = field(default_factory=list)
    llm_reason: str = ""            # LLM 复核理由（启用时）
    model_score: float | None = None  # 本地模型负面概率（启用时）
    regions: list[str] = field(default_factory=list)
    is_new: bool = True             # 相对历史 seen 是否新增

    @property
    def heat(self) -> int:
        return self.reposts * 3 + self.comments * 2 + self.likes

    @property
    def user_type(self) -> str:
        return "个人认证(黄V)" if self.verified_type == 0 else "普通用户"

    @property
    def is_negative(self) -> bool:
        return self.sentiment_label in ("负面", "偏负面", "关注")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["heat"] = self.heat
        d["user_type"] = self.user_type
        return d
# --- models.py 中 Weibo 类的末尾 ---
    positive_ctx: list[str] = field(default_factory=list)
    llm_reason: str = ""            # LLM 复核理由
    model_score: float | None = None  # 本地模型负面概率
    regions: list[str] = field(default_factory=list)
    is_new: bool = True             # 相对历史 seen 是否新增
    
    # ✅ 新增这行：专供领导专报的单句总结
    summary: str = ""