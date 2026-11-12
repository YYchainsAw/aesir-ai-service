"""Sync and completed SSE replies must publish the same commit metadata."""
from app.schemas.companion_dialogue import CompanionDialogueRequest
from app.schemas.memory import MemoryEntry
from app.services.companion import dialogue_service as dialogue


def test_mock_sync_and_sse_share_stage_memory_and_delta_commit(monkeypatch):
    calls = []
    monkeypatch.setattr(dialogue, "_relationship_stage", lambda *a, **k: "close")
    monkeypatch.setattr(dialogue, "_recall", lambda *a, **k: [MemoryEntry(content="玩家喜欢长剑")])
    monkeypatch.setattr(dialogue, "_recall_impressions", lambda *a, **k: [])
    def record(request, response, **fields):
        calls.append(fields)
        return 3  # Check propagation of the commit result, without real persistence.
    monkeypatch.setattr(dialogue, "_record_turn", record)
    request = CompanionDialogueRequest(text="你好", companion_id="companion.alice", session_id="parity")
    sync = dialogue.create_dialogue_reply(request)
    frames = list(dialogue.stream_dialogue_reply(request))
    streamed = frames[-1].response
    assert [f.kind for f in frames] == ["delta", "meta"]
    assert sync.relationship_delta == streamed.relationship_delta == 3
    assert sync.relationship_stage == streamed.relationship_stage == "close"
    assert sync.memory_layers == streamed.memory_layers
    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert calls[0]["memory_cited"] is True
    assert calls[0]["relationship_stage"] == "close"
