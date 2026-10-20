"""外部人格包强校验编排（S5 / T30 / issue #39）。

``load_primary()`` 在归属校验通过后调用本守卫；**仅当 manifest ``origin == "external"``
时生效**。自有人格包（缺省 ``self``）第一行直接 return，不触发任何新读盘，
现有三包（alice / bruno / demo-vn）行为完全不变。

对外部包依次跑三步，冲突**聚合**后一次性抛 ``ExternalPackGuardError``：
1. **checksum**：重算内容哈希并与 manifest 声明比对（缺失 / 不符）；
2. **lint**：配额 + 提示注入扫描（``PackLint``）；
3. **审核记录**：加载 ``data/persona_reviews/<game_id>/<companion_id>.yaml`` 并核对
   哈希 / 版本 / lint_status。

外层（profile_repository）把本异常转 ``CompanionProfileError`` -> 503，
不静默跳过、不降级——失败包绝不进入正常加载路径。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.companion.pack_checksum import PackChecksumError, compute_pack_checksum
from app.services.companion.pack_lint import PackLint
from app.services.companion.pack_policy import ExternalPackPolicy, get_external_pack_policy
from app.services.companion.persona_review import (
    PersonaReview,
    ReviewRecordError,
    review_conflicts,
    review_path,
)


class ExternalPackGuardError(RuntimeError):
    """外部人格包守卫校验失败（聚合多条冲突）。"""


class ExternalPackGuard:
    """外部人格包强校验编排器。"""

    def __init__(
        self,
        policy: ExternalPackPolicy | None = None,
        reviews_root: Path | None = None,
    ) -> None:
        self._policy = policy  # None 时懒加载 get_external_pack_policy（仅 external 包触发）
        self._reviews_root = reviews_root

    def check(self, pack_dir: Path, raw: dict[str, Any]) -> None:
        """校验外部人格包；非 external 包直接放行，失败聚合抛 ``ExternalPackGuardError``。"""
        manifest = raw.get("manifest") or {}
        if not isinstance(manifest, dict):
            manifest = {}
        if str(manifest.get("origin", "self")) != "external":
            return  # 自有人格包：零校验、零新读盘

        conflicts: list[str] = []

        # ① checksum：重算 + 与声明比对
        computed: str | None = None
        try:
            computed = compute_pack_checksum(pack_dir)
        except PackChecksumError as error:
            conflicts.append(f"checksum uncomputable: {error}")

        declared = manifest.get("checksum")
        if not isinstance(declared, str) or not declared:
            conflicts.append("external pack checksum is missing")
        elif computed is not None and declared != computed:
            conflicts.append(f"checksum mismatch: declared '{declared}' vs computed '{computed}'")

        # ② lint：配额 + 注入扫描
        policy = self._policy or get_external_pack_policy()
        lint = PackLint(policy).run(pack_dir, raw)
        conflicts.extend(lint.violations)

        # ③ 审核记录：存在性 + 一致性（仅当哈希可计算时才有意义）
        if computed is not None:
            conflicts.extend(self._review_conflicts(manifest, pack_dir, computed))

        if conflicts:
            raise ExternalPackGuardError(
                f"External pack guard failed for {pack_dir.name}:; " + "; ".join(conflicts)
            )

    def _review_conflicts(
        self, manifest: dict[str, Any], pack_dir: Path, computed_hash: str
    ) -> list[str]:
        game_id = str(manifest.get("game_id", ""))
        companion_id = str(manifest.get("companion_id", pack_dir.name))
        reviews_root = self._resolve_reviews_root()
        path = review_path(reviews_root, game_id, companion_id)

        try:
            review = PersonaReview.from_yaml(path)
        except ReviewRecordError as error:
            return [f"review record missing or invalid: {path} ({error})"]

        return review_conflicts(manifest, review, computed_hash)

    def _resolve_reviews_root(self) -> Path:
        if self._reviews_root is not None:
            return self._reviews_root
        from app.config import get_settings

        return Path(get_settings().persona_reviews_dir)
