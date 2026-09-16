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
    looks_salient,
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


# -- 显著性（双通道：郑重声明一次就该被记得）--------------------------------
class TestSalience:
    def test_salient_single_mention_beats_normal_single(self):
        normal = impression_weight(mention_count=1, last_seen_days_ago=0)
        salient = impression_weight(
            mention_count=1, last_seen_days_ago=0, salient=True
        )
        assert salient > normal

    def test_salient_first_mention_reaches_injection_tier(self):
        """郑重提过一次 ≈ 等效 3 次普通提及，直接跨过注入阈值。"""
        assert tier_of(mention_count=1, salient=True) == "faint"

    def test_salient_topic_decays_slower(self):
        normal = impression_weight(mention_count=3, last_seen_days_ago=14)
        salient = impression_weight(
            mention_count=3, last_seen_days_ago=14, salient=True
        )
        assert salient > normal

    def test_repeated_normal_mentions_do_not_make_topic_salient(self):
        assert looks_salient("钓鱼、钓鱼，还是钓鱼") is False

    def test_solemn_cues_flag_salience(self):
        for text in (
            "记住：我最讨厌蘑菇。",
            "有件重要的事情告诉你，我下个月要搬去上海。",
            "别忘记下周陪我去医院。",
        ):
            assert looks_salient(text) is True

    def test_plain_smalltalk_is_not_salient(self):
        assert looks_salient("今天天气不错") is False
