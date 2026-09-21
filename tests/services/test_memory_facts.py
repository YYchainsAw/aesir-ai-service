"""事实通道的接地校验与档案去重（对话实测复盘 2026-09-21）。

背景：档案里的事实会以「她确定知道的事」长期注入 prompt，编造一条就是
永久错误记忆。因此写档案前必须过接地校验；本文件钉住这道安全阀，以及
「同一件事重复说只算一条」的去重语义。
"""

from __future__ import annotations

from app.schemas.memory import MemoryEntry
from app.services.memory.facts import content_chars, is_grounded, normalize_fact
from app.services.memory.store import MemoryStore


class TestGrounding:
    def test_fact_paraphrasing_player_words_is_grounded(self):
        # 玩家说「我养了只猫，它叫小黑」→ 抽取为第三人称事实，允许换词。
        assert is_grounded("玩家养了一只叫小黑的猫", ["我养了只猫，它叫小黑。"]) is True

    def test_invented_fact_is_rejected(self):
        # 「上次的烤鱼」这类无据断言：来源里没有任何相关字眼。
        assert is_grounded("玩家上次给艾莉烤了鱼", ["今天天气不错。"]) is False

    def test_fact_without_any_source_is_rejected(self):
        assert is_grounded("玩家养了一只猫", []) is False
        assert is_grounded("玩家养了一只猫", [""]) is False

    def test_grounding_uses_recent_turns_too(self):
        # 跨轮拼出的复合事实：本轮没说猫，但上一轮说过——仍算有据。
        assert (
            is_grounded(
                "玩家养了一只叫小黑的猫",
                ["它叫小黑。", "我养了只猫。"],
            )
            is True
        )

    def test_pure_function_words_are_not_a_fact(self):
        assert is_grounded("的了吧", ["的了吧"]) is False

    def test_normalize_and_content_chars_strip_noise(self):
        assert normalize_fact(" 玩家 养了，一只猫。 ") == "玩家养了一只猫"
        # 「玩家」前缀剥掉、高频功能字忽略，留下的才是可校验的实词。
        assert content_chars("玩家养了一只猫") == {"养", "一", "只", "猫"}


class TestArchiveDedup:
    def test_same_fact_twice_keeps_one_entry_and_refreshes_time(self, tmp_path):
        store = MemoryStore("companion.alice", root=str(tmp_path))
        store.load()
        first = MemoryEntry(content="玩家养了一只叫小黑的猫", real_time="2026-09-01T00:00:00Z")
        assert store.record_facts([first]) == 1

        again = MemoryEntry(content="玩家养了一只叫小黑的猫！", real_time="2026-09-20T00:00:00Z")
        assert store.record_facts([again]) == 0  # 标点不同，仍是同一件事

        archive = store.snapshot().archive
        assert len(archive) == 1
        assert archive[0].real_time == "2026-09-20T00:00:00Z"  # 再提一次：时效刷新

    def test_restating_does_not_downgrade_importance(self, tmp_path):
        store = MemoryStore("companion.alice", root=str(tmp_path))
        store.load()
        store.record_facts([MemoryEntry(content="玩家答应找回笔记", importance="critical")])
        store.record_facts([MemoryEntry(content="玩家答应找回笔记", importance="low")])
        assert store.snapshot().archive[0].importance == "critical"

    def test_record_fact_single_entry_still_works(self, tmp_path):
        store = MemoryStore("companion.alice", root=str(tmp_path))
        store.load()
        store.record_fact(MemoryEntry(content="玩家怕高。"))
        assert [e.content for e in store.snapshot().archive] == ["玩家怕高。"]
