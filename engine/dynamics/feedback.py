"""Feedback — 事件因果链的正/负反馈分类 (§31).

event_links 记录 cause → effect。当 effect 是"恢复型"事件（补充资源、重建秩序），
该链接为 negative feedback（稳定化）；否则为 positive feedback（放大）。
"""

from __future__ import annotations

# 恢复 / 稳定型事件类型 → 负反馈（抵消扰动）
NEGATIVE_FEEDBACK_TYPES = {
    "government_response",
    "resource_boom",
    "technology_breakthrough",
    "alliance",
    "recovery",
    "food_stabilization",
    "reform",
}

# 放大型事件类型 → 正反馈（加剧扰动）
POSITIVE_FEEDBACK_TYPES = {
    "protest",
    "conflict",
    "war",
    "market_panic",
    "scandal",
    "food_shortage",
    "economic_crisis",
    "political_movement",
    "migration",
}


def classify_link(effect_type: str) -> str:
    """将一个因果链接按 effect 类型分类为 positive / negative / neutral feedback。"""
    if effect_type in NEGATIVE_FEEDBACK_TYPES:
        return "negative"
    if effect_type in POSITIVE_FEEDBACK_TYPES:
        return "positive"
    return "neutral"


def summarize(chain) -> dict:
    """统计事件链中正/负反馈链接的数量。"""
    pos = neg = neutral = 0
    for cause, effect in chain.links:
        e = chain.get(effect)
        if e is None:
            continue
        kind = classify_link(e.type)
        if kind == "positive":
            pos += 1
        elif kind == "negative":
            neg += 1
        else:
            neutral += 1
    return {"positive": pos, "negative": neg, "neutral": neutral}
