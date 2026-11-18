import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.scoped import ScopedForgetRequest,ScopedForgetResponse,ScopedMemoryEntriesResponse

ROOT=Path('data/golden/memory')


@pytest.mark.parametrize('filename,model',[
    ('forget_request.json',ScopedForgetRequest),
    ('forget_response.json',ScopedForgetResponse),
    ('entries_response.json',ScopedMemoryEntriesResponse)])
def test_memory_management_golden_roundtrip(filename,model):
    data=json.loads((ROOT/filename).read_text(encoding='utf-8'))
    assert model.model_validate(data).model_dump(mode='json')==data


@pytest.mark.parametrize('values',[[],['a'],['10000000-0000-4000-8000-000000000001']*2])
def test_forget_rejects_empty_invalid_or_repeated_entry_ids(values):
    data=json.loads((ROOT/'forget_request.json').read_text(encoding='utf-8'))
    data['entry_ids']=values
    with pytest.raises(ValidationError):
        ScopedForgetRequest.model_validate(data)
