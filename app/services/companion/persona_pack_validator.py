"""人格包归属校验。

S2 阶段实现三方一致性校验的核心子集：
1. manifest.game_id == capability.game_id
2. manifest.requires_capability <= capability.level
3. 人格引用的 scene ∈ capability.scenes
4. reactions 的事件键 ∈ capability.events
5. emotion/gesture/facial_expression ID ∈ capability.presentation_ids
6. abilities 中 ability_id ∈ capability.abilities，behavior_id ∈ capability.behaviors
7. checksum 非 null 时校验（S5 前占位）
8. (game_id, companion_id) 全局唯一由目录结构保证

校验失败一次性返回完整冲突清单，禁止静默忽略。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class PersonaPackValidationError(RuntimeError):
    """人格包归属校验失败。"""


@dataclass(frozen=True)
class Capability:
    """游戏档案声明：某游戏能提供的能力、场景、事件、表现 ID 全集。"""

    game_id: str
    level: str                       # "L0" | "L3"
    scenes: frozenset[str]
    events: frozenset[str]
    presentation_ids: frozenset[str]
    abilities: frozenset[str]
    behaviors: frozenset[str]

    @classmethod
    def from_yaml(cls, path: Path) -> "Capability":
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise PersonaPackValidationError(f"Unable to load capability file: {path}") from error
        if not isinstance(raw, dict):
            raise PersonaPackValidationError(f"Capability file must be a YAML mapping: {path}")

        provides = raw.get("provides") or {}
        if not isinstance(provides, dict):
            raise PersonaPackValidationError(f"Capability file must contain 'provides' mapping: {path}")

        return cls(
            game_id=str(raw.get("game_id", "")),
            level=str(provides.get("capability_level", "L0")),
            scenes=frozenset(provides.get("scenes", [])),
            events=frozenset(
                list(provides.get("events", {}).get("combat", []))
                + list(provides.get("events", {}).get("world", []))
            ),
            presentation_ids=frozenset(provides.get("presentation_ids", [])),
            abilities=frozenset(provides.get("abilities", [])),
            behaviors=frozenset(provides.get("behaviors", [])),
        )


class PersonaPackValidator:
    """按游戏档案校验单个人格包。"""

    _LEVEL_ORDER = {"L0": 0, "L3": 1}

    def __init__(self, capability: Capability) -> None:
        self._capability = capability

    def validate(self, pack_dir: Path, raw: dict[str, Any]) -> None:
        """校验人格包；失败抛出 ``PersonaPackValidationError`` 并附带冲突清单。"""
        manifest = raw.get("manifest") or {}
        if not isinstance(manifest, dict):
            raise PersonaPackValidationError(f"Missing manifest in persona pack: {pack_dir}")

        conflicts: list[str] = []

        # 1. game_id 匹配
        pack_game_id = str(manifest.get("game_id", ""))
        if pack_game_id != self._capability.game_id:
            conflicts.append(
                f"game_id mismatch: pack='{pack_game_id}' vs capability='{self._capability.game_id}'"
            )

        # 2. requires_capability <= capability.level
        required = str(manifest.get("requires_capability", "L0"))
        if self._level_rank(required) > self._level_rank(self._capability.level):
            conflicts.append(
                f"requires_capability '{required}' exceeds game level '{self._capability.level}'"
            )

        # 3. scenes 校验
        conversation_rules = raw.get("conversation_rules") or {}
        scenes = set(conversation_rules.get("allowed_game_states", []))
        unknown_scenes = scenes - self._capability.scenes
        if unknown_scenes:
            conflicts.append(f"unknown scenes: {sorted(unknown_scenes)}")

        # 4. events 校验
        reactions = raw.get("combat_event_reactions", {}) or {}
        world_reactions = raw.get("world_event_reactions", {}) or {}
        event_keys = set(reactions.keys()) | set(world_reactions.keys())
        unknown_events = event_keys - self._capability.events
        if unknown_events:
            conflicts.append(f"unknown events: {sorted(unknown_events)}")

        # 5. presentation IDs 校验
        presentation_ids = self._collect_presentation_ids(raw)
        unknown_presentation = presentation_ids - self._capability.presentation_ids
        if unknown_presentation:
            conflicts.append(f"unknown presentation_ids: {sorted(unknown_presentation)}")

        # 6. abilities / behaviors 校验
        abilities = raw.get("abilities") or {}
        ability_ids = set(abilities.get("ability_ids", []))
        behavior_ids = set(abilities.get("behavior_ids", []))
        unknown_abilities = ability_ids - self._capability.abilities
        unknown_behaviors = behavior_ids - self._capability.behaviors
        if unknown_abilities:
            conflicts.append(f"unknown abilities: {sorted(unknown_abilities)}")
        if unknown_behaviors:
            conflicts.append(f"unknown behaviors: {sorted(unknown_behaviors)}")

        # 7. checksum 占位（S5 前仅检查非 null）
        checksum = manifest.get("checksum")
        if checksum is not None and not isinstance(checksum, str):
            conflicts.append("checksum must be a string or null")

        if conflicts:
            raise PersonaPackValidationError(
                f"Persona pack validation failed for {pack_dir.name}:; " + "; ".join(conflicts)
            )

    def _level_rank(self, level: str) -> int:
        return self._LEVEL_ORDER.get(level, -1)

    def _collect_presentation_ids(self, raw: dict[str, Any]) -> set[str]:
        ids: set[str] = set()
        for key in ("allowed_emotion_ids", "allowed_gesture_ids", "allowed_facial_expression_ids"):
            for item in raw.get(key, []) or []:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    ids.add(item["id"])
        return ids
