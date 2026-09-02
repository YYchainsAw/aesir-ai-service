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
    assert body["order"]["intent"] == "conditional_cast"
    assert body["order"]["trigger"] == {"target": "Boss", "state": "Stunned"}
    assert body["order"]["action"]["ability_id"] == "Explosion"


def test_hold_ability() -> None:
    response = client.post("/parse-command", json={"text": "艾琳，保留爆裂魔法"})

    assert response.status_code == 200
    body = response.json()
    assert body["recognized"] is True
    assert body["order"]["intent"] == "hold_ability"
    assert body["order"]["action"] == {"type": "HoldAbility", "ability_id": "Explosion"}


def test_prioritize_attack() -> None:
    response = client.post("/parse-command", json={"text": "艾琳，优先普通攻击"})

    assert response.status_code == 200
    body = response.json()
    assert body["recognized"] is True
    assert body["order"]["intent"] == "prioritize_attack"
    assert body["order"]["action"] == {"type": "Attack"}


def test_follow_keep_distance() -> None:
    response = client.post("/parse-command", json={"text": "艾琳，跟随我并保持距离"})

    assert response.status_code == 200
    body = response.json()
    assert body["recognized"] is True
    assert body["order"]["intent"] == "follow_keep_distance"
    assert body["order"]["action"]["type"] == "Follow"


def test_retreat() -> None:
    response = client.post("/parse-command", json={"text": "艾琳，撤退并优先保命"})

    assert response.status_code == 200
    body = response.json()
    assert body["recognized"] is True
    assert body["order"]["intent"] == "retreat"
    assert body["order"]["action"] == {"type": "Retreat"}


def test_unknown_command_is_rejected_safely() -> None:
    response = client.post("/parse-command", json={"text": "艾琳，马上释放不存在的技能"})

    assert response.status_code == 200
    assert response.json()["recognized"] is False
    assert response.json()["order"] is None
