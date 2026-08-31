from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["protocol_version"] == "1.0"


def test_example_command_returns_tactical_order() -> None:
    response = client.post(
        "/parse-command",
        json={"text": "艾琳，等 Boss 眩晕时使用爆裂魔法。"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recognized"] is True
    assert body["order"]["agent"] == "Eirin"
    assert body["order"]["trigger"] == {"target": "Boss", "state": "Stunned"}
    assert body["order"]["action"]["ability_id"] == "Explosion"


def test_unknown_command_is_rejected_safely() -> None:
    response = client.post("/parse-command", json={"text": "艾琳，马上释放不存在的技能"})

    assert response.status_code == 200
    assert response.json()["recognized"] is False
    assert response.json()["order"] is None
