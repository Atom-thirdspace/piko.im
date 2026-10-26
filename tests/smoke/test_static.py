import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"

NODE = shutil.which("node")


def js_files():
    return sorted(STATIC.rglob("*.js"))


def test_there_are_scripts():
    assert js_files()


@pytest.mark.skipif(NODE is None, reason="node is not on PATH")
@pytest.mark.parametrize("path", js_files(), ids=lambda p: p.name)
def test_javascript_parses(path):
    args = [NODE, "--check", str(path)]
    proc = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0 and "module" in (proc.stderr or "").lower():
        proc = subprocess.run([NODE, "--input-type=module", "--check",
                               "-e", path.read_text(encoding="utf-8")],
                              capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("path", sorted(STATIC.rglob("*.json")),
                         ids=lambda p: p.name)
def test_json_parses(path):
    json.loads(path.read_text(encoding="utf-8"))


def test_css_braces_balance():
    for path in sorted(STATIC.rglob("*.css")):
        text = path.read_text(encoding="utf-8", errors="replace")
        assert text.count("{") == text.count("}"), path.name
