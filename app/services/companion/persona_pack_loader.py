"""人格包目录化加载器。

S2 阶段把单一人设 YAML 拆分为一个目录（persona pack），内含 8 个 YAML 文件：
manifest.yaml、persona.yaml、rules.yaml、examples.yaml、reactions.yaml、
fallbacks.yaml、presentation.yaml、abilities.yaml。

本模块负责读取这 8 个文件并合并为与旧单文件结构兼容的字典，
使 ``profile_repository.py`` 的校验/构造逻辑无需大改。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class PersonaPackLoadError(RuntimeError):
    """人格包目录缺失、文件损坏或格式非法。"""


REQUIRED_FILES = (
    "manifest.yaml",
    "persona.yaml",
    "rules.yaml",
    "examples.yaml",
    "reactions.yaml",
    "fallbacks.yaml",
    "presentation.yaml",
)
OPTIONAL_FILES = ("abilities.yaml",)


class PersonaPackLoader:
    """从目录加载人格包，合并为单文件式字典。"""

    def __init__(self, pack_dir: Path) -> None:
        self._pack_dir = pack_dir

    def load(self) -> dict[str, Any]:
        """读取目录下所有 YAML 文件并合并。

        合并规则与旧单文件 YAML 顶层字段对齐：
        - ``manifest.yaml`` 提供 ``profile_version``、``companion_id``、``game_id`` 等。
        - ``persona.yaml`` 的 ``identity`` / ``persona`` / ``relationship_stage_personas`` /
          ``speaking_style`` 直接展开到顶层。
        - ``rules.yaml`` 的 ``conversation_rules`` / ``combat_expression_rules`` /
          ``tactical_acknowledgements`` 展开到顶层。
        - ``examples.yaml`` 的 ``dialogue_examples`` 展开到顶层。
        - ``reactions.yaml`` 的 ``combat_event_reactions`` / ``world_event_reactions`` 展开到顶层。
        - ``fallbacks.yaml`` 的 ``fallback_dialogue_responses`` /
          ``default_dialogue_response`` 展开到顶层。
        - ``presentation.yaml`` 的 ``allowed_emotion_ids`` / ``allowed_gesture_ids`` /
          ``allowed_facial_expression_ids`` / ``ue_mapping_contract`` 展开到顶层。
        - ``abilities.yaml`` 内容放入 ``raw["abilities"]``，供后续能力子集读取。
        """
        if not self._pack_dir.is_dir():
            raise PersonaPackLoadError(f"Persona pack directory does not exist: {self._pack_dir}")

        merged: dict[str, Any] = {}
        for name in REQUIRED_FILES:
            data = self._read_yaml(name)
            if data is None:
                raise PersonaPackLoadError(f"Missing required persona pack file: {name}")
            self._merge_file(merged, name, data)

        for name in OPTIONAL_FILES:
            data = self._read_yaml(name)
            if data is not None:
                self._merge_file(merged, name, data)

        return merged

    def _read_yaml(self, name: str) -> dict[str, Any] | None:
        path = self._pack_dir / name
        if not path.is_file():
            return None
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise PersonaPackLoadError(f"Unable to load persona pack file {name}: {error}") from error
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise PersonaPackLoadError(f"Persona pack file {name} must be a YAML mapping.")
        return raw

    def _merge_file(self, merged: dict[str, Any], name: str, data: dict[str, Any]) -> None:
        if name == "manifest.yaml":
            # profile_version 优先使用 manifest 里的声明；companion_id/game_id 也来自 manifest。
            merged["profile_version"] = data.get("profile_version", merged.get("profile_version", "0.2"))
            merged["companion_id"] = data.get("companion_id")
            merged["game_name"] = data.get("game_id", "Aesir")
            merged["manifest"] = data
        elif name == "persona.yaml":
            for key in ("identity", "persona", "relationship_stage_personas", "speaking_style"):
                if key in data:
                    merged[key] = data[key]
        elif name == "rules.yaml":
            for key in ("conversation_rules", "combat_expression_rules", "tactical_acknowledgements"):
                if key in data:
                    merged[key] = data[key]
        elif name == "examples.yaml":
            if "dialogue_examples" in data:
                merged["dialogue_examples"] = data["dialogue_examples"]
        elif name == "reactions.yaml":
            for key in ("combat_event_reactions", "world_event_reactions"):
                if key in data:
                    merged[key] = data[key]
        elif name == "fallbacks.yaml":
            for key in ("fallback_dialogue_responses", "default_dialogue_response"):
                if key in data:
                    merged[key] = data[key]
        elif name == "presentation.yaml":
            for key in (
                "allowed_emotion_ids",
                "allowed_gesture_ids",
                "allowed_facial_expression_ids",
                "ue_mapping_contract",
            ):
                if key in data:
                    merged[key] = data[key]
        elif name == "abilities.yaml":
            #  abilities 不展开到顶层，避免与旧单文件字段冲突；放入 raw 后续读取。
            merged.setdefault("abilities", {})
            merged["abilities"].update(data)
