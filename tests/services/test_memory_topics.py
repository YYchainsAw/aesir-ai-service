"""模糊印象层（主题 × 提及频率）单元测试。

设计：真人不会逐字记住所有对话，但近期聊过的都记得，随时间衰减。
- 每次提及 count+1；权重 = log2(1+次数) × 半衰期时间衰减；
- 注入按权重阈值（默认 0.75）：近期哪怕只提过 1 次也注入，3 天左右淡出；
- 提及越频繁、越郑重（显著性/在意值），存活越久；
- 长期不提自然淡忘（weight 随半衰期减半）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.memory.topics import (
    care_scale,
    extract_topics,
    impression_weight,
    is_blocked_topic,
    looks_like_noise,
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
_SELF_REF_BLACKLIST = frozenset({"艾莉", "爱莉", "alice"})


class TestTopicBlacklist:
    def test_self_reference_and_meta_fragments_are_blocked(self):
        for topic in ("艾莉", "爱莉", "alice", "名字", "记得", "记住"):
            assert is_blocked_topic(
                topic, self_reference_blacklist=_SELF_REF_BLACKLIST
            ) is True

    def test_real_topics_are_not_blocked(self):
        for topic in ("钓鱼", "上海", "蘑菇"):
            assert is_blocked_topic(topic) is False

    def test_meta_talk_about_being_an_ai_is_blocked(self):
        # 实测 2026-09-21：「幻视」「人机味」被当成玩家印象存下来，注入后
        # 只会让角色继续往「你是不是 AI」这条线上跑。
        for topic in ("幻视", "幻觉", "人机", "人机味"):
            assert is_blocked_topic(topic) is True

    def test_extract_topics_filters_blacklisted_fragments(self):
        # 迁移实测出现过的碎片：角色名 / 记忆元语言，不该成为印象主题。
        assert extract_topics(
            "我叫艾莉，记得我的名字",
            self_reference_blacklist=_SELF_REF_BLACKLIST,
        ) == []

    def test_blacklisted_topic_kept_out_of_impressions_via_store(self):
        # 合并入口统一过滤：LLM 顺带返回「艾莉」也不入印象（store 级测试见
        # test_memory_store.py，此处验证规则路径）。
        assert "艾莉" not in extract_topics(
            "艾莉，我们聊聊钓鱼吧",
            self_reference_blacklist=_SELF_REF_BLACKLIST,
        )


# -- 口语噪声碎片（连接词 / 应付词 / 语气词尾巴不构成话题）------------------
class TestNoiseTopics:
    def test_connective_fragments_are_noise(self):
        # 迁移实测出现过的碎片：LLM 顺带返回了「不过」「趁天」「意思呀」。
        for topic in ("不过", "趁天", "意思呀", "正好", "然后"):
            assert looks_like_noise(topic) is True

    def test_demonstrative_and_possessive_fragments_are_noise(self):
        # 实测 2026-09-21 落进印象层的碎片：指代/领属词本身不是话题。
        for topic in ("这话", "那话", "你的", "我的", "那你", "你说", "我说"):
            assert looks_like_noise(topic) is True

    def test_rule_split_fragments_from_her_own_replies_are_noise(self):
        # 六修实测 2026-09-22：她自述主题走规则切词（无分词库）切出的碎片——
        # 「主修/厉害/代价/不小」是动/形容词与形态词，「水系本来」「可不能
        # 当没听见」是切分错误，都不是话题。根治靠 reply_topics 改走 LLM
        # 自述，这里兜底存量与降级路径。
        for topic in ("主修", "厉害", "代价", "不小", "水系本来", "可不能当没听见"):
            assert looks_like_noise(topic) is True

    def test_component_words_inside_real_topics_survive(self):
        # 全等匹配（非包含）：正常话题包含这些成分字眼时不受误伤。
        assert looks_like_noise("主修法师") is False
        assert looks_like_noise("实力差距") is False

    def test_real_topics_are_not_noise(self):
        for topic in ("钓鱼", "上海搬家", "下周去医院复查", "不过如此"):
            assert looks_like_noise(topic) is False

    def test_modal_particle_tails_are_noise(self):
        assert looks_like_noise("挺好吧") is True
        assert looks_like_noise("去钓鱼呀") is False  # 语气词结尾但内容够长

    def test_single_char_is_noise(self):
        assert looks_like_noise("鱼") is True


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


# -- 阈值分档（权重 × 衰减判定注入口吻）-------------------------------------
class TestTierOf:
    def test_recent_single_mention_is_injected(self):
        """近期哪怕只提过一次的闲聊也记得（用户语义：时间不过太久就记得）。"""
        assert tier_of(mention_count=1, last_seen_days_ago=0.0) == "faint"

    def test_yesterday_single_mention_still_remembered(self):
        assert tier_of(mention_count=1, last_seen_days_ago=1.0) == "faint"

    def test_stale_single_mention_fades_out(self):
        """3 天前提过一次的闲聊淡出到阈值以下（默认半衰期 7 天）。"""
        assert tier_of(mention_count=1, last_seen_days_ago=3.0) is None

    def test_frequent_mentions_survive_longer_than_single(self):
        """提及频率强化存活：1 次的 3 天淡出，5 次的 3 天仍在。"""
        assert tier_of(mention_count=1, last_seen_days_ago=3.0) is None
        assert tier_of(mention_count=5, last_seen_days_ago=3.0) is not None

    def test_frequent_recent_mentions_reach_deep_tier(self):
        assert tier_of(mention_count=5, last_seen_days_ago=0.0) == "deep"

    def test_frequent_stale_mentions_fade_out_too(self):
        """哪怕提过很多次，长期不再提及也会淡忘（约 2 周半衰期后）。"""
        assert tier_of(mention_count=9, last_seen_days_ago=60.0) is None


# -- 显著性（双通道：郑重声明一次就该被记得）--------------------------------
class TestSalience:
    def test_salient_single_mention_beats_normal_single(self):
        normal = impression_weight(mention_count=1, last_seen_days_ago=0)
        salient = impression_weight(
            mention_count=1, last_seen_days_ago=0, salient=True
        )
        assert salient > normal

    def test_salient_first_mention_survives_longer_than_trivial(self):
        """郑重提过一次（等效 3 次提及 + 28 天长半衰期）淡忘远慢于闲聊。"""
        assert tier_of(mention_count=1, salient=True, last_seen_days_ago=7.0) == "faint"
        assert tier_of(mention_count=1, last_seen_days_ago=7.0) is None


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
        """在意深 → 加成大：同样首提郑重声明，档位随在意值提升、淡出更晚。"""
        settings_boost = 2.0
        # 刚声明时：无感只是有点印象（加成 0.5），极在意首提即 deep（加成 4.0）。
        assert (
            tier_of(
                1,
                salient=True,
                salience_boost=settings_boost * care_scale(50),
            )
            == "faint"
        )
        assert (
            tier_of(
                1,
                salient=True,
                salience_boost=settings_boost * care_scale(100),
            )
            == "deep"
        )
        # 25 天后：无感的淡出，极在意的仍有点印象（加成把存活期拉长）。
        assert (
            tier_of(
                1,
                last_seen_days_ago=25.0,
                salient=True,
                salience_boost=settings_boost * care_scale(50),
            )
            is None
        )
        assert (
            tier_of(
                1,
                last_seen_days_ago=25.0,
                salient=True,
                salience_boost=settings_boost * care_scale(100),
            )
            == "faint"
        )

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
