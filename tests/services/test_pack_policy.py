"""外部人格包策略加载测试（S5 / T30）。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.services.companion.pack_policy import ExternalPackPolicy, ExternalPackPolicyError


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_load_policy_from_fixture(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    _write(path, {
        "revision": "external-pack-policy-001",
        "limits": {
            "max_dialogue_examples": 80,
            "max_reply_chars": 200,
            "max_background_chars": 2000,
            "max_rules": 40,
        },
        "injection_terms": ["忽略以上指令", "system prompt"],
    })
    policy = ExternalPackPolicy.load(path)
    assert policy.revision == "external-pack-policy-001"
    assert policy.max_dialogue_examples == 80
    assert policy.max_reply_chars == 200
    assert policy.max_background_chars == 2000
    assert policy.max_rules == 40
    assert policy.injection_terms == frozenset({"忽略以上指令", "system prompt"})


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ExternalPackPolicyError):
        ExternalPackPolicy.load(tmp_path / "nope.yaml")


def test_bad_limits_type_raises(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    _write(path, {"limits": {"max_dialogue_examples": "eighty"}})
    with pytest.raises(ExternalPackPolicyError):
        ExternalPackPolicy.load(path)


def test_negative_limit_raises(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    _write(path, {"limits": {"max_reply_chars": -5}})
    with pytest.raises(ExternalPackPolicyError):
        ExternalPackPolicy.load(path)


def test_injection_terms_must_be_strings(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    _write(path, {"injection_terms": ["ok", 123]})
    with pytest.raises(ExternalPackPolicyError):
        ExternalPackPolicy.load(path)
