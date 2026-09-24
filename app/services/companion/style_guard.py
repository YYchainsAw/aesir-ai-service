"""表达一致性校验（SDD T083 / FR-002 / FR-003）。

校验维度：
1. 出戏术语（meta-language）：回复中不得出现游戏机制/系统/协议/模型等词汇。
2. 禁忌表达：不得出现占有、控制、贬低、胁迫或情感勒索式内容。
3. 虚构事实信号：声称玩家说过/答应过/承诺过某事时，若上下文无对应记忆支撑，
   视为高危编造。

校验失败时，调用方应重试一次；仍失败则回退到 mock/安全候选。
本模块只负责判定，不重试也不生成替代回复，以保持职责单一。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


# 策略文件路径；与 data/policy/ 下其他策略保持一致。
_POLICY_PATH = Path(__file__).resolve().parents[3] / "data" / "policy" / "style_policy.yaml"


class StylePolicyError(RuntimeError):
    """风格策略加载失败。"""


@dataclass(frozen=True)
class StyleViolation:
    """一次风格违规。"""

    category: str
    matched_term: str
    message: str


@dataclass(frozen=True)
class StylePolicy:
    """从 YAML 加载的风格策略快照。"""

    revision: str
    meta_terms: frozenset[str]
    forbidden_expressions: frozenset[str]
    fabrication_signals: frozenset[str]
    require_memory_for_fabrication_signals: bool

    @classmethod
    def load(cls, path: Path = _POLICY_PATH) -> "StylePolicy":
        """加载策略；文件缺失或损坏时抛出 StylePolicyError（快速失败）。"""
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise StylePolicyError(f"Style policy not found: {path}") from error
        except (OSError, yaml.YAMLError) as error:
            raise StylePolicyError(f"Unable to load style policy: {error}") from error

        if not isinstance(raw, dict):
            raise StylePolicyError("Style policy must be a YAML mapping.")

        return cls(
            revision=str(raw.get("revision", "")),
            meta_terms=_term_set(raw, "meta_terms"),
            forbidden_expressions=_term_set(raw, "forbidden_expressions"),
            fabrication_signals=_term_set(raw, "fabrication_signals"),
            require_memory_for_fabrication_signals=bool(
                raw.get("checks", {}).get("require_memory_for_fabrication_signals", True)
            ),
        )


# 进程内缓存：策略文件静态不变，mtime 变化时自动失效（与 profile_repository 同思路）。
_policy_cache: dict[Path, tuple[int, StylePolicy]] = {}


def get_style_policy(path: Path = _POLICY_PATH) -> StylePolicy:
    """带 mtime 缓存的风格策略读取。"""
    try:
        mtime = path.stat().st_mtime_ns
    except OSError as error:
        _policy_cache.pop(path, None)
        raise StylePolicyError(f"Unable to stat style policy: {error}") from error

    cached = _policy_cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    policy = StylePolicy.load(path)
    _policy_cache[path] = (mtime, policy)
    return policy


def check_reply(
    text: str,
    *,
    injected_memories: list[Any] | None = None,
    injected_impressions: list[Any] | None = None,
    policy: StylePolicy | None = None,
) -> list[StyleViolation]:
    """检查单条回复文本是否违反表达一致性规则。

    ``injected_memories`` / ``injected_impressions`` 用于虚构事实信号的上下文
    校验：当回复包含"你说过"/"你答应过"等信号词，但本轮未注入任何长期记忆
    或印象时，视为高危编造。

    返回空列表表示通过；否则返回全部命中的违规项（便于调试与链路观测）。
    """
    if not text or not text.strip():
        return []

    policy = policy or get_style_policy()
    violations: list[StyleViolation] = []
    lower_text = text.lower()

    # 1. 出戏术语
    for term in policy.meta_terms:
        if term in text:
            violations.append(
                StyleViolation(
                    category="meta_term",
                    matched_term=term,
                    message=f"回复包含出戏术语：{term}",
                )
            )

    # 2. 禁忌表达
    for expression in policy.forbidden_expressions:
        if expression in text:
            violations.append(
                StyleViolation(
                    category="forbidden_expression",
                    matched_term=expression,
                    message=f"回复包含禁忌表达：{expression}",
                )
            )

    # 3. 虚构事实信号：声称记忆相关事实但无记忆支撑
    if policy.require_memory_for_fabrication_signals:
        has_memory_support = bool(injected_memories) or bool(injected_impressions)
        if not has_memory_support:
            for signal in policy.fabrication_signals:
                if signal in lower_text:
                    violations.append(
                        StyleViolation(
                            category="fabrication_signal",
                            matched_term=signal,
                            message=f"回复声称记忆事实但上下文无记忆支撑：{signal}",
                        )
                    )

    return violations


def _term_set(raw: dict[str, Any], key: str) -> frozenset[str]:
    """读取字符串列表并去重；缺省为空集，元素非字符串时报错。"""
    values = raw.get(key, [])
    if not isinstance(values, list):
        raise StylePolicyError(f"Style policy field '{key}' must be a list.")
    terms: set[str] = set()
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise StylePolicyError(f"Style policy field '{key}[{index}]' must be a non-empty string.")
        terms.add(value.strip())
    return frozenset(terms)
