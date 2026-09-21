"""模糊印象层：主题 × 提及频率（方案：LLM 顺带返回主题，规则提取兜底）。

真人不会逐字记住所有对话，但近期聊过的都记得、随时间衰减：
- 每次提及 ``mention_count += 1``；
- 权重 = ``log2(1 + 次数) × 0.5 ** (距上次提及天数 / 半衰期)``——
  提得越多印象越深，长期不提自然淡忘；
- 注入按权重阈值：近期哪怕只提过 1 次也记得，约 3 天淡出；提及频率与
  显著性（郑重声明/在意值）把存活期拉长。

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

# 主题黑名单：无论规则提取还是 LLM 顺带返回，都不该成为「对玩家的印象」——
# 角色自指（她的名字）、记忆/对话本身的元语言碎片（迁移实测出现过「艾莉」「记得」「名字」）。
# 过滤点在 ``store._merge_mentions_locked``（合并入口，三条路径共用）与 ``extract_topics``。
_TOPIC_BLACKLIST = frozenset(
    """
    艾莉 爱莉 alice 名字 记得 记住 忘了 忘记 告诉 答应 说话 对话 回复 聊天
    重要 事情 感觉 时候 现在 幻视 幻觉 人机 人机味
    """.split()
)

MAX_TOPICS = 3

# 口语噪声主题：连接词 / 应付词 / 带语气词的短碎片。LLM 顺带返回的主题
# 里实测出现过「不过」「趁天」「意思呀」这类碎片——不成话题，注入只会
# 让角色说出怪话。按全等匹配（黑名单才是包含匹配）。
_NOISE_TOPICS = frozenset(
    """
    不过 但是 然后 所以 就是 还是 还是 正好 趁 趁天 意思 确实 其实 当然
    可能 应该 大概 反正 另外 而且 以及 这样 那样 怎么 为什么 真的 好的
    可以 不用 没事 没问题 还行 挺好 差不多 反馈 表示 感觉 觉得
    这话 那话 你的 我的 没有 有点 比较 有点儿 那你 你说 我说
    """.split()
)
# 句尾语气词：带语气词结尾的短碎片（意思呀 / 挺好吧）不是话题。
_MODAL_TAILS = "呀哦啦嘛呗咯哈嘿吧呢啊"


def looks_like_noise(topic: str) -> bool:
    """主题是否为口语噪声碎片（连接词 / 应付词 / 语气词尾巴）。

    与黑名单（角色自指 / 元语言）互补：黑名单按包含匹配，这里按全等 +
    形态判定，避免误伤包含这些字眼的正常话题。规则提取与 LLM 返回共用。
    """
    stripped = topic.strip()
    if len(stripped) <= 1:
        return True
    if stripped[-1] in _MODAL_TAILS and len(stripped) <= 3:
        return True
    return stripped in _NOISE_TOPICS


def is_blocked_topic(topic: str) -> bool:
    """主题是否含黑名单词（角色自指 / 元语言碎片，不构成对玩家的印象）。

    按「包含」而非全等匹配：规则提取的碎片常是「叫艾莉」「不记得」这类
    带粘连字的形式，全等匹配漏掉；黑名单词本身即为不该出现的内容。
    """
    lowered = topic.strip().lower()
    return any(word in lowered for word in _TOPIC_BLACKLIST)


def extract_topics(text: str, *, max_topics: int = MAX_TOPICS) -> list[str]:
    """规则降级提取：切段 → 去停用词 → 保留 ≥2 字 → 去黑名单/噪声 → 去重截断。"""
    topics: list[str] = []
    for segment in _SPLIT_PATTERN.split(text):
        for run in _remove_stopwords(segment):
            if (
                len(run) >= 2
                and run not in topics
                and not is_blocked_topic(run)
                and not looks_like_noise(run)
            ):
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
    salient: bool = False,
    salience_boost: float | None = None,
    salient_half_life_days: float | None = None,
) -> float:
    """主题印象权重：log 增长 × 半衰期衰减。

    显著性（双通道之一）：郑重提过一次的话题按 ``次数 + salience_boost``
    计等效提及（首提即达注入阈值），且衰减用更长的半衰期——重要的事
    遗忘更慢。
    """
    settings = get_settings()
    if half_life_days is None:
        half_life_days = settings.memory_impression_half_life_days
    if salience_boost is None:
        salience_boost = settings.memory_impression_salience_boost
    if salient:
        if salient_half_life_days is None:
            salient_half_life_days = settings.memory_impression_salient_half_life_days
        half_life_days = max(half_life_days, salient_half_life_days)
        mention_count = mention_count + salience_boost
    decay = 0.5 ** (max(0.0, last_seen_days_ago) / max(half_life_days, 1e-9))
    return math.log2(1 + max(0, mention_count)) * decay


def tier_of(
    mention_count: int,
    *,
    last_seen_days_ago: float = 0.0,
    salient: bool = False,
    inject_weight: float | None = None,
    deep_weight: float | None = None,
    salience_boost: float | None = None,
) -> str | None:
    """注入档位：None（不注入）| faint（有点印象）| deep（印象很深）。

    判定不看提及次数的硬门槛，而看现算权重（log 增长 × 半衰期衰减）：
    近期哪怕只提过一次的闲聊也有印象（真人语义：时间不过太久就记得），
    随时间自然淡出；提及越频繁、越被郑重对待（显著性/在意值），权重越高、
    存活越久。``salience_boost`` 为该条印象声明时按在意值缩放后持久化的
    加成（None 用全局默认，兼容旧数据）。
    """
    settings = get_settings()
    if inject_weight is None:
        inject_weight = settings.memory_impression_inject_weight
    if deep_weight is None:
        deep_weight = settings.memory_impression_deep_weight
    weight = impression_weight(
        mention_count=mention_count,
        last_seen_days_ago=last_seen_days_ago,
        salient=salient,
        salience_boost=salience_boost,
    )
    if weight < inject_weight:
        return None
    if weight >= deep_weight:
        return "deep"
    return "faint"


# 在意值缩放边界：中性无感 ×0.25（几乎记不住），极度在意（极爱 / 极厌）×2.0。
_CARE_SCALE_FLOOR = 0.25
_CARE_SCALE_CEIL = 2.0


def care_scale(relationship_value: int | float, *, neutral: float | None = None) -> float:
    """在意值 → 显著性加成乘子。

    「在意」是偏离无感的程度，与方向无关：极亲密（100）与极度讨厌（0）
    都最在意——太不喜欢也是在意的一部分；中性无感才最健忘。距离中性点
    按两侧实际跨度归一，返回值钳制在 ``[_CARE_SCALE_FLOOR, _CARE_SCALE_CEIL]``。
    """
    settings = get_settings()
    if neutral is None:
        neutral = settings.memory_impression_care_neutral
    distance = float(relationship_value) - neutral
    span = max(neutral, 1e-9) if distance < 0 else max(100.0 - neutral, 1e-9)
    normalized = abs(distance) / span
    return _CARE_SCALE_FLOOR + (_CARE_SCALE_CEIL - _CARE_SCALE_FLOOR) * normalized


# 郑重声明线索（规则兜底；正式路径走 LLM 顺带返回的 salient 标记）。
_SALIENT_CUES = (
    "记住",
    "重要",
    "别忘",
    "认真",
    "郑重",
    "一定要",
    "我发誓",
    "答应我",
    "告诉你",
)


def looks_salient(text: str) -> bool:
    """规则兜底判定：玩家是否郑重其事地说了什么。"""
    return any(cue in text for cue in _SALIENT_CUES)
