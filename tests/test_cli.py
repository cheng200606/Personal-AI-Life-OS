import json
import os
from contextlib import contextmanager
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


def test_cli_login_sync_and_conflict_safe_export(client, monkeypatch, tmp_path: Path) -> None:
    credentials_path = tmp_path / "credentials.json"
    monkeypatch.setenv("LIFEOS_CREDENTIALS_FILE", str(credentials_path))
    monkeypatch.delenv("LIFEOS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("LIFEOS_API_URL", raising=False)
    assert client.post(
        "/api/v1/auth/register",
        json={"email": "cli@example.com", "password": "correct horse battery staple", "timezone": "UTC"},
    ).status_code == 201

    def post_login(url: str, *, json: dict, timeout: int):
        assert timeout == 30
        return client.post(url.removeprefix("http://127.0.0.1:8000"), json=json)

    monkeypatch.setattr(cli.httpx, "post", post_login)
    runner = CliRunner()
    logged_in = runner.invoke(
        cli.app,
        ["login", "--email", "cli@example.com", "--password", "correct horse battery staple"],
    )
    assert logged_in.exit_code == 0, logged_in.output

    class ApiClientAdapter:
        def __init__(self, token: str) -> None:
            self.headers = {"Authorization": "Bearer " + token}

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def get(self, path: str, *, params=None):
            return client.get(path, params=params, headers=self.headers)

        def post(self, path: str, *, data=None, files=None, json=None):
            return client.post(path, data=data, files=files, json=json, headers=self.headers)

    @contextmanager
    def authed_client(api_url: str):
        yield ApiClientAdapter(cli._access_token(api_url))

    monkeypatch.setattr(cli, "_authed_client", authed_client)

    identity = runner.invoke(cli.app, ["whoami"])
    assert identity.exit_code == 0, identity.output
    assert "cli@example.com" in identity.output

    synced = runner.invoke(cli.app, ["sync", str(FIXTURES / "memory.md"), "--yes"])
    assert synced.exit_code == 0, synced.output
    assert "Imported memory.md:" in synced.output
    token = cli._access_token("http://127.0.0.1:8000")
    headers = {"Authorization": "Bearer " + token}
    source = client.get("/api/v1/sources", headers=headers).json()[0]
    assert source["kind"] == "memory_markdown"
    item = client.get("/api/v1/timeline", headers=headers).json()["items"][0]
    tag = client.post("/api/v1/tags", headers=headers, json={"name": "CLI research"}).json()
    collection = client.post("/api/v1/collections", headers=headers, json={"name": "CLI release"}).json()
    organized = client.put(
        f"/api/v1/items/{item['id']}/organization",
        headers=headers,
        json={"tag_ids": [tag["id"]], "collection_ids": [collection["id"]]},
    )
    assert organized.status_code == 200, organized.text
    destination = tmp_path / "vault"
    destination.mkdir()

    exported = runner.invoke(
        cli.app,
        ["export", str(destination), "--item-id", item["id"], "--yes"],
    )
    assert exported.exit_code == 0, exported.output
    target = next(destination.glob("*.md"))
    assert item["id"] in target.read_text(encoding="utf-8")
    assert 'tags: ["CLI research"]' in target.read_text(encoding="utf-8")
    assert 'collections: ["CLI release"]' in target.read_text(encoding="utf-8")

    target.write_text("A deliberate user edit.", encoding="utf-8")
    repeated = runner.invoke(
        cli.app,
        ["export", str(destination), "--item-id", item["id"], "--yes"],
    )
    assert repeated.exit_code == 0, repeated.output
    assert "conflict" in repeated.output
    assert target.read_text(encoding="utf-8") == "A deliberate user edit."
