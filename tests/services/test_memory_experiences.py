"""共同经历接线测试：世界事件 → 摘要层（对话实测复盘 2026-09-21）。

背景：摘要层此前在真实运行中恒为空——``record_experience`` 只有测试和
demo 在调。这里钉住「哪些事件算共同经历」「细节只取上报方给过的」
「同一事件重放不重复记」三件事。
"""

from __future__ import annotations

from app.services.memory.experiences import build_experience
from app.services.memory.store import get_memory_store, reset_memory_stores


class TestBuildExperience:
    def test_region_event_uses_snapshot_region(self):
        entry = build_experience(
            "region_first_entered", occurred_at="2026-09-13T12:00:00Z", region_id="region.forest"
        )
        assert entry is not None
        assert "region.forest" in entry.content
        assert entry.source == "shared_experience"
        assert entry.game_time == "2026-09-13T12:00:00Z"

    def test_gift_event_prefers_details_over_fallback(self):
        entry = build_experience("gift_given", details={"item_id": "item.moonflower"})
        assert entry is not None
        assert "item.moonflower" in entry.content

    def test_missing_detail_falls_back_to_generic_wording(self):
        # 没有细节就写泛一点，绝不编一个名字出来。
        entry = build_experience("gift_given")
        assert entry is not None
        assert "item." not in entry.content
        assert "礼物" in entry.content

    def test_protecting_the_companion_is_high_importance(self):
        entry = build_experience("player_protected_companion")
        assert entry is not None and entry.importance == "high"

    def test_transient_combat_states_are_not_memories(self):
        # 血量告急/蓝量过低是当下要处理的情况，不是共同经历。
        for event_type in ("player_hp_critical", "companion_mp_low", "boss_stunned"):
            assert build_experience(event_type) is None


class TestWorldEventWiring:
    def _payload(self, event_id: str, event_type: str, details: dict | None = None) -> dict:
        return {
            "protocol_version": "0.3",
            "request_id": "req.mem.test.001",
            "companion_id": "companion.alice",
            "event": {
                "event_id": event_id,
                "event_type": event_type,
                "occurred_at": "2026-09-13T12:00:00Z",
                "sequence": 1,
                "details": details or {},
            },
            "world_context": {
                "snapshot_id": "44444444-4444-4444-8444-444444444444",
                "captured_at": "2026-09-13T12:00:00Z",
                "scene": "exploration",
                "region": {"region_id": "region.forest.north", "first_visit": True},
                "player": {"id": "party.player", "hp_percent": 80},
                "companion": {"id": "companion.alice", "hp_percent": 90, "mp_percent": 70},
            },
        }

    def test_world_event_records_a_shared_experience(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        from app.main import app

        monkeypatch.setenv("AESIR_MEMORY_ROOT", str(tmp_path))
        reset_memory_stores()
        try:
            response = TestClient(app).post(
                "/v1/world/events", json=self._payload("event.mem.001", "gift_given", {"item_id": "item.moonflower"})
            )
            assert response.status_code == 200
            summaries = get_memory_store("companion.alice").snapshot().summaries
            assert len(summaries) == 1
            assert "item.moonflower" in summaries[0].content
        finally:
            reset_memory_stores()

    def test_replayed_event_does_not_double_record(self, monkeypatch, tmp_path):
        """幂等重放：关系不重复计分，共同经历也不重复记。"""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.services.tactical import event_policy

        monkeypatch.setenv("AESIR_MEMORY_ROOT", str(tmp_path))
        reset_memory_stores()
        event_policy._reset_seen_events()
        try:
            client = TestClient(app)
            payload = self._payload("event.mem.002", "promise_kept", {"promise_id": "promise.notes"})
            assert client.post("/v1/world/events", json=payload).status_code == 200
            replay = client.post("/v1/world/events", json=payload)
            assert replay.json()["duplicate"] is True

            summaries = get_memory_store("companion.alice").snapshot().summaries
            assert len(summaries) == 1
        finally:
            event_policy._reset_seen_events()
            reset_memory_stores()
