"""模糊印象层：主题 × 提及频率（方案：LLM 顺带返回主题，规则提取兜底）。

真人不会逐字记住所有对话，但对反复出现的主题形成强印象：
- 每次提及 ``mention_count += 1``；
- 权重 = ``log2(1 + 次数) × 0.5 ** (距上次提及天数 / 半衰期)``——
  提得越多印象越深，长期不提自然淡忘；
- 次数不足阈值不注入（只提过一两次的闲聊不留印象）。

规则提取（``extract_topics``）只是 mock / LLM 失败时的降级路径：
按停用词与标点切段，保留 ≥2 字的片段，去重后截前 3 个——
对无分隔的连续中文无能为力，正式路径走 LLM 顺带返回的 ``topics``。
"""

from __future__ import annotations

import math
import re

from app.config import get_settings

# 常见口语填充/功能词：切段基准（按需扩充）。
_STOPWORDS = frozenset(
    """
    我 你 他 她 它 我们 你们 他们 她们 的 了 是 在 和 都 很 也 就 还 要 想
    有 个 吗 呢 啊 吧 嗯 嗯嗯 好的 今天 明天 昨天 最近 还是 然后 但是 因为
    所以 如果 说说 说 讲讲 讲 聊聊 聊 谈谈 谈 问问 问 事情 话题 这个 那个
    什么 时候 一样 起来 觉得 知道 可以 应该 不是 就是 但是 有点 比较
    """.split()
)

_SPLIT_PATTERN = re.compile(
    r"[\s，。、！？；：,!?;:\"'（）()\[\]【】《》—…·]+"
)

MAX_TOPICS = 3


def extract_topics(text: str, *, max_topics: int = MAX_TOPICS) -> list[str]:
    """规则降级提取：切段 → 去停用词 → 保留 ≥2 字 → 去重截断。"""
    topics: list[str] = []
    for segment in _SPLIT_PATTERN.split(text):
        for run in _remove_stopwords(segment):
            if len(run) >= 2 and run not in topics:
                topics.append(run)
    return topics[:max_topics]


def _remove_stopwords(segment: str) -> list[str]:
    """把一段无标点文本按停用词切成碎片；停用词本身丢弃。"""
    if not segment:
        return []
    pieces: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(segment):
        for word in sorted(_STOPWORDS, key=len, reverse=True):
            if segment.startswith(word, index):
                if current:
                    pieces.append("".join(current))
                    current = []
                index += len(word)
                break
        else:
            current.append(segment[index])
            index += 1
    if current:
        pieces.append("".join(current))
    return [piece for piece in pieces if piece]


def impression_weight(
    *,
    mention_count: int,
    last_seen_days_ago: float,
    half_life_days: float | None = None,
) -> float:
    """主题印象权重：log 增长 × 半衰期衰减。"""
    if half_life_days is None:
        half_life_days = get_settings().memory_impression_half_life_days
    decay = 0.5 ** (max(0.0, last_seen_days_ago) / max(half_life_days, 1e-9))
    return math.log2(1 + max(0, mention_count)) * decay


def tier_of(
    mention_count: int,
    *,
    faint_threshold: int | None = None,
    deep_threshold: int = 5,
) -> str | None:
    """注入档位：None（不注入）| faint（有点印象）| deep（印象很深）。"""
    if faint_threshold is None:
        faint_threshold = get_settings().memory_impression_min_mentions
    if mention_count < faint_threshold:
        return None
    if mention_count >= deep_threshold:
        return "deep"
    return "faint"
