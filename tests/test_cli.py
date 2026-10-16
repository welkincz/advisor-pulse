from typer.testing import CliRunner

from pulse import __version__
from pulse.cli import app

runner = CliRunner()

COMMANDS = ["generate", "ingest", "run", "backfill", "export", "narrate"]


def test_help_lists_every_subcommand() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in COMMANDS:
        assert command in result.output


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == __version__


def test_stub_names_its_issue_and_exits_zero() -> None:
    result = runner.invoke(app, ["export"])
    assert result.exit_code == 0
    assert "issue #46" in result.output


def test_backfill_requires_range() -> None:
    result = runner.invoke(app, ["backfill"])
    assert result.exit_code != 0
