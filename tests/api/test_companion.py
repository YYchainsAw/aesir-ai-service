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
    assert body["reply_text"] == "我在呢。想聊什么？"
    assert body["emotion_id"] == "emotion.bright"
    assert body["gesture_id"] == "gesture.cheerful_idle"
    assert body["facial_expression_id"] == "face.bright_smile"
    assert body["interruptible"] is True
    assert body["source"] == "mock"


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
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.companion import profile_repository as pr

    bad = tmp_path / "bad.yaml"
    bad.write_text("identity: {id: [unclosed", encoding="utf-8")
    # __init__ 的默认路径在 import 时已绑定，须替换构造逻辑指向坏文件。
    monkeypatch.setattr(
        pr.CompanionProfileRepository, "__init__", lambda self: setattr(self, "_profile_path", bad)
    )

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/v1/companion/chat",
        json={"text": "你好", "companion_id": "companion.alice", "game_state": "exploration"},
    )
    assert response.status_code == 503
    assert "profile" in response.json()["detail"].lower()
