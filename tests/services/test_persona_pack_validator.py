"""人格包归属校验测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.companion.persona_pack_validator import (
    Capability,
    PersonaPackValidationError,
    PersonaPackValidator,
)


@pytest.fixture
def capability() -> Capability:
    return Capability(
        game_id="aesir",
        level="L3",
        scenes=frozenset({"combat", "exploration"}),
        events=frozenset({"player_hp_critical", "boss_stunned", "region_first_entered"}),
        presentation_ids=frozenset({"emotion.bright", "gesture.cheerful_idle", "face.gentle_smile"}),
        abilities=frozenset({"ability.alice.basic_attack", "ability.alice.explosion"}),
        behaviors=frozenset({"follow", "inspect"}),
    )


def _minimal_raw(overrides: dict | None = None) -> dict:
    raw = {
        "manifest": {
            "game_id": "aesir",
            "requires_capability": "L3",
        },
        "conversation_rules": {"allowed_game_states": ["exploration"]},
        "combat_event_reactions": {"player_hp_critical": {}},
        "world_event_reactions": {"region_first_entered": {}},
        "allowed_emotion_ids": [{"id": "emotion.bright"}],
        "allowed_gesture_ids": [{"id": "gesture.cheerful_idle"}],
        "allowed_facial_expression_ids": [{"id": "face.gentle_smile"}],
        "abilities": {
            "ability_ids": ["ability.alice.basic_attack"],
            "behavior_ids": ["follow"],
        },
    }
    if overrides:
        raw.update(overrides)
    return raw


def test_valid_pack_passes(capability: Capability, tmp_path: Path) -> None:
    validator = PersonaPackValidator(capability)
    validator.validate(tmp_path / "companion.alice", _minimal_raw())


def test_game_id_mismatch(capability: Capability, tmp_path: Path) -> None:
    validator = PersonaPackValidator(capability)
    raw = _minimal_raw({"manifest": {"game_id": "other_game", "requires_capability": "L3"}})
    with pytest.raises(PersonaPackValidationError, match="game_id mismatch"):
        validator.validate(tmp_path / "companion.alice", raw)


def test_requires_capability_exceeds(capability: Capability, tmp_path: Path) -> None:
    capability_l0 = Capability(
        game_id="aesir",
        level="L0",
        scenes=capability.scenes,
        events=capability.events,
        presentation_ids=capability.presentation_ids,
        abilities=capability.abilities,
        behaviors=capability.behaviors,
    )
    validator = PersonaPackValidator(capability_l0)
    with pytest.raises(PersonaPackValidationError, match="requires_capability"):
        validator.validate(tmp_path / "companion.alice", _minimal_raw())


def test_unknown_scene_reported(capability: Capability, tmp_path: Path) -> None:
    validator = PersonaPackValidator(capability)
    raw = _minimal_raw({"conversation_rules": {"allowed_game_states": ["unknown_scene"]}})
    with pytest.raises(PersonaPackValidationError, match="unknown scenes"):
        validator.validate(tmp_path / "companion.alice", raw)


def test_unknown_event_reported(capability: Capability, tmp_path: Path) -> None:
    validator = PersonaPackValidator(capability)
    raw = _minimal_raw({"combat_event_reactions": {"unknown_event": {}}})
    with pytest.raises(PersonaPackValidationError, match="unknown events"):
        validator.validate(tmp_path / "companion.alice", raw)


def test_unknown_presentation_id_reported(capability: Capability, tmp_path: Path) -> None:
    validator = PersonaPackValidator(capability)
    raw = _minimal_raw({"allowed_emotion_ids": [{"id": "emotion.unknown"}]})
    with pytest.raises(PersonaPackValidationError, match="unknown presentation_ids"):
        validator.validate(tmp_path / "companion.alice", raw)


def test_unknown_ability_reported(capability: Capability, tmp_path: Path) -> None:
    validator = PersonaPackValidator(capability)
    raw = _minimal_raw({"abilities": {"ability_ids": ["ability.alice.unknown"], "behavior_ids": []}})
    with pytest.raises(PersonaPackValidationError, match="unknown abilities"):
        validator.validate(tmp_path / "companion.alice", raw)


def test_multiple_conflicts_in_one_message(capability: Capability, tmp_path: Path) -> None:
    validator = PersonaPackValidator(capability)
    raw = _minimal_raw(
        {
            "manifest": {"game_id": "wrong", "requires_capability": "L3"},
            "combat_event_reactions": {"unknown_event": {}},
            "abilities": {"ability_ids": ["ability.alice.unknown"], "behavior_ids": []},
        }
    )
    with pytest.raises(PersonaPackValidationError) as exc_info:
        validator.validate(tmp_path / "companion.alice", raw)
    message = str(exc_info.value)
    assert "game_id mismatch" in message
    assert "unknown events" in message
    assert "unknown abilities" in message
