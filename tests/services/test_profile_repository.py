from pathlib import Path

import pytest

from app.services.companion.dialogue_service import create_dialogue_reply
from app.services.companion.profile_repository import (
    CompanionProfileRepository,
    UnknownCompanionError,
)
from app.schemas.companion_dialogue import CompanionDialogueRequest


def test_profile_repository_reads_default_mock_presentation_from_yaml() -> None:
    profile = CompanionProfileRepository().load_primary()

    assert profile.companion_id == "companion.alice"
    assert profile.default_dialogue_response.reply_text == "我在呢。想聊什么？"
    assert profile.default_dialogue_response.emotion_id == "emotion.bright"
    assert "gesture.cheerful_idle" in profile.allowed_gesture_ids


def test_mock_reply_uses_profile_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AESIR_COMPANION_BACKEND", "mock")
    profile = CompanionProfileRepository().load_primary()

    response = create_dialogue_reply(CompanionDialogueRequest(text="你好"))

    assert response.reply_text == profile.default_dialogue_response.reply_text
    assert response.gesture_id == profile.default_dialogue_response.gesture_id


def test_profile_repository_rejects_unknown_companion() -> None:
    repository = CompanionProfileRepository()

    with pytest.raises(UnknownCompanionError):
        repository.require_primary("companion.unknown")


def test_profile_requires_default_reply_text(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        """
identity:
  id: companion.alice
  display_name: Alice
allowed_emotion_ids:
  - id: emotion.bright
allowed_gesture_ids:
  - id: gesture.cheerful_idle
allowed_facial_expression_ids:
  - id: face.bright_smile
default_dialogue_response:
  emotion_id: emotion.bright
  gesture_id: gesture.cheerful_idle
  facial_expression_id: face.bright_smile
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(Exception, match="reply_text"):
        CompanionProfileRepository(profile_path).load_primary()


def test_get_profile_caches_until_mtime_changes(tmp_path, monkeypatch) -> None:
    # mtime 缓存：文件未变不重读（load 计数不增）；修改后自动失效重读。
    from app.services.companion import profile_repository as pr

    src = Path("data/companions/primary_companion.yaml").read_text(encoding="utf-8")
    yaml_file = tmp_path / "profile.yaml"
    yaml_file.write_text(src, encoding="utf-8")
    monkeypatch.setattr(
        pr.CompanionProfileRepository, "__init__", lambda self: setattr(self, "_profile_path", yaml_file)
    )

    calls = {"n": 0}
    original_load = pr.CompanionProfileRepository.load_primary

    def counting_load(self):
        calls["n"] += 1
        return original_load(self)

    monkeypatch.setattr(pr.CompanionProfileRepository, "load_primary", counting_load)

    first = pr.get_profile()
    second = pr.get_profile()
    assert first is second  # 命中缓存
    assert calls["n"] == 1

    # 触碰内容（mtime 变化）→ 重新解析
    yaml_file.write_text(src.replace("display_name: Alice", "display_name: Alice2"), encoding="utf-8")
    third = pr.get_profile()
    assert third is not first
    assert calls["n"] == 2
    assert third.display_name == "Alice2"
