"""外部人格包 lint：配额校验 + 提示注入扫描（S5 / T30 / issue #39）。

对 ``PersonaPackLoader`` 合并后的扁平 dict 做两类检查，所有违规聚合为
``PackLintReport.violations``（字符串列表），由外层 guard 一次性抛出，不静默忽略。

- **配额**：dialogue_examples 条数 / 单条 reply_text 字数 / background 字数 / 规则条数；
- **注入**：examples（player + reply_text）、persona 字符串字段、rules 规则文本中
  命中 ``injection_terms`` 黑名单（子串匹配）。

阈值与词表全部来自 ``ExternalPackPolicy``（data/policy/external_pack_policy.yaml）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.companion.pack_policy import ExternalPackPolicy


@dataclass(frozen=True)
class PackLintReport:
    """一次 lint 的结果；``violations`` 为空表示通过。"""

    violations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.violations


class PackLint:
    """按策略对人格包合并 dict 做配额与注入检查。"""

    def __init__(self, policy: ExternalPackPolicy) -> None:
        self._policy = policy

    def run(self, pack_dir: Path, raw: dict[str, Any]) -> PackLintReport:
        violations: list[str] = []
        violations.extend(self._check_quotas(raw))
        violations.extend(self._scan_injection(raw))
        return PackLintReport(violations=tuple(violations))

    # -- 配额 ----------------------------------------------------------------
    def _check_quotas(self, raw: dict[str, Any]) -> list[str]:
        out: list[str] = []
        policy = self._policy

        # dialogue_examples 条数
        examples = raw.get("dialogue_examples") or []
        if not isinstance(examples, list):
            out.append("dialogue_examples must be a list")
        elif len(examples) > policy.max_dialogue_examples:
            out.append(
                f"dialogue_examples count {len(examples)} exceeds limit {policy.max_dialogue_examples}"
            )

        # 单条 reply_text 字数（examples 与 fallback 全部回复）
        for location, text in self._iter_reply_texts(raw):
            if len(text) > policy.max_reply_chars:
                out.append(
                    f"reply_text in {location} length {len(text)} exceeds limit {policy.max_reply_chars}"
                )

        # background 字数
        persona = raw.get("persona") or {}
        background = persona.get("background") if isinstance(persona, dict) else None
        if isinstance(background, str) and len(background) > policy.max_background_chars:
            out.append(
                f"background length {len(background)} exceeds limit {policy.max_background_chars}"
            )

        # 规则条数（response_rules + runtime_state_policy）
        rules = raw.get("conversation_rules") or {}
        if isinstance(rules, dict):
            rule_count = 0
            for key in ("response_rules", "runtime_state_policy"):
                value = rules.get(key)
                if isinstance(value, list):
                    rule_count += len(value)
            if rule_count > policy.max_rules:
                out.append(f"rules count {rule_count} exceeds limit {policy.max_rules}")

        return out

    # -- 注入扫描 -------------------------------------------------------------
    def _scan_injection(self, raw: dict[str, Any]) -> list[str]:
        out: list[str] = []
        terms = self._policy.injection_terms
        if not terms:
            return out

        for location, text in self._scan_targets(raw):
            if not text:
                continue
            for term in terms:
                if term in text:
                    out.append(f"injection term hit in {location}: '{term}'")
                    break  # 同一位置只报第一个命中词，避免一条文本刷屏

        return out

    # -- 遍历器 ---------------------------------------------------------------
    def _iter_reply_texts(self, raw: dict[str, Any]):
        """产出 (位置标签, reply_text)：examples 每条 + fallback 每个候选。"""
        examples = raw.get("dialogue_examples") or []
        if isinstance(examples, list):
            for index, item in enumerate(examples):
                if isinstance(item, dict):
                    presentation = item.get("presentation") or {}
                    text = presentation.get("reply_text") if isinstance(presentation, dict) else None
                    if isinstance(text, str):
                        yield f"examples.yaml[{index}].reply_text", text

        fallbacks = raw.get("fallback_dialogue_responses") or {}
        if isinstance(fallbacks, dict):
            for name, body in fallbacks.items():
                if not isinstance(body, dict):
                    continue
                for index, reply in enumerate(body.get("replies") or []):
                    if isinstance(reply, dict) and isinstance(reply.get("reply_text"), str):
                        yield f"fallbacks.yaml['{name}'][{index}].reply_text", reply["reply_text"]

        default_response = raw.get("default_dialogue_response") or {}
        if isinstance(default_response, dict) and isinstance(default_response.get("reply_text"), str):
            yield "fallbacks.yaml.default_dialogue_response.reply_text", default_response["reply_text"]

    def _scan_targets(self, raw: dict[str, Any]):
        """产出 (位置标签, 文本)：所有应做注入扫描的字符串字段。"""
        # examples 的 player 与 reply_text
        examples = raw.get("dialogue_examples") or []
        if isinstance(examples, list):
            for index, item in enumerate(examples):
                if not isinstance(item, dict):
                    continue
                if isinstance(item.get("player"), str):
                    yield f"examples.yaml[{index}].player", item["player"]
                presentation = item.get("presentation") or {}
                if isinstance(presentation, dict) and isinstance(presentation.get("reply_text"), str):
                    yield f"examples.yaml[{index}].reply_text", presentation["reply_text"]

        # persona 全部字符串值（background / core_traits / values 等）
        persona = raw.get("persona") or {}
        if isinstance(persona, dict):
            for key, value in persona.items():
                yield from self._strings_in(f"persona.yaml.{key}", value)

        # rules 规则文本
        rules = raw.get("conversation_rules") or {}
        if isinstance(rules, dict):
            for key, value in rules.items():
                yield from self._strings_in(f"rules.yaml.{key}", value)

    @staticmethod
    def _strings_in(location: str, value: Any):
        """递归展开字符串 / 列表 / 嵌套 dict 中的字符串叶子节点。"""
        if isinstance(value, str):
            yield location, value
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from PackLint._strings_in(f"{location}[{index}]", item)
        elif isinstance(value, dict):
            for key, item in value.items():
                yield from PackLint._strings_in(f"{location}.{key}", item)
