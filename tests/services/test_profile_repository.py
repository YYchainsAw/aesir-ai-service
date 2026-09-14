from pathlib import Path

import pytest

from app.services.companion.dialogue_service import create_dialogue_reply
from app.services.companion.profile_repository import (
    CompanionProfileError,
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

    # 「你好」已命中 greeting 回退类别；此处用不命中任何关键词的输入验证默认回复。
    response = create_dialogue_reply(CompanionDialogueRequest(text="今天天气不错"))

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


def test_profile_parses_dialogue_examples_and_fallback_categories() -> None:
    # 方案 A 回归：dialogue_examples / fallback_dialogue_responses 解析进快照，
    # 回退类别保持 YAML 出现顺序（tactical_redirect 判序最高）。
    profile = CompanionProfileRepository().load_primary()

    categories = [c.name for c in profile.fallback_reply_categories]
    assert categories[0] == "tactical_redirect"
    assert all(c.replies for c in profile.fallback_reply_categories)
    assert any(e.category == "praised" for e in profile.dialogue_examples)


def test_profile_rejects_unregistered_id_in_dialogue_example(tmp_path) -> None:
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
  reply_text: hi
  emotion_id: emotion.bright
  gesture_id: gesture.cheerful_idle
  facial_expression_id: face.bright_smile
dialogue_examples:
  - category: smalltalk
    player: hi
    reply_text: yo
    emotion_id: emotion.not_registered
    gesture_id: gesture.cheerful_idle
    facial_expression_id: face.bright_smile
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(CompanionProfileError, match="dialogue example"):
        CompanionProfileRepository(profile_path).load_primary()


def test_corpus_red_lines_no_meta_language() -> None:
    """B1 语料红线：所有角色回复禁出戏术语（指令/接口/频道/协议/系统/模型等）。"""
    profile = CompanionProfileRepository().load_primary()
    forbidden = ("指令", "接口", "频道", "协议", "系统", "模型", "参数", "会话", "请求")
    offenders = [
        ex.player
        for ex in profile.dialogue_examples
        for term in forbidden
        if term in ex.presentation.reply_text
    ] + [
        f"{category.name}/{reply.reply_text}"
        for category in profile.fallback_reply_categories
        for reply in category.replies
        for term in forbidden
        if term in reply.reply_text
    ]
    assert not offenders, f"语料中出现出戏术语：{offenders}"


def test_corpus_b1_volume_and_category_coverage() -> None:
    """B1 扩充基线：few-shot ≥ 60 组，覆盖至少 12 个互动类别。"""
    profile = CompanionProfileRepository().load_primary()
    assert len(profile.dialogue_examples) >= 60
    categories = {ex.category for ex in profile.dialogue_examples}
    assert len(categories) >= 12
    # 关键类别必须存在（战斗婉拒 / 记忆引用 / 情绪关怀 / 边界拒绝）
    assert {"tactical_redirect", "memory_recall", "comfort", "boundary"} <= categories
