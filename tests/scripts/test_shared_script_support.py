"""Shared report IO must cover both scoped and legacy data without counting junk."""
import json
from scripts.support.jsonl import iter_records
from scripts.rl.dialogue_signal_report import build_report

def test_nested_scoped_and_legacy_signals_are_both_read(tmp_path):
    for relative in ("aesir/companion.alice.jsonl", "aesir/player/save/companion.bruno/run/day.jsonl"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"companion_id": "companion.bruno", "source": "mock"})
                        + '\ninvalid\n[]\nnull\n42\n', encoding="utf-8")
    assert len(list(iter_records(tmp_path))) == 2
    assert build_report(tmp_path)["total_records"] == 2
