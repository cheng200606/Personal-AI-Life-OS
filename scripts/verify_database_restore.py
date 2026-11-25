"""Exercise PostgreSQL dump/restore and deletion replay in the local lifeos-iteration stack."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx

COMPOSE = ["docker", "compose", "-p", "lifeos-iteration", "-f", "docker-compose.yml"]
DATABASE = "postgresql+psycopg://lifeos:lifeos_dev@db:5432/"


def exec_service(service: str, *args: str, payload: bytes | None = None) -> bytes:
    return subprocess.run(
        [*COMPOSE, "exec", "-T", service, *args],
        input=payload,
        stdout=subprocess.PIPE,
        check=True,
        timeout=120,
    ).stdout


def create_item(api: httpx.Client, name: str) -> tuple[str, str]:
    source = api.post("sources", json={"kind": "memory_markdown", "name": name}).raise_for_status()
    source_id = source.json()["id"]
    fixture = Path("fixtures/synthetic/memory.md").read_bytes()
    imported = api.post(
        f"sources/{source_id}/imports", files={"file": ("memory.md", fixture, "text/markdown")}
    ).raise_for_status()
    return source_id, imported.json()["items"][0]["id"]


def main() -> None:
    database_name = "lifeos_restore_" + uuid4().hex
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=20) as api:
        registration = api.post(
            "auth/register",
            json={"email": f"{uuid4().hex}@example.test", "password": uuid4().hex},
        ).raise_for_status()
        token = registration.json()["access_token"]
        api.headers["Authorization"] = "Bearer " + token
        try:
            deleted_source, deleted_item = create_item(api, "Synthetic post-snapshot deletion")
            _, control_item = create_item(api, "Synthetic retained control")
            snapshot = exec_service("db", "pg_dump", "-Fc", "-U", "lifeos", "lifeos")
            api.delete(f"sources/{deleted_source}").raise_for_status()
            assert api.get(f"items/{deleted_item}/raw").status_code == 404

            start = time.monotonic()
            exec_service("db", "createdb", "-U", "lifeos", database_name)
            try:
                exec_service(
                    "db", "pg_restore", "--exit-on-error", "--no-owner", "-U", "lifeos",
                    "-d", database_name, payload=snapshot,
                )
                verification = b"""
import json
import sys
from personal_ai_life_os.config import Settings
from personal_ai_life_os.main import create_app
from personal_ai_life_os.models import SourceItem
from personal_ai_life_os.services.deletion import replay_deletion_tombstones

data = json.load(sys.stdin)
config = Settings(database_url=data["database_url"], auto_create_schema=False)
app = create_app(config)
state = app.state
with state.session_factory() as session:
    assert session.get(SourceItem, data["deleted_item"]).deleted_at is None
replay_deletion_tombstones(state.session_factory, state.object_store)
with state.session_factory() as session:
    removed = session.get(SourceItem, data["deleted_item"])
    assert removed is None or removed.deleted_at is not None
    retained = session.get(SourceItem, data["control_item"])
    assert retained is not None and retained.deleted_at is None
    assert state.object_store.get(retained.object_key)
print("Post-snapshot deletion was replayed and the retained object remained readable.")
"""
                inputs = json.dumps({
                    "database_url": DATABASE + database_name,
                    "deleted_item": deleted_item,
                    "control_item": control_item,
                }).encode()
                result = exec_service(
                    "api", "python", "-c", verification.decode(), payload=inputs,
                )
                print(result.decode().strip())
                print(f"Local database restore and deletion replay took {time.monotonic() - start:.2f}s.")
            finally:
                exec_service("db", "dropdb", "-U", "lifeos", database_name)
        finally:
            api.delete("account").raise_for_status()


if __name__ == "__main__":
    main()
