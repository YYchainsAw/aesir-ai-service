"""Prevent extracted business services from depending on HTTP route adapters."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_services_do_not_import_http_route_modules():
    offenders = []
    for path in (ROOT / "app/services").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.api"):
                offenders.append(str(path.relative_to(ROOT)))
            if isinstance(node, ast.Import) and any(n.name.startswith("app.api") for n in node.names):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []

def test_scoped_does_not_call_legacy_route_modules():
    source = ROOT / "app/api/v1/scoped.py"
    imports = [n.module for n in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
               if isinstance(n, ast.ImportFrom)]
    assert not any((name or "").startswith("app.api.v1") for name in imports)
