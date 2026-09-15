"""/v1/companion/chat/stream（SSE）契约测试：帧形状、mock 后端、错误路径。"""

import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _parse_frames(text: str) -> list[tuple[str, dict]]:
    """把原始 SSE 文本解析成 (event, data) 列表。"""
    frames = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        kind = ""
        data = {}
        for line in block.splitlines():
            if line.startswith("event:"):
                kind = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:"):].strip())
        frames.append((kind, data))
    return frames


def test_stream_mock_backend_emits_delta_then_meta() -> None:
    response = client.post(
        "/v1/companion/chat/stream",
        json={"text": "我们出发吧。", "session_id": "stream-1"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    frames = _parse_frames(response.text)
    kinds = [kind for kind, _ in frames]
    assert kinds[-1] == "meta"
    assert "delta" in kinds
    assert kinds == ["delta", "meta"]  # mock 后端：单 delta（全文）+ meta

    delta = next(data for kind, data in frames if kind == "delta")
    meta = next(data for kind, data in frames if kind == "meta")
    assert delta["text"] == meta["reply_text"]
    assert meta["source"] == "mock"
    assert meta["session_id"] == "stream-1"
    assert set(
        (
            "protocol_version",
            "companion_id",
            "session_id",
            "reply_text",
            "emotion_id",
            "gesture_id",
            "facial_expression_id",
            "interruptible",
            "source",
            "relationship_stage",
        )
    ) <= set(meta)


def test_stream_rejects_combat_state() -> None:
    response = client.post(
        "/v1/companion/chat/stream",
        json={"text": "进攻", "game_state": "combat"},
    )
    assert response.status_code == 422


def test_stream_unknown_companion_returns_404_before_stream() -> None:
    response = client.post(
        "/v1/companion/chat/stream",
        json={"text": "你好", "companion_id": "companion.nobody"},
    )
    assert response.status_code == 404
