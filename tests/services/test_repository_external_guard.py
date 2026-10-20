"""profile_repository 挂载外部包守卫的集成测试（S5 / T30）。

验证：
1. 外部包（origin=external）checksum 缺失 -> load_primary 抛 CompanionProfileError（503 语义）；
2. 同目录改回 origin=self -> 恢复可加载（降级路径 / 自有人格包豁免）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.services.companion import profile_repository as pr
from app.services.companion.persona_pack_validator import Capability
from app.services.companion.profile_repository import CompanionProfileError, CompanionProfileRepository


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _permissive_capability() -> Capability:
    return Capability(
        game_id="aesir",
        level="L3",
        scenes=frozenset({"exploration"}),
        events=frozenset(),
        presentation_ids=frozenset({"emotion.bright", "gesture.cheerful_idle", "face.gentle_smile"}),
        abilities=frozenset(),
        behaviors=frozenset(),
    )


def _build_full_pack(tmp_path: Path, origin: str) -> Path:
    """构造一个身份/默认回复完整、可通过归属校验的人格包目录。"""
    pack = tmp_path / "companion.guest"
    pack.mkdir()
    _write(pack / "manifest.yaml", {
        "profile_version": "0.2", "companion_id": "companion.guest", "game_id": "aesir",
        "requires_capability": "L3", "origin": origin, "checksum": None,
    })
    _write(pack / "persona.yaml", {
        "identity": {"id": "companion.guest", "display_name": "Guest", "wake_words": ["guest"]},
        "persona": {"background": "bg"},
    })
    _write(pack / "rules.yaml", {"conversation_rules": {"allowed_game_states": ["exploration"]}})
    _write(pack / "examples.yaml", {"dialogue_examples": []})
    _write(pack / "reactions.yaml", {"combat_event_reactions": {}, "world_event_reactions": {}})
    _write(pack / "fallbacks.yaml", {
        "default_dialogue_response": {
            "reply_text": "嗯？", "emotion_id": "emotion.bright",
            "gesture_id": "gesture.cheerful_idle", "facial_expression_id": "face.gentle_smile",
        },
        "fallback_dialogue_responses": {},
    })
    _write(pack / "presentation.yaml", {
        "allowed_emotion_ids": [{"id": "emotion.bright"}],
        "allowed_gesture_ids": [{"id": "gesture.cheerful_idle"}],
        "allowed_facial_expression_ids": [{"id": "face.gentle_smile"}],
    })
    return pack


def test_external_pack_without_checksum_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pr, "_get_capability", _permissive_capability)
    pack = _build_full_pack(tmp_path, origin="external")
    with pytest.raises(CompanionProfileError, match="checksum is missing"):
        CompanionProfileRepository(pack).load_primary()


def test_self_pack_same_directory_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """降级路径：同目录把 origin 改回 self（或删除 origin），恢复可加载。"""
    monkeypatch.setattr(pr, "_get_capability", _permissive_capability)
    pack = _build_full_pack(tmp_path, origin="self")
    profile = CompanionProfileRepository(pack).load_primary()
    assert profile.companion_id == "companion.guest"
