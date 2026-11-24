"""Four synthetic production-dialogue probes; opt-in paid calls, isolated state.

Answers are saved for review, not auto-declared factually correct by substring.
No player data is used. --execute permits at most eight generations (one style
retry per case); fallback source is retained and must not count as LLM success.
"""
import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.execute:
        print('Dry run: four synthetic dialogue cases; no provider calls.')
        return
    from app.config import get_settings
    get_settings()  # Load private configuration without printing it.
    from app.schemas.companion_dialogue import CompanionDialogueRequest
    from app.schemas.memory import MemoryEntry
    from app.services.companion.dialogue_service import create_dialogue_reply, _prepare_dialogue
    from app.services.memory.store import get_memory_store
    cases = [
        ('hometown_only_cn','玩家的家乡是港口小镇。','我小时候住的那座镇子是哪儿？','unknown'),
        ('hometown_only_en','玩家的家乡是港口小镇。','Where did I live as a child?','unknown'),
        ('explicit_childhood','玩家小时候住在山城。','我小时候住在哪里？','山城'),
        ('hometown_control','玩家的家乡是港口小镇。','我的家乡是哪儿？','港口'),
    ]
    rows = []
    changes = {'AESIR_COORDINATION_BACKEND':'memory','AESIR_SCOPE_STORAGE_BACKEND':'json',
               'AESIR_COMPANION_BACKEND':'llm','AESIR_DIALOGUE_DATA_ORIGIN':'evaluation',
               'AESIR_DIALOGUE_DATA_RUN_ID':'p2'}
    previous = {key:os.environ.get(key) for key in changes}
    with TemporaryDirectory(prefix='p2-') as temp:
        for key in ('MEMORY_ROOT','RELATIONSHIP_ROOT','DIALOGUE_SIGNALS_DIR'):
            name = 'AESIR_'+key
            previous[name] = os.environ.get(name)
        try:
            os.environ.update(changes)
            for name, fact, query, expected in cases:
                for key in ('MEMORY_ROOT','RELATIONSHIP_ROOT','DIALOGUE_SIGNALS_DIR'):
                    os.environ['AESIR_'+key] = str(Path(temp)/name/key.lower())
                store = get_memory_store('companion.alice',game_id='aesir')
                store.record_fact(MemoryEntry(content=fact,importance='critical'))
                request = CompanionDialogueRequest(text=query,companion_id='companion.alice',session_id=name)
                recalled = _prepare_dialogue(request)[3]
                response = create_dialogue_reply(request)
                rows.append(dict(case=name,query=query,expected=expected,
                    injected_contents=[entry.content for entry in recalled],response=response.model_dump(mode='json')))
                args.output.parent.mkdir(parents=True,exist_ok=True)
                args.output.write_text(json.dumps(dict(synthetic=True,automatic_semantic_verdict=False,
                    cases=rows),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                print(json.dumps(dict(case=name,source=response.source,reply=response.reply_text),ensure_ascii=False),flush=True)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key,None)
                else:
                    os.environ[key] = value


if __name__ == '__main__':
    main()
