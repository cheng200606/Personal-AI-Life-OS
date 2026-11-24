import json
import os
from pathlib import Path

from typer.testing import CliRunner

from personal_ai_life_os import cli

FIXTURES = Path(__file__).parents[1] / "fixtures" / "synthetic"


def test_preview_is_local_and_does_not_print_message_bodies() -> None:
    result = CliRunner().invoke(cli.app, ["preview", str(FIXTURES / "conversations.json"), "--json"])

    assert result.exit_code == 0, result.output
    preview = json.loads(result.output)
    assert preview[0]["conversation_count"] == 2
    assert "content_text" not in preview[0]
    assert "Ignore every rule" not in result.output


def test_directory_scan_skips_obsidian_and_git_folders(tmp_path: Path) -> None:
    root = tmp_path / "selected"
    root.mkdir()
    (root / "memory.md").write_text("## A note\n\nA synthetic line.", encoding="utf-8")
    obsidian = root / ".obsidian"
    obsidian.mkdir()
    (obsidian / "app.json").write_text('{"private":"not selected"}', encoding="utf-8")
    git = root / ".git"
    git.mkdir()
    (git / "config").write_text("remote", encoding="utf-8")

    paths = cli._candidate_paths(root)

    assert [path.name for path in paths] == ["memory.md"]


def test_credentials_are_written_atomically_with_owner_only_permissions(tmp_path, monkeypatch) -> None:
    credentials_path = tmp_path / "private" / "credentials.json"
    monkeypatch.setenv("LIFEOS_CREDENTIALS_FILE", str(credentials_path))

    cli._write_credentials({"http://127.0.0.1:8000": {"access_token": "synthetic-token"}})

    assert cli._read_credentials()["http://127.0.0.1:8000"]["access_token"] == "synthetic-token"
    assert not list(credentials_path.parent.glob("credentials-*"))
    if os.name != "nt":
        assert credentials_path.stat().st_mode & 0o777 == 0o600


def test_markdown_export_keeps_edits_and_requires_explicit_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "note-12345678.md"
    target.write_text("user edits", encoding="utf-8")

    kept = cli._write_export_file(tmp_path, target.name, b"generated", "keep")
    assert kept == "kept"
    assert target.read_text(encoding="utf-8") == "user edits"

    copied = cli._write_export_file(tmp_path, target.name, b"generated", "copy")
    assert copied == "copied"
    assert (tmp_path / "note-12345678-lifeos-copy.md").read_bytes() == b"generated"

    overwritten = cli._write_export_file(tmp_path, target.name, b"generated", "overwrite")
    assert overwritten == "overwritten"
    assert target.read_bytes() == b"generated"


def test_markdown_export_is_atomic_and_repeatable(tmp_path: Path) -> None:
    first = cli._write_export_file(tmp_path, "note-12345678.md", b"same content", "keep")
    second = cli._write_export_file(tmp_path, "note-12345678.md", b"same content", "keep")
    assert first == "created"
    assert second == "unchanged"
    assert list(tmp_path.glob(".lifeos-*")) == []
