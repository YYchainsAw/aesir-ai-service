"""人格包校验 / 重算 / 审核登记命令（S5 / T30 / issue #39）。

用法（项目虚拟环境）：
    .venv/Scripts/python.exe -m scripts.lint_persona_pack checksum <pack_dir>
    .venv/Scripts/python.exe -m scripts.lint_persona_pack lint <pack_dir> [--json]
    .venv/Scripts/python.exe -m scripts.lint_persona_pack review-init <pack_dir>

子命令：
- ``checksum``      打印对包内容重算的哈希（sha256:<hex>），用于核对 manifest.checksum。
- ``lint``          全量检查：归属一致性 + checksum 比对 + 配额/注入 lint + 审核记录一致性。
                    返回码：0=全部通过 / 1=有冲突 / 2=运行错误（目录或文件损坏）。
- ``review-init``   生成外部包审核记录骨架到 data/persona_reviews/<game_id>/<companion_id>.yaml
                    （预填内容哈希与 profile_version；reviewer/date/signed_by 留空待人工签字）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Windows 终端默认 GBK，中文输出会乱码
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.companion.pack_checksum import PackChecksumError, compute_pack_checksum  # noqa: E402
from app.services.companion.pack_lint import PackLint  # noqa: E402
from app.services.companion.pack_policy import get_external_pack_policy  # noqa: E402
from app.services.companion.persona_pack_loader import PersonaPackLoadError, PersonaPackLoader  # noqa: E402
from app.services.companion.persona_pack_validator import (  # noqa: E402
    Capability,
    PersonaPackValidationError,
    PersonaPackValidator,
)
from app.services.companion.persona_review import (  # noqa: E402
    PersonaReview,
    ReviewRecordError,
    review_conflicts,
    review_path,
)


def _resolve_pack_dir(arg: str) -> Path:
    path = Path(arg)
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_dir():
        print(f"[2] 人格包目录不存在或不是目录: {path}", file=sys.stderr)
        raise SystemExit(2)
    return path


def _load_capability(game_id: str) -> Capability | None:
    """按 game_id 加载游戏档案；缺失返回 None（lint 记录冲突但继续）。"""
    path = ROOT / "data" / "games" / game_id / "capability.yaml"
    if not path.is_file():
        return None
    try:
        return Capability.from_yaml(path)
    except Exception as error:  # noqa: BLE001 - 档案损坏也按 lint 冲突报告
        print(f"[warn] 无法加载游戏档案 {path}: {error}", file=sys.stderr)
        return None


def collect_report(pack_dir: Path) -> dict:
    """收集全量 lint 报告（归属 + checksum + 配额/注入 + 审核记录）。"""
    report: dict = {"pack_dir": str(pack_dir), "attribution": {}, "checksum": {}, "lint": {}, "review": {}}

    # 1) 加载合并 dict
    try:
        raw = PersonaPackLoader(pack_dir).load()
    except PersonaPackLoadError as error:
        report["fatal"] = f"load failed: {error}"
        report["passed"] = False
        return report

    manifest = raw.get("manifest") or {}
    origin = str(manifest.get("origin", "self"))
    report["origin"] = origin
    game_id = str(manifest.get("game_id", ""))
    companion_id = str(manifest.get("companion_id", pack_dir.name))

    # 2) checksum
    try:
        computed = compute_pack_checksum(pack_dir)
        declared = manifest.get("checksum")
        report["checksum"] = {
            "declared": declared if isinstance(declared, str) else None,
            "computed": computed,
            "ok": declared == computed if isinstance(declared, str) else (origin != "external"),
        }
    except PackChecksumError as error:
        computed = None
        report["checksum"] = {"ok": False, "conflicts": [f"checksum uncomputable: {error}"]}

    # 3) 归属校验（需要游戏档案）
    capability = _load_capability(game_id)
    if capability is None:
        report["attribution"] = {"ok": False, "conflicts": [f"capability file missing for game_id '{game_id}'"]}
    else:
        try:
            PersonaPackValidator(capability).validate(pack_dir, raw)
            report["attribution"] = {"ok": True, "conflicts": []}
        except PersonaPackValidationError as error:
            report["attribution"] = {"ok": False, "conflicts": str(error).split("; ")}

    # 4) 配额 + 注入 lint
    try:
        lint = PackLint(get_external_pack_policy()).run(pack_dir, raw)
        report["lint"] = {"ok": lint.ok, "conflicts": list(lint.violations)}
    except Exception as error:  # noqa: BLE001
        report["lint"] = {"ok": False, "conflicts": [f"lint error: {error}"]}

    # 5) 审核记录（仅外部包）
    if origin == "external" and computed is not None:
        reviews_root = ROOT / "data" / "persona_reviews"
        path = review_path(reviews_root, game_id, companion_id)
        try:
            review = PersonaReview.from_yaml(path)
            conflicts = review_conflicts(manifest, review, computed)
            report["review"] = {"path": str(path), "present": True, "ok": not conflicts, "conflicts": conflicts}
        except ReviewRecordError as error:
            report["review"] = {"path": str(path), "present": False, "ok": False, "conflicts": [str(error)]}
    else:
        report["review"] = {"skipped": "self pack", "ok": True, "conflicts": []}

    dims = ("attribution", "checksum", "lint", "review")
    report["passed"] = all(report[d].get("ok", False) for d in dims) and "fatal" not in report
    return report


def _print_report(report: dict) -> None:
    print(f"人格包: {report['pack_dir']}  (origin={report.get('origin', '?')})")
    if "fatal" in report:
        print(f"  [致命] {report['fatal']}")
        return
    for dim in ("attribution", "checksum", "lint", "review"):
        section = report.get(dim, {})
        mark = "PASS" if section.get("ok") else "FAIL"
        print(f"  [{mark}] {dim}")
        for c in section.get("conflicts", []):
            print(f"        - {c}")
    print(f"==> {'全部通过' if report['passed'] else '存在冲突'}")


def cmd_checksum(pack_dir: Path) -> int:
    try:
        print(compute_pack_checksum(pack_dir))
        return 0
    except PackChecksumError as error:
        print(f"[2] {error}", file=sys.stderr)
        return 2


def cmd_lint(pack_dir: Path, as_json: bool) -> int:
    report = collect_report(pack_dir)
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report)
    if "fatal" in report:
        return 2
    return 0 if report["passed"] else 1


def cmd_review_init(pack_dir: Path) -> int:
    try:
        raw = PersonaPackLoader(pack_dir).load()
    except PersonaPackLoadError as error:
        print(f"[2] 加载人格包失败: {error}", file=sys.stderr)
        return 2
    manifest = raw.get("manifest") or {}
    game_id = str(manifest.get("game_id", ""))
    companion_id = str(manifest.get("companion_id", pack_dir.name))
    profile_version = str(manifest.get("profile_version", ""))
    try:
        computed = compute_pack_checksum(pack_dir)
    except PackChecksumError as error:
        print(f"[2] {error}", file=sys.stderr)
        return 2

    path = review_path(ROOT / "data" / "persona_reviews", game_id, companion_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        print(f"[1] 审核记录已存在，未覆盖: {path}", file=sys.stderr)
        return 1
    import yaml

    skeleton = {
        "companion_id": companion_id,
        "game_id": game_id,
        "profile_version": profile_version,
        "content_hash": computed,
        "lint_status": "pass",
        "lint_conflicts": [],
        "reviewer": "",
        "date": "",
        "signed_by": "",
        "notes": "",
    }
    path.write_text(
        "# 外部人格包人工审核记录（人写签字；机器不自动生成 signed_by）。\n"
        "# review-init 仅预填哈希与版本，结论与签字必须人工填写。\n"
        + yaml.safe_dump(skeleton, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"审核记录骨架已生成: {path}")
    print("请人工填写 reviewer / date / signed_by 后再上线该外部包。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="人格包校验 / 重算 / 审核登记（S5 / T30）")
    parser.add_argument("subcommand", choices=["checksum", "lint", "review-init"])
    parser.add_argument("pack_dir", help="人格包目录路径")
    parser.add_argument("--json", action="store_true", help="lint 子命令输出 JSON（机器可读）")
    args = parser.parse_args()

    pack_dir = _resolve_pack_dir(args.pack_dir)
    if args.subcommand == "checksum":
        return cmd_checksum(pack_dir)
    if args.subcommand == "lint":
        return cmd_lint(pack_dir, args.json)
    return cmd_review_init(pack_dir)


if __name__ == "__main__":
    raise SystemExit(main())
