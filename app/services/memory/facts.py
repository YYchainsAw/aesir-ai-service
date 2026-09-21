"""事实抽取的落地校验（防「编造的事实」变成永久错误记忆）。

实测复盘（2026-09-21）发现：长期信息此前几乎全靠模糊印象层承载，而印象
只有话题、没有事实——她手里没有任何可引用的事实，遇到「上次的烤鱼」这种
问法只能靠脑补补全。修法是让对话链路顺带抽出**事实**写进长期档案，注入时
作为「她确定知道的事」供她直说。

但这条通道有个比幻视更严重的风险：**一轮幻视只是当场说错，一条编造的事
实却会长期注入、次次被当作真事复述**。因此写档案前过一道轻量接地校验——
事实的实词必须大部分出现在玩家真说过的话（本轮 + 近期会话）里，对不上就
丢弃。这不是语义理解，只是保守兜底：宁可漏掉一条真事实（印象层仍留痕），
也不让编造的事实进档案。
"""

from __future__ import annotations

import re

# 归一化：空白 + 中英标点（去重键与接地比对都基于归一化后的文本）
_PUNCTUATION = re.compile(r"[\s，。、！？；：,.!?;:\"'（）()\[\]【】《》—…·~`]+")

# 计算「实词」时忽略的高频功能字：它们在任何两段中文里都会撞上，
# 留着只会虚高接地比（的/了/是/我…）。
_FUNCTION_CHARS = frozenset("的了是我你他她它们和与就还也都很在有个这那吗呢啊吧嗯")

# 事实里常见的第三人称前缀：玩家自己的话不会带「玩家」二字，不剥掉会
# 白白拉低接地比（「玩家养了一只猫」里有 2 个字对不上任何来源）。
_SUBJECT_PREFIXES = ("玩家", "对方")

# 接地阈值：事实的实词至少一半能在来源里找到，才允许写进档案。
_MIN_GROUNDING = 0.5
# 实词少于 2 个的事实没有校验余地（也对不上任何具体内容），直接丢弃。
_MIN_CONTENT_CHARS = 2


def normalize_fact(text: str) -> str:
    """去空白与标点后的规范形式：去重键与接地比对共用。"""
    return _PUNCTUATION.sub("", text).strip()


def content_chars(text: str) -> set[str]:
    """文本的实词字符集（归一化后去掉高频功能字）。

    按**字符**而非词切分：中文没有词边界，字符级重合度对这种短文本足够
    稳（「玩家养了一只叫小黑的猫」对「我养了只猫，它叫小黑」重合 6/9）。
    """
    normalized = normalize_fact(text)
    for prefix in _SUBJECT_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return {char for char in normalized if char not in _FUNCTION_CHARS}


def is_grounded(fact: str, sources: list[str]) -> bool:
    """事实是否扎根于来源文本（玩家本轮 + 近期真说过的话）。

    ``sources`` 为空（无任何玩家原文）时一律判不接地——没有依据的事实
    不写档案，这正是本校验存在的意义。
    """
    fact_chars = content_chars(fact)
    if len(fact_chars) < _MIN_CONTENT_CHARS:
        return False
    source_chars: set[str] = set()
    for source in sources:
        source_chars |= set(normalize_fact(source))
    if not source_chars:
        return False
    overlap = len(fact_chars & source_chars) / len(fact_chars)
    return overlap >= _MIN_GROUNDING


def dedup_key(fact: str) -> str:
    """档案去重键：同一件事换标点/空白重复说，仍视作同一条。"""
    return normalize_fact(fact).lower()
