"""模糊印象层（主题 × 提及频率）单元测试。

设计：真人不会逐字记住所有对话，但对反复出现的主题形成强印象。
- 每次提及 count+1；权重 = log2(1+次数) × 半衰期时间衰减；
- 次数不足阈值（默认 3）不注入——只提过一两次的闲聊不留印象；
- 长期不提自然淡忘（weight 随半衰期减半）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.memory.topics import (
    care_scale,
    extract_topics,
    impression_weight,
    is_blocked_topic,
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


# -- 主题黑名单（角色自指 / 元语言碎片不构成对玩家的印象）-------------------
class TestTopicBlacklist:
    def test_self_reference_and_meta_fragments_are_blocked(self):
        for topic in ("艾莉", "爱莉", "alice", "名字", "记得", "记住"):
            assert is_blocked_topic(topic) is True

    def test_real_topics_are_not_blocked(self):
        for topic in ("钓鱼", "上海", "蘑菇"):
            assert is_blocked_topic(topic) is False

    def test_extract_topics_filters_blacklisted_fragments(self):
        # 迁移实测出现过的碎片：角色名 / 记忆元语言，不该成为印象主题。
        assert extract_topics("我叫艾莉，记得我的名字") == []

    def test_blacklisted_topic_kept_out_of_impressions_via_store(self):
        # 合并入口统一过滤：LLM 顺带返回「艾莉」也不入印象（store 级测试见
        # test_memory_store.py，此处验证规则路径）。
        assert "艾莉" not in extract_topics("艾莉，我们聊聊钓鱼吧")


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


# -- 在意值缩放（太不喜欢也是在意的一部分）---------------------------------
class TestCareScale:
    def test_extremes_of_love_and_hate_care_equally(self):
        """极亲密（100）与极度讨厌（0）都最在意，缩放相同且达上限。"""
        assert care_scale(100) == care_scale(0) == 2.0

    def test_neutral_indifference_forgets_fastest(self):
        """中性无感缩放最低（0.25）：郑重声明几乎记不住。"""
        assert care_scale(50) == 0.25

    def test_initial_relationship_still_remembered_roughly(self):
        """初值 20（疏远侧）：在意缩放 1.3，郑重声明仍首提达注入阈值。"""
        assert care_scale(20) == 1.3

    def test_symmetric_around_neutral(self):
        assert care_scale(70) == care_scale(30)

    def test_scaled_boost_moves_tier_with_care(self):
        """在意深 → 加成大：同样首提郑重声明，档位随在意值提升。"""
        settings_boost = 2.0
        indifferent = tier_of(
            1, salient=True, salience_boost=settings_boost * care_scale(50)
        )
        devoted = tier_of(
            1, salient=True, salience_boost=settings_boost * care_scale(100)
        )
        assert indifferent is None  # 无感：1 + 0.5 = 1.5 < 3，不注入
        assert devoted == "deep"  # 极在意：1 + 4 = 5，首提即 deep

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
