from typer.testing import CliRunner

from astock_lens.cli.app import app


def test_trade_commands_are_registered() -> None:
    result = CliRunner().invoke(app, ["trade", "--help"])
    assert result.exit_code == 0
    for name in ("evaluate", "show", "override", "execute", "review", "stats"):
        assert name in result.stdout
