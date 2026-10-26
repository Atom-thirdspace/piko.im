import pytest

from piko_cli.cli import build_parser


@pytest.fixture(scope="module")
def subs():
    return build_parser()._subparsers._group_actions[0].choices


def flags(parser):
    return {opt for action in parser._actions for opt in action.option_strings}


def test_parser_builds():
    build_parser()


def test_no_duplicate_commands(subs):
    names = list(subs)
    assert len(names) == len(set(names))


def test_every_command_has_a_handler(subs):
    assert [n for n, sp in subs.items() if sp.get_default("fn") is None] == []


@pytest.mark.parametrize("command,flag", [
    ("login", "--token"), ("get", "--into"), ("submit", "--force"),
    ("submit", "--check"), ("watch", "--plain"), ("stress", "--gen"),
])
def test_flag_is_on_its_own_command(subs, command, flag):
    assert flag in flags(subs[command])


def test_global_flags_are_on_the_root():
    assert {"--json", "--version", "--api"} <= flags(build_parser())


def test_version_prints_and_exits(capsys):
    from piko_cli.cli import main

    assert main(["--version"]) == 0
    assert "piko-cli" in capsys.readouterr().out
