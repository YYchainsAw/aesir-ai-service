"""lint_persona_pack 脚本测试（S5 / T30）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from scripts import lint_persona_pack as script


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _build_self_pack(tmp_path: Path) -> Path:
    """构造一个自有人格包（无 origin、checksum=null）。"""
    pack = tmp_path / "companion.demo"
    pack.mkdir()
    _write(pack / "manifest.yaml", {
        "profile_version": "0.2", "companion_id": "companion.demo", "game_id": "aesir",
        "requires_capability": "L3",
    })
    _write(pack / "persona.yaml", {"identity": {"id": "companion.demo", "display_name": "Demo"}})
    _write(pack / "rules.yaml", {"conversation_rules": {"allowed_game_states": ["exploration"]}})
    _write(pack / "examples.yaml", {"dialogue_examples": []})
    _write(pack / "reactions.yaml", {"combat_event_reactions": {}, "world_event_reactions": {}})
    _write(pack / "fallbacks.yaml", {
        "default_dialogue_response": {
            "reply_text": "嗯？", "emotion_id": "emotion.bright",
            "gesture_id": "gesture.cheerful_idle", "facial_expression_id": "face.gentle_smile",
        },
    })
    _write(pack / "presentation.yaml", {
        "allowed_emotion_ids": [{"id": "emotion.bright"}],
        "allowed_gesture_ids": [{"id": "gesture.cheerful_idle"}],
        "allowed_facial_expression_ids": [{"id": "face.gentle_smile"}],
    })
    return pack


def _run(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["lint_persona_pack", *argv])
    try:
        return script.main()
    except SystemExit as exc:
        return exc.code or 0


def test_checksum_subcommand_exit0(tmp_path: Path, monkeypatch, capsys) -> None:
    pack = _build_self_pack(tmp_path)
    code = _run(monkeypatch, ["checksum", str(pack)])
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("sha256:")


def test_lint_bad_dir_exit2(tmp_path: Path, monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["lint", str(tmp_path / "no-such-pack")])
    assert code == 2


def test_lint_self_pack_pass_or_attribution_exit(tmp_path: Path, monkeypatch, capsys) -> None:
    """自有人格包：checksum/review 维度必过；attribution 依真实 aesir 档案。
    重点验证脚本正常跑完且返回码为 0 或 1（不抛异常 / 不为 2）。"""
    pack = _build_self_pack(tmp_path)
    code = _run(monkeypatch, ["lint", str(pack)])
    assert code in (0, 1)
    out = capsys.readouterr().out
    assert "attribution" in out


def test_lint_json_output_keys(tmp_path: Path, monkeypatch, capsys) -> None:
    pack = _build_self_pack(tmp_path)
    _run(monkeypatch, ["lint", str(pack), "--json"])
    out = capsys.readouterr().out
    import json
    report = json.loads(out)
    for key in ("attribution", "checksum", "lint", "review", "passed"):
        assert key in report


def test_review_init_generates_skeleton(tmp_path: Path, monkeypatch, capsys) -> None:
    # 把脚本的 ROOT 指到 tmp，使审核记录骨架落在隔离目录，不污染真实仓库
    monkeypatch.setattr(script, "ROOT", tmp_path)
    pack = _build_self_pack(tmp_path)
    # 改成外部包，review-init 才有意义
    _write(pack / "manifest.yaml", {
        "profile_version": "0.2", "companion_id": "companion.demo", "game_id": "aesir",
        "requires_capability": "L3", "origin": "external", "checksum": None,
    })
    code = _run(monkeypatch, ["review-init", str(pack)])
    assert code == 0
    out = capsys.readouterr().out
    assert "审核记录骨架已生成" in out
    skeleton = tmp_path / "data" / "persona_reviews" / "aesir" / "companion.demo.yaml"
    assert skeleton.is_file()
    assert "signed_by" in skeleton.read_text(encoding="utf-8")
