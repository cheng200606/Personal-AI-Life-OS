"""Native API contract and local desktop data lifecycle on synthetic Windows data."""

import hmac
import json
import sqlite3
import sys
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from time import monotonic, sleep, time

import pytest
from fastapi.testclient import TestClient

from personal_ai_life_os.config import Settings
from personal_ai_life_os.main import create_app

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows desktop credential storage")
SECRET = "1234" * 16
PATH_KEY = b"native picker test key with padding"


def grant(path: Path, purpose: str) -> dict:
    payload = json.dumps({"path": str(path.resolve()), "purpose": purpose, "issued": time()})
    return {"payload": payload, "signature": hmac.digest(PATH_KEY, payload.encode(), "sha256").hex()}


def until(get, match, *, timeout=15):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        value = get()
        if match(value):
            return value
        sleep(0.10)
    raise AssertionError(f"Desktop state did not converge: {value!r}")


@contextmanager
def desktop_workspace(tmp_path):
    pytest.importorskip("ijson")
    pytest.importorskip("win32ctypes")
    root = tmp_path / "app"
    (root / "data").mkdir(parents=True, exist_ok=True)
    config = Settings(
        app_env="desktop", data_dir=root, database_url=f"sqlite+pysqlite:///{(root / 'data' / 'lifeos.db').as_posix()}",
        auto_create_schema=True, registration_mode="closed", processing_mode="worker",
        worker_poll_interval_seconds=0.05, model_providers=None, model_provider="none", cors_origins="http://tauri.localhost",
    )
    app = create_app(config, desktop_secret=SECRET, desktop_path_key=PATH_KEY)
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-LifeOS-Desktop": SECRET}) as client:
        response = client.get("/api/v1/auth/desktop-profile")
        if response.status_code == 404:
            response = client.post("/api/v1/auth/desktop-profile", json={"timezone": "Asia/Shanghai"})
        response.raise_for_status()
        client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
        yield client, app, tmp_path


@pytest.fixture
def workspace(tmp_path):
    with desktop_workspace(tmp_path) as fixture:
        yield fixture


def test_folder_update_pause_and_confirmed_deletion(workspace):
    client, app, tmp = workspace
    vault = tmp / "vault"
    vault.mkdir()
    hidden = vault / ".obsidian"
    hidden.mkdir()
    (hidden / "private.md").write_text("# Hidden data", encoding="utf-8")
    (vault / "export.md").write_text("---\nlifeos_id: example\n---\n# Derived export", encoding="utf-8")
    note = vault / "note.md"
    note.write_text("# First revision\nSource evidence", encoding="utf-8")
    payload = {"kind": "obsidian", "grant": grant(vault, "obsidian")}
    unauthorized = {**payload, "grant": {**payload["grant"], "signature": "0" * 64}}
    assert client.post("/api/v1/desktop/folders", json=unauthorized).status_code == 403
    source = client.post("/api/v1/desktop/folders", json=payload).raise_for_status().json()
    assert client.post("/api/v1/desktop/folders", json=payload).status_code == 409
    export = {
        "grant": grant(vault, "export"), "filename": "explicit.md",
        "markdown": "# Exported content", "policy": "keep",
    }
    export_url = "/api/v1/desktop/data/export"
    written = client.post(export_url, json=export).raise_for_status().json()
    assert written == {"status": "written", "filename": "explicit.md"}
    exported = vault / "LifeOS-Exports" / "explicit.md"
    exported.write_text("Edited by user", encoding="utf-8")
    assert client.post(export_url, json=export).raise_for_status().json()["status"] == "kept"
    assert exported.read_text(encoding="utf-8") == "Edited by user"
    copied = client.post(export_url, json={**export, "policy": "copy"}).raise_for_status().json()
    assert copied["filename"] == "explicit-1.md"
    assert client.post(export_url, json={**export, "policy": "overwrite"}).is_success
    assert exported.read_text(encoding="utf-8") == "# Exported content"

    def titles():
        return [item["title"] for item in client.get("/api/v1/timeline").raise_for_status().json()["items"]]

    assert until(titles, bool) == ["First revision"]
    assert client.patch(f"/api/v1/sources/{source['id']}/status", json={"status": "paused"}).is_success
    note.write_text("# Revised note now\nUpdated evidence", encoding="utf-8")
    assert titles() == ["First revision"]
    assert client.patch(f"/api/v1/sources/{source['id']}/status", json={"status": "active"}).is_success
    until(titles, lambda value: value == ["Revised note now"])
    note.unlink()
    [missing] = until(lambda: client.get("/api/v1/desktop/folders/missing").raise_for_status().json(), bool)
    assert titles() == []
    assert client.delete(f"/api/v1/desktop/folders/missing/{missing['id']}").status_code == 204
    assert app.state.object_store.list_deletion_tombstones()
    assert not list((app.state.settings.data_dir / "objects" / "owners").glob("**/source.bin"))


def test_chat_whitelist_persists_across_file_updates(workspace):
    client, _, tmp = workspace
    directory = tmp / "exports"
    directory.mkdir()
    file = directory / "conversations.json"

    def write(values):
        file.write_text(json.dumps([
            {"id": key, "title": key, "messages": [{"id": "m", "role": "user", "content": value}]}
            for key, value in values
        ]), encoding="utf-8")

    write([("selected", "First version"), ("excluded", "Private text")])
    folder = client.post("/api/v1/desktop/folders", json={
        "kind": "chat_folder", "grant": grant(directory, "chat_folder"),
    }).raise_for_status().json()
    task = client.post("/api/v1/desktop/chats/preview", json=grant(file, "chat")).raise_for_status().json()
    path = f"/api/v1/desktop/chats/{task['id']}"
    ready = until(lambda: client.get(path).raise_for_status().json(), lambda s: s["state"] != "previewing")
    assert ready["state"] == "ready", ready
    assert client.post(path + "/import", json={"conversation_ids": ["missing"]}).status_code == 422
    client.post(path + "/import", json={
        "conversation_ids": ["selected"], "folder_id": folder["id"],
    }).raise_for_status()
    done = until(lambda: client.get(path).raise_for_status().json(), lambda s: s["state"] != "importing")
    assert done["state"] == "complete" and done["items_created"] == 1, done

    def records():
        return [row["content_text"] for row in client.get("/api/v1/timeline").raise_for_status().json()["items"]]

    assert records() == ["First version"]
    write([("new-id", "New excluded content"), ("selected", "Updated version")])
    until(records, lambda values: values == ["Updated version"])


def test_authorized_analysis_budget_and_review(workspace):
    client, app, _ = workspace
    observed = []

    class Model(BaseHTTPRequestHandler):
        def do_POST(self):
            options = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            evidence = options["messages"][1]["content"]
            observed.append(evidence)
            response = json.dumps({
                "choices": [{"message": {"content": json.dumps({"drafts": [
                    {"kind": "experience", "body": "Reviewed the lesson", "quote": "Study evidence line", "confidence": 0.95},
                    {"kind": "knowledge", "body": "Unverifiable", "quote": "Missing evidence", "confidence": 0.99},
                    {"kind": "action", "body": "Read it again", "quote": "Repeat tomorrow", "confidence": 0.82},
                ]})}}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 40},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(response)

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    thread = Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    try:
        config = {
            "base_url": f"http://127.0.0.1:{provider.server_port}/v1", "model": "synthetic",
            "input_cost_per_million_usd": "1", "output_cost_per_million_usd": "1",
            "monthly_budget_usd": "0", "max_cost_per_call_usd": "0.10",
            "privacy_url": "https://example.test/privacy", "retention": "Test data discarded immediately.",
            "api_key": "synthetic-credential",
        }
        provider_settings = "/api/v1/desktop/analysis/provider"
        saved = client.put(provider_settings, json=config).raise_for_status().json()
        assert saved["key_configured"] and "api_key" not in saved
        assert "synthetic-credential" not in app.state.desktop_provider.path.read_text(encoding="utf-8")
        source = client.post("/api/v1/sources", json={
            "kind": "memory_markdown", "name": "Study log", "consent_version": "test-v1",
        }).raise_for_status().json()
        source_path = f"/api/v1/sources/{source['id']}"

        def record(body):
            return client.post(source_path + "/imports", files={
                "file": ("notes.md", body.encode(), "text/markdown"),
            }).raise_for_status().json()

        assert not record("# Without consent\nLocal only")["job_ids"]
        consent = {"provider_id": "desktop", "enabled": True, "disclosure_version": saved["disclosure_version"]}
        client.put("/api/v1/model-providers/consent", json=consent).raise_for_status()
        client.patch(source_path + "/cloud-consent", json={
            "enabled": True, "consent_version": "graph-cloud-v1",
        }).raise_for_status()
        [job] = record("# Study\nStudy evidence line. Repeat tomorrow.")["job_ids"]

        def job_state():
            return client.get("/api/v1/jobs/" + job).raise_for_status().json()

        blocked = until(job_state, lambda value: value["status"] == "failed")
        assert blocked["error_code"] == "model_budget_exceeded" and not observed
        saved = client.put(provider_settings, json={
            **{key: value for key, value in config.items() if key != "api_key"}, "monthly_budget_usd": "5",
        }).raise_for_status().json()
        consent["disclosure_version"] = saved["disclosure_version"]
        client.put("/api/v1/model-providers/consent", json=consent).raise_for_status()
        client.post(f"/api/v1/jobs/{job}/retry").raise_for_status()
        until(job_state, lambda value: value["status"] == "completed")
        assert len(observed) == 1 and "Local only" not in observed[0]
        drafts = client.get("/api/v1/desktop/analysis/drafts").raise_for_status().json()
        assert [draft["kind"] for draft in drafts] == ["experience", "action"]
        client.patch(f"/api/v1/desktop/analysis/drafts/{drafts[0]['id']}", json={
            "body": "Reviewed the lesson and saved notes",
        }).raise_for_status()
        decision = {"ids": [draft["id"] for draft in drafts], "decision": "accepted"}
        assert client.post("/api/v1/desktop/analysis/drafts/decision", json=decision).is_success
        assert client.post("/api/v1/desktop/analysis/drafts/decision", json=decision).status_code == 409
        [note] = client.get("/api/v1/desktop/analysis/confirmed").raise_for_status().json()
        assert note["body"] == "Reviewed the lesson and saved notes"
    finally:
        app.state.desktop_provider.clear()
        provider.shutdown()
        provider.server_close()
        thread.join(timeout=3)


def test_restore_replays_newer_file_deletion(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    file = vault / "delete.md"
    file.write_text("# Removed record\nPRIVATE-FIXTURE", encoding="utf-8")
    target = tmp_path / "external-backups"
    target.mkdir()
    url = "/api/v1/desktop/data"
    with desktop_workspace(tmp_path) as (client, app, _):
        client.post("/api/v1/desktop/folders", json={
            "kind": "obsidian", "grant": grant(vault, "obsidian"),
        }).raise_for_status()
        until(lambda: client.get("/api/v1/timeline").raise_for_status().json()["items"], bool)
        client.put(url + "/backup", json=grant(target, "backup")).raise_for_status()
        created = client.post(url + "/backup").raise_for_status().json()
        snapshot = target / created["filename"]
        file.unlink()
        [pending] = until(
            lambda: client.get("/api/v1/desktop/folders/missing").raise_for_status().json(), bool,
        )
        client.delete(f"/api/v1/desktop/folders/missing/{pending['id']}").raise_for_status()
        client.post(url + "/restore", json=grant(snapshot, "restore")).raise_for_status()
        service = app.state.desktop_backup
    assert service.prepare_startup()
    with desktop_workspace(tmp_path) as (restored, app, _):
        assert not restored.get("/api/v1/timeline").raise_for_status().json()["items"]
        [folder] = restored.get("/api/v1/desktop/folders").raise_for_status().json()
        assert folder["status"] == "paused"
        assert not list((app.state.settings.data_dir / "objects" / "owners").glob("**/source.bin"))
    service.finish_restore()


def test_desktop_migration_preserves_older_data_after_failure_and_retry(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    from personal_ai_life_os.desktop import migrate

    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "lifeos.db"
    settings = Settings(app_env="desktop", data_dir=tmp_path, database_url=f"sqlite+pysqlite:///{database.as_posix()}")
    config = Config()
    config.set_main_option("script_location", str(root / "migrations"))
    config.attributes["settings"] = settings
    command.upgrade(config, "a1b7c9d3e504")
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE probe (name TEXT)")
        connection.execute("INSERT INTO probe VALUES ('pre-upgrade data')")
        connection.commit()

    def interrupted_upgrade(*_):
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("DELETE FROM probe")
            connection.execute("CREATE TABLE incomplete_upgrade (id INTEGER)")
            connection.commit()
        raise RuntimeError("Synthetic upgrade failure")

    with monkeypatch.context() as failure:
        failure.setattr(command, "upgrade", interrupted_upgrade)
        with pytest.raises(RuntimeError, match="Synthetic upgrade"):
            migrate(tmp_path, database, settings, root)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT * FROM probe").fetchall() == [("pre-upgrade data",)]
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE name='incomplete_upgrade'",
        ).fetchall()
    migrate(tmp_path, database, settings, root)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("c8d73b1e0afd",)
        assert connection.execute("SELECT * FROM probe").fetchall() == [("pre-upgrade data",)]
