"""外部人格包人工审核记录（S5 / T30 / issue #39）。

审核记录是「外部不可信包上线」的人工把关凭证，落盘于
``data/persona_reviews/<game_id>/<companion_id>.yaml``（入库、人写签字）。

机器只做**核对**不做**签发**：``review-init`` 子命令仅预填哈希与版本，
``signed_by`` 必须人工填写。加载时核对四项一致性：
1. 记录文件存在且字段齐全；
2. ``content_hash`` == 包当前重算哈希（防篡改/防包与记录漂移）；
3. ``profile_version`` == manifest 声明版本；
4. ``lint_status == "pass"``。
任一不符即产生冲突项，由外层 guard 聚合抛出。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ReviewRecordError(RuntimeError):
    """审核记录缺失、损坏或字段非法。"""


@dataclass(frozen=True)
class PersonaReview:
    """一份外部人格包人工审核记录的快照。"""

    companion_id: str
    game_id: str
    profile_version: str
    content_hash: str
    lint_status: str
    reviewer: str
    date: str
    signed_by: str

    @classmethod
    def from_yaml(cls, path: Path) -> "PersonaReview":
        """读取并校验审核记录；缺失/损坏/字段缺失抛 ``ReviewRecordError``。"""
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ReviewRecordError(f"Review record not found: {path}") from error
        except (OSError, yaml.YAMLError) as error:
            raise ReviewRecordError(f"Unable to load review record {path}: {error}") from error

        if not isinstance(raw, dict):
            raise ReviewRecordError(f"Review record must be a YAML mapping: {path}")

        return cls(
            companion_id=_required_str(raw, "companion_id", path),
            game_id=_required_str(raw, "game_id", path),
            profile_version=_required_str(raw, "profile_version", path),
            content_hash=_required_str(raw, "content_hash", path),
            lint_status=_required_str(raw, "lint_status", path),
            reviewer=_required_str(raw, "reviewer", path),
            date=_required_str(raw, "date", path),
            signed_by=_required_str(raw, "signed_by", path),
        )


def review_path(reviews_dir: Path, game_id: str, companion_id: str) -> Path:
    """审核记录落盘路径：``<reviews_dir>/<game_id>/<companion_id>.yaml``。"""
    return reviews_dir / game_id / f"{companion_id}.yaml"


def review_conflicts(
    manifest: dict[str, Any],
    review: PersonaReview,
    computed_hash: str,
) -> list[str]:
    """比对审核记录与包当前状态，返回冲突列表（空 = 一致）。"""
    conflicts: list[str] = []

    if review.content_hash != computed_hash:
        conflicts.append(
            f"review hash mismatch: reviewed '{review.content_hash}' vs current '{computed_hash}'"
        )

    manifest_version = str(manifest.get("profile_version", ""))
    if review.profile_version != manifest_version:
        conflicts.append(
            f"review version drift: reviewed '{review.profile_version}' vs manifest '{manifest_version}'"
        )

    if review.lint_status != "pass":
        conflicts.append(f"review lint status not passed: '{review.lint_status}'")

    return conflicts


def _required_str(raw: dict[str, Any], key: str, path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ReviewRecordError(f"Review record '{path}' missing required field '{key}'.")
    return value.strip()
