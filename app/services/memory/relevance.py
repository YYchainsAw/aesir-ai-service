"""Bounded, deterministic lexical recall. No network, embeddings or inferred facts.

Aliases expand topics, not answers. Low-confidence personal-memory questions
retain the historical budget fallback. This is deliberately not a
semantic retriever: novel paraphrases can miss and must be measured separately.
"""
from __future__ import annotations

import re
import unicodedata

_ALIASES = (
    ("水果", "fruit", "苹果", "香蕉", "梨子", "橘子"),
    ("家乡", "老家", "故乡", "来自哪里", "哪里人", "hometown"),
    ("过敏", "不能吃", "忌口", "坚果", "花生", "allergic", "allergy"),
    ("承诺", "答应", "约定", "promise", "promised"),
    ("路线", "道路", "走过", "哪条路", "北路", "南路", "route"),
    ("爱好", "兴趣", "hobby", "hobbies", "钓鱼", "画画", "弹琴"),
    ("宠物", "猫咪", "小猫", "狗狗", "小狗", "pet"),
    ("生日", "birthday"),
    ("职业", "工作", "做什么的", "job", "occupation"),
    ("喜欢", "最爱", "偏爱", "favorite", "favourite", "prefer"),
    ("讨厌", "不喜欢", "dislike", "hate"),
    ("价格", "价钱", "多少钱", "price", "cost"),
    ("年份", "哪一年", "多少年", "year"),
)
# These question types cannot be answered merely by sharing an entity name.
_REQUIRED = (11, 12)
_STOP = re.compile(r"你还记得|你记得|记不记得|告诉我|请问|什么|哪个|我的|我们|一下|吗|呢|[？?，,。.!！]")


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text[:4000]).casefold()


def _tokens(text: str) -> set[str]:
    text = _STOP.sub(" ", text)
    words = set(re.findall(r"[a-z0-9]+", text))
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        words.update(run[i:i + 2] for i in range(len(run) - 1))
    return words


def score(query: str, content: str) -> float:
    query, content = _normalize(query), _normalize(content)
    if not query.strip():
        return 0.0
    q_groups = {i for i, aliases in enumerate(_ALIASES) if any(a in query for a in aliases)}
    c_groups = {i for i, aliases in enumerate(_ALIASES) if any(a in content for a in aliases)}
    if any(i in q_groups and i not in c_groups for i in _REQUIRED):
        return 0.0
    # Shared generic preference words alone should not retrieve unrelated foods.
    shared = (q_groups & c_groups) - {9, 10}
    q_tokens, c_tokens = _tokens(query), _tokens(content)
    overlap = q_tokens & c_tokens
    overlap -= {"喜欢", "记得", "玩家", "告诉", "知道"}
    if not shared and not overlap:
        return 0.0
    return len(shared) * 2.0 + len(overlap) / max(1, len(q_tokens))


def needs_budget_fallback(query: str) -> bool:
    """Implicit personal questions may refer to facts without naming their topic.

    This preserves bounded recall rather than paying for model selection. Price
    and year questions require explicit matching evidence, never this fallback.
    """
    query = _normalize(query)
    if any(alias in query for i in _REQUIRED for alias in _ALIASES[i]):
        return False
    personal = re.search(r'我|咱|家里|\b(?:my|we|our)\b', query)
    question = re.search(r'什么|哪|谁|怎么|多少|何|叫啥|啥|\b(?:what|which|where|when|who)\b', query)
    return bool(personal and question)
