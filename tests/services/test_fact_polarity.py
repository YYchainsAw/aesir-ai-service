import pytest
from app.services.memory.facts import is_grounded


@pytest.mark.parametrize('fact,sources,expected',[
 ('玩家去过港口',['我没去过港口。'],False),
 ('玩家没去过港口',['我去过港口。'],False),
 ('玩家没去过港口',['我没有去过港口。'],True),
 ('玩家喜欢苹果',['我不喜欢苹果，但喜欢香蕉。'],False),
 ('玩家喜欢香蕉',['我不喜欢苹果，但喜欢香蕉。'],True),
 ('玩家喜欢香蕉',['我不喜欢苹果但喜欢香蕉。'],True),
 ('玩家喜欢苹果',['我现在不喜欢苹果。','我喜欢苹果。'],False),
 ('玩家喜欢苹果',['我现在喜欢苹果。','我不喜欢苹果。'],True),
 ('玩家养了一只叫小黑的猫',['它叫小黑。','我养了只猫。'],True),
 ('玩家住在港口',['如果我住在港口会怎么样？'],False),
 ('玩家住在港口',['我住在港口吗？'],False),
 ('玩家住在港口',['我可能住在港口。'],False),
 ('玩家可能住在港口',['我可能住在港口。'],True),
 ('玩家小时候住在港口',['我现在住在港口。'],False),
 ('玩家小时候住在港口',['我小时候住在港口。'],True),
])
def test_strong_polarity_conflicts_do_not_become_persistent_facts(fact,sources,expected):
    assert is_grounded(fact,sources) is expected


def test_latest_history_correction_prevents_old_positive_fact_from_being_reextracted(monkeypatch):
    from app.schemas.companion_dialogue import CompanionDialogueRequest,CompanionDialogueResponse
    from app.services.companion.session_memory import get_session_memory
    from app.services.companion.dialogue_service import _record_turn
    from app.services.memory.store import get_memory_store
    monkeypatch.setenv('AESIR_DIALOGUE_HISTORY_TURNS','3')
    memory=get_session_memory(3)
    memory.record('polarity-chronology','我喜欢苹果。','收到',companion_id='companion.alice')
    memory.record('polarity-chronology','我现在不喜欢苹果。','收到',companion_id='companion.alice')
    request=CompanionDialogueRequest(text='嗯',session_id='polarity-chronology')
    response=CompanionDialogueResponse(companion_id='companion.alice',reply_text='收到',source='llm',
        emotion_id='emotion.bright',gesture_id='gesture.cheerful_idle',facial_expression_id='face.bright_smile',interruptible=True)
    _record_turn(request,response,topics=[],reply_topics=[],facts=['玩家喜欢苹果'],salient=False,game_id='aesir')
    assert not get_memory_store('companion.alice').snapshot().archive
