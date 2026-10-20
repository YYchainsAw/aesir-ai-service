"""人格包内容哈希测试（S5 / T30）。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.services.companion.pack_checksum import PackChecksumError, compute_pack_checksum


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _make_pack(tmp_path: Path, manifest: dict | None = None) -> Path:
    pack = tmp_path / "companion.guest"
    pack.mkdir()
    _write(pack / "manifest.yaml", manifest or {"game_id": "aesir", "profile_version": "0.2", "checksum": None})
    _write(pack / "persona.yaml", {"identity": {"id": "companion.guest"}})
    _write(pack / "examples.yaml", {"dialogue_examples": []})
    return pack


def test_checksum_deterministic(tmp_path: Path) -> None:
    pack = _make_pack(tmp_path)
    assert compute_pack_checksum(pack) == compute_pack_checksum(pack)


def test_checksum_changes_on_touch(tmp_path: Path) -> None:
    pack = _make_pack(tmp_path)
    before = compute_pack_checksum(pack)
    _write(pack / "examples.yaml", {"dialogue_examples": [{"player": "新内容"}]})
    after = compute_pack_checksum(pack)
    assert before != after


def test_manifest_checksum_field_excluded(tmp_path: Path) -> None:
    """manifest 中 checksum 字段自身（及注释行）改动不应改变哈希（破循环）。"""
    pack = _make_pack(tmp_path, {"game_id": "aesir", "profile_version": "0.2", "checksum": None})
    before = compute_pack_checksum(pack)
    # 改 checksum 的取值与注释——必须不影响哈希
    _write(pack / "manifest.yaml", {"game_id": "aesir", "profile_version": "0.2", "checksum": "sha256:fake"})
    after = compute_pack_checksum(pack)
    assert before == after


def test_other_manifest_change_changes_hash(tmp_path: Path) -> None:
    """manifest 其他字段（非 checksum）改动必须改变哈希。"""
    pack = _make_pack(tmp_path, {"game_id": "aesir", "profile_version": "0.2", "checksum": None})
    before = compute_pack_checksum(pack)
    _write(pack / "manifest.yaml", {"game_id": "aesir", "profile_version": "0.3", "checksum": None})
    after = compute_pack_checksum(pack)
    assert before != after


def test_missing_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(PackChecksumError):
        compute_pack_checksum(tmp_path / "not-exist")


def test_dir_without_yaml_raises(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "readme.txt").write_text("hi", encoding="utf-8")
    with pytest.raises(PackChecksumError):
        compute_pack_checksum(empty)


def test_output_is_sha256_prefixed(tmp_path: Path) -> None:
    pack = _make_pack(tmp_path)
    digest = compute_pack_checksum(pack)
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64
