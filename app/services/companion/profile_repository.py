"""从主队友 YAML 读取并校验静态人设资料。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.services.companion.persona_pack_loader import PersonaPackLoadError, PersonaPackLoader
from app.services.companion.persona_pack_validator import (
    Capability,
    PersonaPackValidationError,
    PersonaPackValidator,
)

# 默认主队友人设源（S2 迁移后为人格包目录；旧单文件 YAML 仍可通过显式路径加载）。
_PRIMARY_PROFILE_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "personas" / "aesir" / "companion.alice"
)
_COMPANIONS_DIR = Path(__file__).resolve().parents[3] / "data" / "companions"
_PERSONAS_DIR = Path(__file__).resolve().parents[3] / "data" / "personas"
_CAPABILITY_PATH = Path(__file__).resolve().parents[3] / "data" / "games" / "aesir" / "capability.yaml"
_capability_cache: Capability | None = None


class CompanionProfileError(RuntimeError):
    """角色资料缺失或不符合配置契约。"""


class UnknownCompanionError(CompanionProfileError):
    """调用方请求的队友 ID 不属于已登记的主队友。"""


@dataclass(frozen=True)
class DialoguePresentation:
    reply_text: str
    emotion_id: str
    gesture_id: str
    facial_expression_id: str
    interruptible: bool


@dataclass(frozen=True)
class DialogueExample:
    """一条 few-shot 示范：玩家输入 + 艾莉的示范回复（含表现 ID）。"""

    category: str
    player: str
    presentation: DialoguePresentation


@dataclass(frozen=True)
class FallbackReplyCategory:
    """无 LLM 回退的类别：关键词集合 + 候选回复（按 YAML 出现顺序判序）。"""

    name: str
    keywords: tuple[str, ...]
    replies: tuple[DialoguePresentation, ...]


@dataclass(frozen=True)
class CompanionProfile:
    """从 YAML 提取出的、聊天服务所需的已校验人设快照。"""

    companion_id: str
    display_name: str
    game_name: str
    wake_words: frozenset[str]
    self_reference_blacklist: frozenset[str]
    raw: dict[str, Any]
    allowed_emotion_ids: frozenset[str]
    allowed_gesture_ids: frozenset[str]
    allowed_facial_expression_ids: frozenset[str]
    default_dialogue_response: DialoguePresentation
    dialogue_examples: tuple[DialogueExample, ...]
    fallback_reply_categories: tuple[FallbackReplyCategory, ...]


class CompanionProfileRepository:
    """人设 YAML / 人格包目录的读取与校验；调用方一般走 ``get_profile()`` 的 mtime 缓存。"""

    def __init__(self, profile_source: Path = _PRIMARY_PROFILE_PATH) -> None:
        self._profile_source = profile_source

    def _load_raw(self) -> dict[str, Any]:
        """从单文件或人格包目录读取原始 YAML 数据。"""
        source = getattr(self, "_profile_source", None) or getattr(self, "_profile_path", None)
        if source is None:
            raise CompanionProfileError("CompanionProfileRepository has no profile source.")
        if source.is_dir():
            return PersonaPackLoader(source).load()
        return yaml.safe_load(source.read_text(encoding="utf-8"))

    def load_primary(self) -> CompanionProfile:
        source = getattr(self, "_profile_source", None) or getattr(self, "_profile_path", None)
        try:
            raw_profile = self._load_raw()
        except PersonaPackLoadError as error:
            raise CompanionProfileError(str(error)) from error
        except (OSError, yaml.YAMLError) as error:
            raise CompanionProfileError("Unable to load the primary companion profile.") from error

        if not isinstance(raw_profile, dict):
            raise CompanionProfileError("Primary companion profile must be a YAML mapping.")

        # 人格包目录在加载后进行归属校验；旧单文件 YAML 兼容期跳过。
        if source is not None and source.is_dir():
            validator = PersonaPackValidator(_get_capability())
            try:
                validator.validate(source, raw_profile)
            except PersonaPackValidationError as error:
                raise CompanionProfileError(str(error)) from error

        identity = _required_mapping(raw_profile, "identity")
        companion_id = _required_string(identity, "id")
        display_name = _required_string(identity, "display_name")
        # persona pack 的 game_name 来自 manifest.yaml 顶层；旧单文件来自 identity.game_name。
        game_name = _optional_string(raw_profile, "game_name") or _optional_string(identity, "game_name") or "Aesir"
        wake_words = _optional_string_set(identity, "wake_words") or _optional_string_set(identity, "aliases") or frozenset({display_name.lower()})
        # 角色自指黑名单：默认取 aliases + display_name + 常见变体，避免把她自己的名字/称呼当成玩家话题。
        default_self_blacklist = set(wake_words)
        default_self_blacklist.add(display_name.lower())
        default_self_blacklist.update({"爱莉"})
        self_reference_blacklist = _optional_string_set(identity, "self_reference_blacklist") or frozenset(default_self_blacklist)
        allowed_emotions = _id_set(raw_profile, "allowed_emotion_ids")
        allowed_gestures = _id_set(raw_profile, "allowed_gesture_ids")
        allowed_faces = _id_set(raw_profile, "allowed_facial_expression_ids")
        default_response = _default_response(raw_profile)

        if default_response.emotion_id not in allowed_emotions:
            raise CompanionProfileError("Default dialogue emotion ID is not registered in the profile.")
        if default_response.gesture_id not in allowed_gestures:
            raise CompanionProfileError("Default dialogue gesture ID is not registered in the profile.")
        if default_response.facial_expression_id not in allowed_faces:
            raise CompanionProfileError("Default dialogue facial-expression ID is not registered in the profile.")

        return CompanionProfile(
            companion_id=companion_id,
            display_name=display_name,
            game_name=game_name,
            wake_words=frozenset(wake_words),
            self_reference_blacklist=frozenset(self_reference_blacklist),
            raw=raw_profile,
            allowed_emotion_ids=frozenset(allowed_emotions),
            allowed_gesture_ids=frozenset(allowed_gestures),
            allowed_facial_expression_ids=frozenset(allowed_faces),
            default_dialogue_response=default_response,
            dialogue_examples=_dialogue_examples(raw_profile, allowed_emotions, allowed_gestures, allowed_faces),
            fallback_reply_categories=_fallback_reply_categories(
                raw_profile, allowed_emotions, allowed_gestures, allowed_faces
            ),
        )

    def require_primary(self, companion_id: str) -> CompanionProfile:
        profile = self.load_primary()
        if companion_id != profile.companion_id:
            raise UnknownCompanionError(f"Unsupported companion_id: {companion_id}")
        return profile

    # -- 多角色注册表（SDD T010 / FR-044）------------------------------------
    def load_registered(self, companion_id: str) -> CompanionProfile:
        """按角色标识解析注册表内任意角色（data/personas/ 目录优先，兼容 data/companions/*.yaml）。

        未登记的角色抛 ``UnknownCompanionError``——调用方据此返回 404，
        **不**回退到默认角色的人格（FR-044）。
        注册表扫描过程中若任何角色配置损坏，统一抛 ``CompanionProfileError``，
        由路由层转 503（避免未捕获异常导致 500）。
        """
        for source in self._profile_sources():
            try:
                profile = get_profile(source)
            except Exception as error:
                raise CompanionProfileError(
                    f"Failed to load companion profile from {source}: {error}"
                ) from error
            if profile.companion_id == companion_id:
                return profile
        raise UnknownCompanionError(f"Unregistered companion_id: {companion_id}")

    def list_registered(self) -> list[str]:
        """当前注册表内的全部角色标识（/health 与 console 展示用）。"""
        try:
            return [get_profile(source).companion_id for source in self._profile_sources()]
        except Exception as error:
            raise CompanionProfileError(
                f"Failed to list companion profiles: {error}"
            ) from error

    def _profile_sources(self) -> list[Path]:
        """返回所有可加载的人设源：人格包目录优先，旧单文件 YAML 兼容。"""
        sources: list[Path] = []
        # 1) 人格包目录：data/personas/<game_id>/<companion_id>/
        try:
            if _PERSONAS_DIR.is_dir():
                for game_dir in sorted(_PERSONAS_DIR.iterdir()):
                    if game_dir.is_dir():
                        sources.extend(sorted(d for d in game_dir.iterdir() if d.is_dir()))
        except OSError:
            pass
        # 2) 旧单文件 YAML：data/companions/*.yaml（兼容期）。
        # 共存语义：人格包目录优先扫描；若同一 companion_id 同时存在目录包与旧 YAML，
        # load_registered 命中先扫描到的目录包，旧 YAML 不生效（不视为冲突，便于灰度迁移）。
        try:
            if _COMPANIONS_DIR.is_dir():
                sources.extend(sorted(_COMPANIONS_DIR.glob("*.yaml")))
        except OSError:
            pass
        # 3) 兜底主队友
        if not sources:
            return [_PRIMARY_PROFILE_PATH]
        return sources


def _get_capability() -> Capability:
    """读取当前游戏档案；进程内缓存。"""
    global _capability_cache  # noqa: PLW0603
    if _capability_cache is None:
        _capability_cache = Capability.from_yaml(_CAPABILITY_PATH)
    return _capability_cache


# ---------------------------------------------------------------------------
# mtime 缓存 provider：YAML 是静态配置，文件未变时不必每请求重读重解析。
# 文件变更（mtime 变化）自动失效重读，保留「YAML 是唯一静态来源」语义；
# 解析失败不写缓存（损坏文件每次请求都如实报 503）。
# ---------------------------------------------------------------------------
_profile_cache: dict[Path, tuple[int, CompanionProfile]] = {}


def _source_mtime(source: Path) -> int:
    """计算人设源的 mtime：单文件取文件 mtime；人格包目录取所有 YAML 最大 mtime。"""
    if source.is_dir():
        mtimes = [p.stat().st_mtime_ns for p in source.rglob("*.yaml") if p.is_file()]
        if not mtimes:
            raise OSError(f"No YAML files found in persona pack: {source}")
        return max(mtimes)
    return source.stat().st_mtime_ns


def get_profile(profile_source: Path | None = None) -> CompanionProfile:
    """读取主队友人设（带 mtime 缓存）。支持单文件路径或人格包目录。

    注意：测试 monkeypatch ``CompanionProfileRepository.__init__`` 指向坏文件时，
    缓存 key 按构造时的实际路径计算，异常不落缓存，行为与每次直读一致。
    """
    repo = CompanionProfileRepository(profile_source) if profile_source is not None else CompanionProfileRepository()
    # 兼容旧测试 monkeypatch：优先 _profile_source，回退 _profile_path。
    source = getattr(repo, "_profile_source", None) or getattr(repo, "_profile_path", None)  # noqa: SLF001
    try:
        mtime = _source_mtime(source)
    except OSError:
        _profile_cache.pop(source, None)
        return repo.load_primary()  # 抛 CompanionProfileError → 503

    cached = _profile_cache.get(source)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    profile = repo.load_primary()
    _profile_cache[source] = (mtime, profile)
    return profile


def get_registered_profile(companion_id: str) -> CompanionProfile:
    """模块级多角色入口（SDD T010）：按标识取已登记角色，未登记抛 404 语义异常。

    既有 ``get_profile()``（无参）仍返回主队友，供旧链路（companion chat /
    tactical acknowledgement / event reactions）使用，语义不变。
    """
    return CompanionProfileRepository().load_registered(companion_id)


def list_registered_companions() -> list[str]:
    """注册表内全部角色标识（健康检查与调试台展示）。"""
    return CompanionProfileRepository().list_registered()


def _required_mapping(container: dict[str, Any], key: str) -> dict[str, Any]:
    value = container.get(key)
    if not isinstance(value, dict):
        raise CompanionProfileError(f"Profile field '{key}' must be a mapping.")
    return value


def _required_string(container: dict[str, Any], key: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CompanionProfileError(f"Profile field '{key}' must be a non-empty string.")
    return value


def _optional_string(container: dict[str, Any], key: str) -> str | None:
    """读取可选字符串字段；缺失或空字符串均返回 None。"""
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _optional_string_set(container: dict[str, Any], key: str) -> frozenset[str] | None:
    """读取可选字符串列表字段并去重；缺失、非列表或全空时返回 None。"""
    values = container.get(key)
    if not isinstance(values, list):
        return None
    items = {str(v).strip().lower() for v in values if isinstance(v, str) and v.strip()}
    return frozenset(items) if items else None


def _id_set(profile: dict[str, Any], key: str) -> set[str]:
    values = profile.get(key)
    if not isinstance(values, list):
        raise CompanionProfileError(f"Profile field '{key}' must be a list.")

    ids = {
        item.get("id")
        for item in values
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
    }
    if not ids:
        raise CompanionProfileError(f"Profile field '{key}' contains no IDs.")
    return ids


def _default_response(profile: dict[str, Any]) -> DialoguePresentation:
    defaults = _required_mapping(profile, "default_dialogue_response")
    return DialoguePresentation(
        reply_text=_required_string(defaults, "reply_text"),
        emotion_id=_required_string(defaults, "emotion_id"),
        gesture_id=_required_string(defaults, "gesture_id"),
        facial_expression_id=_required_string(defaults, "facial_expression_id"),
        interruptible=defaults.get("interruptible", True),
    )


def _presentation(
    container: dict[str, Any], *, where: str, allowed_emotions: set, allowed_gestures: set, allowed_faces: set
) -> DialoguePresentation:
    """从映射构造回复表现并校验 ID 白名单（default/示例/回退候选共用）。"""
    presentation = DialoguePresentation(
        reply_text=_required_string(container, "reply_text"),
        emotion_id=_required_string(container, "emotion_id"),
        gesture_id=_required_string(container, "gesture_id"),
        facial_expression_id=_required_string(container, "facial_expression_id"),
        interruptible=container.get("interruptible", True),
    )
    _validate_presentation_ids(presentation, where, allowed_emotions, allowed_gestures, allowed_faces)
    return presentation


def _validate_presentation_ids(
    presentation: DialoguePresentation, where: str, allowed_emotions: set, allowed_gestures: set, allowed_faces: set
) -> None:
    if presentation.emotion_id not in allowed_emotions:
        raise CompanionProfileError(f"Emotion ID in {where} is not registered in the profile.")
    if presentation.gesture_id not in allowed_gestures:
        raise CompanionProfileError(f"Gesture ID in {where} is not registered in the profile.")
    if presentation.facial_expression_id not in allowed_faces:
        raise CompanionProfileError(f"Facial-expression ID in {where} is not registered in the profile.")


def _dialogue_examples(
    profile: dict[str, Any], allowed_emotions: set, allowed_gestures: set, allowed_faces: set
) -> tuple[DialogueExample, ...]:
    """few-shot 示范样例（可选字段，缺省为空组）。"""
    examples = profile.get("dialogue_examples", [])
    if not isinstance(examples, list):
        raise CompanionProfileError("Profile field 'dialogue_examples' must be a list.")

    parsed: list[DialogueExample] = []
    for index, item in enumerate(examples):
        if not isinstance(item, dict):
            raise CompanionProfileError(f"Dialogue example #{index} must be a mapping.")
        parsed.append(
            DialogueExample(
                category=_required_string(item, "category"),
                player=_required_string(item, "player"),
                presentation=_presentation(
                    item, where=f"dialogue example #{index}", allowed_emotions=allowed_emotions,
                    allowed_gestures=allowed_gestures, allowed_faces=allowed_faces,
                ),
            )
        )
    return tuple(parsed)


def _fallback_reply_categories(
    profile: dict[str, Any], allowed_emotions: set, allowed_gestures: set, allowed_faces: set
) -> tuple[FallbackReplyCategory, ...]:
    """分类回退候选（可选字段，缺省为空组；YAML 出现顺序即判序）。"""
    categories = profile.get("fallback_dialogue_responses", {})
    if not isinstance(categories, dict):
        raise CompanionProfileError("Profile field 'fallback_dialogue_responses' must be a mapping.")

    parsed: list[FallbackReplyCategory] = []
    for name, body in categories.items():
        if not isinstance(body, dict):
            raise CompanionProfileError(f"Fallback reply category '{name}' must be a mapping.")
        keywords = body.get("keywords", [])
        replies = body.get("replies", [])
        if not isinstance(keywords, list) or not all(isinstance(k, str) and k for k in keywords):
            raise CompanionProfileError(f"Fallback reply category '{name}' keywords must be a list of strings.")
        if not isinstance(replies, list) or not replies:
            raise CompanionProfileError(f"Fallback reply category '{name}' must contain at least one reply.")
        parsed.append(
            FallbackReplyCategory(
                name=str(name),
                keywords=tuple(keywords),
                replies=tuple(
                    _presentation(
                        reply, where=f"fallback reply '{name}'", allowed_emotions=allowed_emotions,
                        allowed_gestures=allowed_gestures, allowed_faces=allowed_faces,
                    )
                    for reply in replies
                ),
            )
        )
    return tuple(parsed)
