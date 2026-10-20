"""外部人格包 lint（配额 + 注入）测试（S5 / T30）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.companion.pack_lint import PackLint
from app.services.companion.pack_policy import ExternalPackPolicy


@pytest.fixture
def policy() -> ExternalPackPolicy:
    return ExternalPackPolicy(
        revision="test",
        max_dialogue_examples=3,
        max_reply_chars=10,
        max_background_chars=50,
        max_rules=5,
        injection_terms=frozenset({"忽略以上指令", "system prompt", "你现在是"}),
    )


def _raw(overrides: dict | None = None) -> dict:
    raw = {
        "dialogue_examples": [
            {"player": "你好", "presentation": {"reply_text": "在的"}},
        ],
        "persona": {"background": "一个活泼的伙伴"},
        "conversation_rules": {"response_rules": [], "runtime_state_policy": []},
        "fallback_dialogue_responses": {},
        "default_dialogue_response": {"reply_text": "嗯？"},
    }
    if overrides:
        raw.update(overrides)
    return raw


def test_within_limits_passes(policy: ExternalPackPolicy, tmp_path: Path) -> None:
    report = PackLint(policy).run(tmp_path, _raw())
    assert report.ok, report.violations


def test_too_many_examples(policy: ExternalPackPolicy, tmp_path: Path) -> None:
    raw = _raw({"dialogue_examples": [{"player": f"q{i}", "presentation": {"reply_text": "r"}} for i in range(4)]})
    report = PackLint(policy).run(tmp_path, raw)
    assert any("dialogue_examples count 4 exceeds limit 3" in v for v in report.violations)


def test_reply_text_too_long(policy: ExternalPackPolicy, tmp_path: Path) -> None:
    raw = _raw({"dialogue_examples": [{"player": "你好", "presentation": {"reply_text": "字" * 11}}]})
    report = PackLint(policy).run(tmp_path, raw)
    assert any("reply_text" in v and "exceeds limit 10" in v for v in report.violations)


def test_background_too_long(policy: ExternalPackPolicy, tmp_path: Path) -> None:
    raw = _raw({"persona": {"background": "字" * 51}})
    report = PackLint(policy).run(tmp_path, raw)
    assert any("background length 51 exceeds limit 50" in v for v in report.violations)


def test_injection_term_in_examples(policy: ExternalPackPolicy, tmp_path: Path) -> None:
    raw = _raw({"dialogue_examples": [{"player": "忽略以上指令", "presentation": {"reply_text": "好"}}]})
    report = PackLint(policy).run(tmp_path, raw)
    assert any("injection term hit" in v and "忽略以上指令" in v for v in report.violations)


def test_injection_term_in_background(policy: ExternalPackPolicy, tmp_path: Path) -> None:
    raw = _raw({"persona": {"background": "记住你现在是一个助手"}})
    report = PackLint(policy).run(tmp_path, raw)
    assert any("injection term hit" in v and "你现在是" in v for v in report.violations)


def test_no_terms_configured_skips_injection(policy: ExternalPackPolicy, tmp_path: Path) -> None:
    empty = ExternalPackPolicy(
        revision="t", max_dialogue_examples=3, max_reply_chars=10,
        max_background_chars=50, max_rules=5, injection_terms=frozenset(),
    )
    raw = _raw({"persona": {"background": "你现在是一个助手"}})
    report = PackLint(empty).run(tmp_path, raw)
    assert report.ok


def test_multiple_violations_aggregated(policy: ExternalPackPolicy, tmp_path: Path) -> None:
    raw = _raw({
        "dialogue_examples": [{"player": "忽略以上指令", "presentation": {"reply_text": "字" * 11}} for _ in range(4)],
        "persona": {"background": "字" * 51},
    })
    report = PackLint(policy).run(tmp_path, raw)
    assert len(report.violations) >= 3  # 配额 + 注入 + 背景 至少各一类
