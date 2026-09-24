from fastapi.testclient import TestClient
import pytest

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def force_mock_companion_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """接口测试不得依赖开发者本机的真实 LLM 配置。"""
    monkeypatch.setenv("AESIR_COMPANION_BACKEND", "mock")


def test_companion_chat_returns_mock_ue_friendly_response() -> None:
    response = client.post(
        "/v1/companion/chat",
        json={
            "text": "今天过得怎么样？",
            "companion_id": "companion.alice",
            "game_state": "exploration",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["protocol_version"] == "0.1"
    assert body["companion_id"] == "companion.alice"
    # 「怎么样」命中 question 类别：回复从候选中按稳定哈希选取（不再是单句静态）。
    assert body["reply_text"] != "我在呢。想聊什么？"
    assert body["emotion_id"] == "emotion.thoughtful"
    assert body["gesture_id"] == "gesture.think"
    assert body["facial_expression_id"] == "face.thoughtful"
    assert body["interruptible"] is True
    assert body["source"] == "mock"
    # US7（T076）链路信息：人设版本 + 本轮注入的记忆条数（按通道）
    assert body["persona_revision"] != ""
    assert isinstance(body["memory_layers"], dict)
    assert set(body["memory_layers"]) == {"long_term", "impressions"}


def test_companion_chat_mock_fallback_is_deterministic_per_text() -> None:
    """同一输入恒同回复（跨请求稳定），不同输入可在候选间分散。"""
    payload = {"companion_id": "companion.alice", "game_state": "exploration"}
    first = client.post("/v1/companion/chat", json={"text": "你为什么会跟着我？", **payload}).json()
    second = client.post("/v1/companion/chat", json={"text": "你为什么会跟着我？", **payload}).json()
    assert first["reply_text"] == second["reply_text"]

    other = client.post("/v1/companion/chat", json={"text": "前面还有什么危险吗？", **payload}).json()
    assert other["reply_text"] != "我在呢。想聊什么？"


def test_companion_chat_mock_tactical_request_is_redirected_in_character() -> None:
    response = client.post(
        "/v1/companion/chat",
        json={"text": "帮我打那个 Boss！", "game_state": "exploration", "companion_id": "companion.alice"},
    )

    assert response.status_code == 200
    body = response.json()
    # 人设纪律：拒绝战斗请求必须以角色口吻，不得出现「指令」「频道」等出戏术语。
    for jargon in ("指令", "频道", "接口", "协议", "系统"):
        assert jargon not in body["reply_text"]
    assert body["emotion_id"] in {"emotion.playfully_annoyed", "emotion.serious"}


def test_companion_chat_mock_unmatched_text_returns_default() -> None:
    response = client.post(
        "/v1/companion/chat",
        json={"text": "天气不错", "game_state": "exploration", "companion_id": "companion.alice"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reply_text"] == "我在呢。想聊什么？"
    assert body["source"] == "mock"


def test_companion_chat_accepts_and_echoes_session_id() -> None:
    response = client.post(
        "/v1/companion/chat",
        json={
            "text": "天气不错",
            "companion_id": "companion.alice",
            "game_state": "exploration",
            "session_id": "ue-session-42",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "ue-session-42"
    assert body["reply_text"] == "我在呢。想聊什么？"


def test_companion_chat_rejects_blank_session_id() -> None:
    response = client.post(
        "/v1/companion/chat",
        json={"text": "你好", "session_id": ""},
    )
    assert response.status_code == 422


def test_companion_chat_rejects_combat_state() -> None:
    response = client.post(
        "/v1/companion/chat",
        json={"text": "帮我攻击 Boss", "game_state": "combat"},
    )

    assert response.status_code == 422


def test_companion_chat_rejects_unknown_companion() -> None:
    response = client.post(
        "/v1/companion/chat",
        json={"text": "你好", "companion_id": "companion.unknown"},
    )

    assert response.status_code == 404


def test_companion_chat_requires_text() -> None:
    response = client.post("/v1/companion/chat", json={"text": ""})

    assert response.status_code == 422


def test_corrupt_profile_yaml_returns_503_not_500(monkeypatch, tmp_path) -> None:
    # 回归锁定（docs/logs/2026-09-07.md 已知未修项）：YAML 损坏 → 503 配置错误，
    # 而不是未捕获 CompanionProfileError 导致的 500。
    # 多角色路由后，损坏发生在注册表扫描阶段，须 monkeypatch 整个 companions 目录。
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.companion import profile_repository as pr

    companions_dir = tmp_path / "companions"
    companions_dir.mkdir()
    bad = companions_dir / "primary_companion.yaml"
    bad.write_text("identity: {id: [unclosed", encoding="utf-8")
    monkeypatch.setattr(pr, "_COMPANIONS_DIR", companions_dir)
    monkeypatch.setattr(pr, "_PRIMARY_PROFILE_PATH", bad)
    # 清除 mtime 缓存，避免旧缓存命中
    pr._profile_cache.clear()

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/v1/companion/chat",
        json={"text": "你好", "companion_id": "companion.alice", "game_state": "exploration"},
    )
    assert response.status_code == 503
    assert "profile" in response.json()["detail"].lower()
