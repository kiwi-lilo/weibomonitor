"""local_model.py — 本地中文情感模型（可选，免费）

默认模型：IDEA-CCNL/Erlangshen-Roberta-110M-Sentiment
  · 400MB 左右，纯 CPU 推理，一条微博约几十毫秒
  · 首次运行自动下载并缓存到 ~/.cache/huggingface

启用条件：装了 torch + transformers 即自动启用（见 requirements-model.txt）。
未安装时自动跳过，不影响主流程。

环境变量：
  LOCAL_MODEL=0                       # 强制关闭
  LOCAL_MODEL_NAME=...                # 换其他 HuggingFace 情感模型
  HF_ENDPOINT=https://hf-mirror.com   # 国内下载加速（本地运行建议配置）
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

MODEL_NAME = os.environ.get("LOCAL_MODEL_NAME",
                            "IDEA-CCNL/Erlangshen-Roberta-110M-Sentiment")

_pipe = None          # (tokenizer, model, torch) 缓存
_load_failed = False


def available() -> bool:
    """torch + transformers 可导入且未被禁用"""
    if os.environ.get("LOCAL_MODEL", "1") == "0":
        return False
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except ImportError:
        return False


def _load():
    global _pipe, _load_failed
    if _pipe is not None or _load_failed:
        return _pipe
    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        log.info("加载本地情感模型 %s（首次运行需下载约400MB）…", MODEL_NAME)
        tok = AutoTokenizer.from_pretrained(MODEL_NAME)
        mdl = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
        mdl.eval()
        _pipe = (tok, mdl, torch)
        log.info("本地情感模型加载完成")
    except Exception as e:  # 下载失败/内存不足等，一律降级
        log.warning("本地情感模型加载失败，跳过模型复核: %s", e)
        _load_failed = True
    return _pipe


def score_texts(texts: list[str], batch_size: int = 32) -> list[float] | None:
    """返回每条文本的负面概率 P(负面) ∈ [0,1]；模型不可用时返回 None。

    Erlangshen-Sentiment 的标签约定: index 0 = Negative, 1 = Positive
    """
    if not texts or not available():
        return None
    pipe = _load()
    if pipe is None:
        return None
    tok, mdl, torch = pipe
    scores: list[float] = []
    try:
        with torch.no_grad():
            for i in range(0, len(texts), batch_size):
                batch = [t[:200] for t in texts[i:i + batch_size]]
                enc = tok(batch, truncation=True, max_length=128,
                          padding=True, return_tensors="pt")
                logits = mdl(**enc).logits
                probs = torch.softmax(logits, dim=-1)
                scores.extend(probs[:, 0].tolist())   # P(Negative)
        return scores
    except Exception as e:
        log.warning("本地模型推理失败，跳过: %s", e)
        return None
