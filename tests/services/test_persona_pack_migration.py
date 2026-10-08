"""S2 人格包迁移回归：真实 Alice/Bruno 目录包的加载、归属校验与注册表行为。"""

from __future__ import annotations

from pathlib import Path

from app.services.companion.profile_repository import (
    CompanionProfileRepository,
    get_profile,
    list_registered_companions,
)

_ALICE_PACK = Path("data/personas/aesir/companion.alice")
_BRUNO_PACK = Path("data/personas/aesir/companion.bruno")


def test_alice_pack_loads_with_expected_identity() -> None:
    profile = CompanionProfileRepository(_ALICE_PACK).load_primary()
    assert profile.companion_id == "companion.alice"
    assert profile.display_name == "Alice"
    assert profile.game_name == "aesir"
    assert "艾莉" in profile.wake_words
    # 迁移无损：few-shot 与回退类别数量与旧单文件一致
    assert len(profile.dialogue_examples) == 68
    assert len(profile.fallback_reply_categories) == 7
    # 战术应答与世界事件反应完整迁移
    assert "support_heal_player" in profile.raw["tactical_acknowledgements"]
    assert set(profile.raw["world_event_reactions"]) == {
        "region_first_entered", "weather_changed", "gift_given",
        "companion_recovered", "player_protected_companion", "promise_kept",
    }


def test_bruno_pack_loads_with_expected_identity() -> None:
    profile = CompanionProfileRepository(_BRUNO_PACK).load_primary()
    assert profile.companion_id == "companion.bruno"
    assert profile.display_name == "Bruno"
    assert len(profile.dialogue_examples) == 6
    # Bruno 白名单与 Alice 不重叠（情绪子集且默认 ID 不同）
    assert profile.default_dialogue_response.emotion_id == "emotion.neutral"


def test_default_profile_source_is_alice_pack() -> None:
    """无参 get_profile()（旧链路主队友入口）应解析到 Alice 人格包目录。"""
    profile = get_profile()
    assert profile.companion_id == "companion.alice"


def test_registry_contains_both_packs_without_duplicates() -> None:
    ids = list_registered_companions()
    assert ids.count("companion.alice") == 1
    assert ids.count("companion.bruno") == 1
    assert len(ids) == len(set(ids))
