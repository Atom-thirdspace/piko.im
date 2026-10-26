import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def editor_section(name):
    text = (ROOT / "static" / "editor.js").read_text(encoding="utf-8")
    if name == "LANGS":
        body = text.split("var LANGS", 1)[1].split("var STARTERS", 1)[0]
    else:
        body = text.split("var STARTERS", 1)[1].split("var PAIRS", 1)[0]
    return set(re.findall(r"^\s{4}(\w+)\s*:", body, re.M))


def judge_languages():
    from server.judge.languages import LANGUAGES

    return set(LANGUAGES)


def cli_languages():
    from piko_cli import runner

    return set(runner.LANGUAGES)


def test_every_judge_language_has_a_label():
    from server.judge.languages import LANGUAGES

    for key, lang in LANGUAGES.items():
        assert lang.label, "%s has no label" % key
        assert lang.image and lang.source_name and lang.run_cmd, key


def test_language_keys_fit_the_column():
    for key in judge_languages():
        assert len(key) <= 16, key


def test_editor_highlights_every_language():
    missing = judge_languages() - editor_section("LANGS")
    assert missing == set(), (
        "no syntax config, so these fall back to Python highlighting: %s"
        % sorted(missing))


def test_editor_has_a_starter_for_every_language():
    missing = judge_languages() - editor_section("STARTERS")
    assert missing == set(), "no starter template: %s" % sorted(missing)


def test_cli_runs_what_it_offers():
    extra = cli_languages() - judge_languages()
    assert extra == set(), "CLI offers unknown languages: %s" % sorted(extra)


@pytest.mark.parametrize("key", sorted(cli_languages()))
def test_cli_language_specs_are_complete(key):
    from piko_cli import runner

    spec = runner.LANGUAGES[key]
    assert spec["source"] and spec["label"] and spec["stub"]
    assert callable(spec["run"])
