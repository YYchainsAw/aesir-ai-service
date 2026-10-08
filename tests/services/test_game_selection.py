"""S3/T028 一进程一游戏：配置化游戏选择、注册表范围限制与跨游戏拒绝回归。"""

from __future__ import annotations

import pytest

from app.services.companion import profile_repository as pr
from app.services.companion.profile_repository import (
    CompanionProfileRepository,
    UnknownCompanionError,
)


@pytest.fixture()
def _clean_caches(monkeypatch):
    """每个用例前清缓存，用例后恢复默认游戏并再清一次，避免串味。"""
    pr._profile_cache.clear()  # noqa: SLF001
    pr._capability_cache.clear()  # noqa: SLF001
    yield monkeypatch
    monkeypatch.delenv("AESIR_GAME_ID", raising=False)
    pr._profile_cache.clear()  # noqa: SLF001
    pr._capability_cache.clear()  # noqa: SLF001


def test_default_game_is_aesir(_clean_caches) -> None:
    assert pr._current_game_id() == "aesir"  # noqa: SLF001
    ids = pr.list_registered_companions()
    assert set(ids) == {"companion.alice", "companion.bruno"}


def test_demo_vn_registry_only_loads_own_personas(_clean_caches) -> None:
    _clean_caches.setenv("AESIR_GAME_ID", "demo-vn")
    ids = pr.list_registered_companions()
    assert ids == ["companion.narrator"]


def test_cross_game_companion_id_rejected_not_fallback(_clean_caches) -> None:
    """demo-vn 进程请求 Alice：404 语义，不回退默认角色、不混用 Aesir 能力。"""
    _clean_caches.setenv("AESIR_GAME_ID", "demo-vn")
    with pytest.raises(UnknownCompanionError):
        CompanionProfileRepository().load_registered("companion.alice")


def test_demo_vn_default_profile_source_is_narrator(_clean_caches) -> None:
    _clean_caches.setenv("AESIR_GAME_ID", "demo-vn")
    profile = CompanionProfileRepository().load_primary()
    assert profile.companion_id == "companion.narrator"
    assert profile.game_name == "demo-vn"


def test_demo_vn_capability_is_l0_and_validates_pack(_clean_caches) -> None:
    """demo-vn 档案按 game_id 独立加载；旁白包通过其归属校验（L0 <= L0）。"""
    _clean_caches.setenv("AESIR_GAME_ID", "demo-vn")
    capability = pr._get_capability()  # noqa: SLF001
    assert capability.game_id == "demo-vn"
    assert capability.level == "L0"
    # 归属校验已在 load_primary 内执行；能通过即证明校验链按当前游戏档案工作
    CompanionProfileRepository().load_primary()


def test_game_capability_caches_are_independent(_clean_caches) -> None:
    aesir_cap = pr._get_capability()  # noqa: SLF001
    _clean_caches.setenv("AESIR_GAME_ID", "demo-vn")
    vn_cap = pr._get_capability()  # noqa: SLF001
    assert aesir_cap.game_id == "aesir"
    assert vn_cap.game_id == "demo-vn"
    assert aesir_cap is not vn_cap
