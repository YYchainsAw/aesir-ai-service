"""模糊印象层（主题 × 提及频率）单元测试。

设计：真人不会逐字记住所有对话，但对反复出现的主题形成强印象。
- 每次提及 count+1；权重 = log2(1+次数) × 半衰期时间衰减；
- 次数不足阈值（默认 3）不注入——只提过一两次的闲聊不留印象；
- 长期不提自然淡忘（weight 随半衰期减半）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.memory.topics import (
    extract_topics,
    impression_weight,
    tier_of,
)


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


# -- 规则提取（mock/降级路径）----------------------------------------------
class TestExtractTopics:
    def test_stops_words_and_short_fragments_are_dropped(self):
        assert extract_topics("我今天想聊聊钓鱼的事情") == ["钓鱼"]

    def test_multiple_topics_kept_in_order(self):
        assert extract_topics("钓鱼和打猎是最近常聊的话题") == ["钓鱼", "打猎"]

    def test_empty_when_nothing_salient(self):
        assert extract_topics("嗯嗯好的") == []

    def test_deduplicates_repeated_topic(self):
        assert extract_topics("钓鱼、钓鱼，今天还是钓鱼") == ["钓鱼"]

    def test_caps_at_three_topics(self):
        assert len(extract_topics("钓鱼打猎下厨跑步都爱")) <= 3


# -- 强化与衰减 -------------------------------------------------------------
class TestImpressionWeight:
    def test_weight_grows_logarithmically_with_count(self):
        once = impression_weight(mention_count=1, last_seen_days_ago=0)
        often = impression_weight(mention_count=9, last_seen_days_ago=0)
        assert often > once > 0

    def test_weight_decays_with_half_life(self):
        fresh = impression_weight(mention_count=5, last_seen_days_ago=0)
        one_half_life = impression_weight(
            mention_count=5, last_seen_days_ago=7, half_life_days=7
        )
        assert one_half_life == fresh / 2

    def test_forgotten_topics_approach_zero(self):
        assert (
            impression_weight(mention_count=3, last_seen_days_ago=365, half_life_days=7)
            < 0.01
        )


# -- 阈值分档（注入口吻）---------------------------------------------------
class TestTierOf:
    def test_below_threshold_is_not_injected(self):
        assert tier_of(mention_count=2) is None

    def test_threshold_reaches_faint_tier(self):
        assert tier_of(mention_count=3) == "faint"

    def test_frequent_mentions_reach_deep_tier(self):
        assert tier_of(mention_count=5) == "deep"
