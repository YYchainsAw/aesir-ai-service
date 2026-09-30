"""人格包目录化加载器测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.services.companion.persona_pack_loader import PersonaPackLoadError, PersonaPackLoader
from app.services.companion.profile_repository import CompanionProfileRepository


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _build_minimal_pack(tmp_path: Path) -> Path:
    """构建一个最小合法人格包目录。"""
    pack_dir = tmp_path / "companion.alice"
    pack_dir.mkdir(parents=True)

    _write_yaml(
        pack_dir / "manifest.yaml",
        {
            "profile_version": "0.2",
            "companion_id": "companion.alice",
            "manifest_version": "0.1",
            "game_id": "aesir",
            "requires_capability": "L3",
        },
    )
    _write_yaml(
        pack_dir / "persona.yaml",
        {
            "identity": {
                "id": "companion.alice",
                "display_name": "Alice",
                "aliases": ["艾莉"],
                "wake_words": ["艾莉"],
                "self_reference_blacklist": ["艾莉"],
                "role": "player_companion",
                "archetype": "arcane_support",
                "short_description": "test",
            },
            "persona": {
                "background": "bg",
                "core_traits": ["lively"],
                "values": ["keep_promises"],
                "dislikes": ["reckless_self_harm"],
                "relationship_to_player": {"surface": "s", "subtext": "st", "behavior_rules": []},
            },
            "relationship_stage_personas": {},
            "speaking_style": {
                "language": "zh-CN",
                "tone": "t",
                "preferred_address_for_player": "你",
                "sentence_length": "short",
                "habits": [],
                "avoid": [],
            },
        },
    )
    _write_yaml(
        pack_dir / "rules.yaml",
        {
            "conversation_rules": {"allowed_game_states": ["conversation"], "response_rules": [], "runtime_state_policy": []},
            "combat_expression_rules": {},
            "tactical_acknowledgements": {},
        },
    )
    _write_yaml(pack_dir / "examples.yaml", {"dialogue_examples": []})
    _write_yaml(pack_dir / "reactions.yaml", {"combat_event_reactions": {}, "world_event_reactions": {}})
    _write_yaml(
        pack_dir / "fallbacks.yaml",
        {
            "default_dialogue_response": {
                "reply_text": "嗯？",
                "emotion_id": "emotion.bright",
                "gesture_id": "gesture.cheerful_idle",
                "facial_expression_id": "face.gentle_smile",
            },
            "fallback_dialogue_responses": {},
        },
    )
    _write_yaml(
        pack_dir / "presentation.yaml",
        {
            "allowed_emotion_ids": [{"id": "emotion.bright"}],
            "allowed_gesture_ids": [{"id": "gesture.cheerful_idle"}],
            "allowed_facial_expression_ids": [{"id": "face.gentle_smile"}],
            "ue_mapping_contract": {
                "fallback": {
                    "emotion_id": "emotion.bright",
                    "gesture_id": "gesture.cheerful_idle",
                    "facial_expression_id": "face.gentle_smile",
                },
                "required_fields": [],
            },
        },
    )
    _write_yaml(
        pack_dir / "abilities.yaml",
        {"ability_ids": ["ability.alice.basic_attack"], "behavior_ids": ["follow"]},
    )
    return pack_dir


def test_loader_reads_all_files_and_merges_them(tmp_path: Path) -> None:
    pack_dir = _build_minimal_pack(tmp_path)
    raw = PersonaPackLoader(pack_dir).load()

    assert raw["profile_version"] == "0.2"
    assert raw["companion_id"] == "companion.alice"
    assert raw["game_name"] == "aesir"
    assert raw["identity"]["display_name"] == "Alice"
    assert raw["dialogue_examples"] == []
    assert raw["abilities"]["ability_ids"] == ["ability.alice.basic_attack"]


def test_loader_raises_on_missing_required_file(tmp_path: Path) -> None:
    pack_dir = tmp_path / "companion.alice"
    pack_dir.mkdir()
    _write_yaml(pack_dir / "manifest.yaml", {"profile_version": "0.2"})
    # 其他文件缺失

    with pytest.raises(PersonaPackLoadError, match="Missing required persona pack file"):
        PersonaPackLoader(pack_dir).load()


def test_repository_loads_profile_from_pack(tmp_path: Path) -> None:
    pack_dir = _build_minimal_pack(tmp_path)
    profile = CompanionProfileRepository(pack_dir).load_primary()

    assert profile.companion_id == "companion.alice"
    assert profile.display_name == "Alice"
    assert profile.game_name == "aesir"
    assert "emotion.bright" in profile.allowed_emotion_ids


def test_get_profile_uses_mtime_cache_for_pack(tmp_path: Path) -> None:
    pack_dir = _build_minimal_pack(tmp_path)

    from app.services.companion import profile_repository as repo_module

    repo_module._profile_cache.clear()  # noqa: SLF001
    first = repo_module.get_profile(pack_dir)
    second = repo_module.get_profile(pack_dir)
    assert first is second
