"""Tests for CLI version reporting."""

from click.testing import CliRunner

from tether import __version__
from tether.cli import cli


def test_cli_reports_source_version() -> None:
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_verify_exits_nonzero_when_session_is_blocked(monkeypatch) -> None:
    def fake_run_verify(*, config_path=None, verbose=False) -> bool:
        return False

    monkeypatch.setattr("tether.verify.verifier.run_verify", fake_run_verify)

    result = CliRunner().invoke(cli, ["verify"])
    assert result.exit_code == 1
