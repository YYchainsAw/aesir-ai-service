"""对话信号埋点单元 + 集成测试（RL 前置：奖励的前提是数据）。

覆盖：玩家否定反馈检测（实测日志出现过的形态）、复读度（句式相似度）、
话题延续判定、对话链路落 JSONL、埋点故障绝不阻塞对话主流程。
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app
from app.services.companion.dialogue_signals import (
    detect_negative_feedback,
    record_turn_signal,
    repetition_score,
    topic_continued,
)

client = TestClient(app)


# -- 玩家否定反馈（记错 / 编造 / 复读的玩家侧表述）------------------------
class TestNegativeFeedback:
    def test_real_log_phrrases_are_detected(self):
        # 实测日志里出现过的真实负面信号形态。
        for text in (
            "你是不是又模糊了我们上次的对话",
            "你幻视了，我没说过",
            "我也没答应你我钓了鱼给你烤",
            "你经常返回相同的语句",
        ):
            assert detect_negative_feedback(text) is not None

    def test_plain_chat_is_not_negative(self):
        for text in ("今天天气不错", "钓鱼吗", "最近过得还好吗", "好"):
            assert detect_negative_feedback(text) is None


# -- 复读度（本条回复 vs 近期回复的相似度）--------------------------------
class TestRepetitionScore:
    def test_near_identical_reply_scores_high(self):
        previous = ["嗯，那就走吧。天还亮着，我陪你多走一段。"]
        current = "嗯，那就走吧。天还亮着，我陪你多走一段。"
        assert repetition_score(current, previous) > 0.9

    def test_distinct_reply_scores_low(self):
        previous = ["我还挺喜欢钓鱼的，小时候常去河边。"]
        current = "照明术随时能放，你怕黑就站我旁边。"
        assert repetition_score(current, previous) < 0.2

    def test_no_history_scores_zero(self):
        assert repetition_score("随便说点什么", []) == 0.0

    def test_same_sentence_pattern_flags_repetitive(self):
        # 实测复读形态：换尾词但句式雷同（「……不过……吧」模式）。
        previous = ["不过钓鱼这事你总提过吧"]
        current = "不过烤鱼这事你总提过吧"
        assert repetition_score(current, previous) > 0.6


# -- 话题延续（engagement 粗代理）------------------------------------------
class TestTopicContinued:
    def test_first_turn_has_no_comparison(self):
        assert topic_continued("钓鱼吗", None) is None

    def test_same_topic_is_continued(self):
        assert topic_continued("钓鱼吗", "记得我上次说我们一起去钓鱼吗") is True

    def test_topic_switch_is_not_continued(self):
        assert topic_continued("最近过得还好吗", "钓鱼吗") is False


# -- 落盘与容错 ------------------------------------------------------------
class TestRecordTurnSignal:
    def test_chat_writes_signal_record(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AESIR_DIALOGUE_SIGNALS_DIR", str(tmp_path))
        payload = {
            "text": "钓鱼吗",
            "companion_id": "companion.alice",
            "game_state": "conversation",
            "session_id": "sig-1",
        }
        response = client.post("/v1/companion/chat", json=payload)
        assert response.status_code == 200

        lines = (tmp_path / "aesir" / "companion.alice.jsonl").read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[-1])
        assert record["session_id"] == "sig-1"
        assert record["player_text"] == "钓鱼吗"
        assert record["source"] in ("mock", "llm", "fallback")
        assert "negative_feedback" in record["signals"]
        assert "repetition_score" in record["signals"]
        assert record["signals"]["topic_continued"] is None  # 会话第一轮
        assert isinstance(record["injected_topics"], list)

    def test_failure_never_blocks_dialogue(self, monkeypatch, tmp_path):
        # 目录指向一个不可能创建的路径（Windows 下非法字符）→ 对话仍然成功。
        monkeypatch.setenv("AESIR_DIALOGUE_SIGNALS_DIR", str(tmp_path / "bad<>|dir"))
        response = client.post(
            "/v1/companion/chat",
            json={
                "text": "你好",
                "companion_id": "companion.alice",
                "game_state": "conversation",
            },
        )
        assert response.status_code == 200

    def test_repetition_visible_across_turns(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AESIR_DIALOGUE_SIGNALS_DIR", str(tmp_path))
        payload = {
            "companion_id": "companion.alice",
            "game_state": "conversation",
            "session_id": "sig-2",
        }
        # 同一会话连发两轮：第二轮记录里有历史可比较。
        client.post("/v1/companion/chat", json={**payload, "text": "钓鱼吗"})
        client.post("/v1/companion/chat", json={**payload, "text": "记得我上次说我们一起去钓鱼吗"})

        lines = (tmp_path / "aesir" / "companion.alice.jsonl").read_text(encoding="utf-8").splitlines()
        second = json.loads(lines[-1])
        assert second["signals"]["topic_continued"] is True
        assert second["signals"]["repetition_score"] >= 0.0

    def test_game_id_partitions_signal_files(self, monkeypatch, tmp_path):
        """不同 game_id 的信号写入不同子目录（S1）。"""
        monkeypatch.setenv("AESIR_DIALOGUE_SIGNALS_DIR", str(tmp_path))
        base = {
            "companion_id": "companion.alice",
            "session_id": None,
            "player_text": "你好",
            "reply_text": "嗯，我在。",
            "source": "mock",
            "emotion_id": "",
            "gesture_id": "",
            "facial_expression_id": "",
            "game_state": "conversation",
        }
        record_turn_signal(**base, game_id="aesir")
        record_turn_signal(**base, game_id="other")
        assert (tmp_path / "aesir" / "companion.alice.jsonl").exists()
        assert (tmp_path / "other" / "companion.alice.jsonl").exists()
