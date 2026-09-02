from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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


def test_companion_chat_requires_text() -> None:
    response = client.post("/v1/companion/chat", json={"text": ""})

    assert response.status_code == 422
