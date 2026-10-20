"""外部人格包守卫策略（S5 / T30 / issue #39）。

从 ``data/policy/external_pack_policy.yaml`` 加载两类参数：
1. 配额阈值（dialogue_examples 条数 / reply_text 字数 / background 字数 / 规则条数）；
2. 提示注入检测黑名单（子串命中即判违规）。

仅对 ``origin: external`` 的人格包生效；自有人格包（缺省 self）不触发本策略。
加载范式与 ``style_guard.StylePolicy`` 一致：dataclass 快照 + mtime 缓存热加载。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


_POLICY_PATH = Path(__file__).resolve().parents[3] / "data" / "policy" / "external_pack_policy.yaml"


class ExternalPackPolicyError(RuntimeError):
    """外部人格包策略加载失败。"""


@dataclass(frozen=True)
class ExternalPackPolicy:
    """从 YAML 加载的外部人格包守卫策略快照。"""

    revision: str
    max_dialogue_examples: int
    max_reply_chars: int
    max_background_chars: int
    max_rules: int
    injection_terms: frozenset[str]

    @classmethod
    def load(cls, path: Path = _POLICY_PATH) -> "ExternalPackPolicy":
        """加载策略；文件缺失或损坏时抛出 ExternalPackPolicyError（快速失败）。"""
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ExternalPackPolicyError(f"External pack policy not found: {path}") from error
        except (OSError, yaml.YAMLError) as error:
            raise ExternalPackPolicyError(f"Unable to load external pack policy: {error}") from error

        if not isinstance(raw, dict):
            raise ExternalPackPolicyError("External pack policy must be a YAML mapping.")

        limits = raw.get("limits") or {}
        if not isinstance(limits, dict):
            raise ExternalPackPolicyError("External pack policy field 'limits' must be a mapping.")

        return cls(
            revision=str(raw.get("revision", "")),
            max_dialogue_examples=_non_negative_int(limits, "max_dialogue_examples"),
            max_reply_chars=_non_negative_int(limits, "max_reply_chars"),
            max_background_chars=_non_negative_int(limits, "max_background_chars"),
            max_rules=_non_negative_int(limits, "max_rules"),
            injection_terms=_term_set(raw, "injection_terms"),
        )


def _non_negative_int(limits: dict[str, Any], key: str) -> int:
    value = limits.get(key, 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ExternalPackPolicyError(f"External pack policy limit '{key}' must be a non-negative integer.")
    return value


def _term_set(raw: dict[str, Any], key: str) -> frozenset[str]:
    """读取字符串列表并去重；缺省为空集，元素非字符串时报错。"""
    values = raw.get(key, [])
    if not isinstance(values, list):
        raise ExternalPackPolicyError(f"External pack policy field '{key}' must be a list.")
    terms: set[str] = set()
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise ExternalPackPolicyError(f"External pack policy field '{key}[{index}]' must be a non-empty string.")
        terms.add(value.strip())
    return frozenset(terms)


# 进程内缓存：策略文件静态不变，mtime 变化时自动失效（与 style_guard 同思路）。
_policy_cache: dict[Path, tuple[int, ExternalPackPolicy]] = {}


def get_external_pack_policy(path: Path = _POLICY_PATH) -> ExternalPackPolicy:
    """带 mtime 缓存的外部人格包策略读取。"""
    try:
        mtime = path.stat().st_mtime_ns
    except OSError as error:
        _policy_cache.pop(path, None)
        raise ExternalPackPolicyError(f"Unable to stat external pack policy: {error}") from error

    cached = _policy_cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    policy = ExternalPackPolicy.load(path)
    _policy_cache[path] = (mtime, policy)
    return policy
