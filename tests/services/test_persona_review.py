"""外部人格包审核记录测试（S5 / T30）。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.services.companion.persona_review import (
    PersonaReview,
    ReviewRecordError,
    review_conflicts,
    review_path,
)


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _review() -> PersonaReview:
    return PersonaReview(
        companion_id="companion.guest",
        game_id="aesir",
        profile_version="0.2",
        content_hash="sha256:abc",
        lint_status="pass",
        reviewer="张三",
        date="2026-10-20",
        signed_by="张三",
    )


def test_review_path_layout(tmp_path: Path) -> None:
    path = review_path(tmp_path, "aesir", "companion.guest")
    assert path == tmp_path / "aesir" / "companion.guest.yaml"


def test_load_valid_review(tmp_path: Path) -> None:
    path = review_path(tmp_path, "aesir", "companion.guest")
    _write(path, {
        "companion_id": "companion.guest", "game_id": "aesir", "profile_version": "0.2",
        "content_hash": "sha256:abc", "lint_status": "pass",
        "reviewer": "张三", "date": "2026-10-20", "signed_by": "张三",
    })
    review = PersonaReview.from_yaml(path)
    assert review.content_hash == "sha256:abc"
    assert review.lint_status == "pass"


def test_missing_review_raises(tmp_path: Path) -> None:
    with pytest.raises(ReviewRecordError):
        PersonaReview.from_yaml(tmp_path / "aesir" / "nobody.yaml")


def test_missing_field_raises(tmp_path: Path) -> None:
    path = review_path(tmp_path, "aesir", "companion.guest")
    _write(path, {"companion_id": "companion.guest"})  # 缺其余必填字段
    with pytest.raises(ReviewRecordError):
        PersonaReview.from_yaml(path)


def test_hash_mismatch_conflict() -> None:
    conflicts = review_conflicts({"profile_version": "0.2"}, _review(), "sha256:different")
    assert any("review hash mismatch" in c for c in conflicts)


def test_version_drift_conflict() -> None:
    conflicts = review_conflicts({"profile_version": "0.3"}, _review(), "sha256:abc")
    assert any("review version drift" in c for c in conflicts)


def test_lint_status_fail_conflict() -> None:
    review = PersonaReview(**{**_review().__dict__, "lint_status": "fail"})
    conflicts = review_conflicts({"profile_version": "0.2"}, review, "sha256:abc")
    assert any("review lint status not passed" in c for c in conflicts)


def test_consistent_review_no_conflicts() -> None:
    conflicts = review_conflicts({"profile_version": "0.2"}, _review(), "sha256:abc")
    assert conflicts == []
