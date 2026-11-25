"""Rehearse database and primary S3 loss with a local S3 emulator and synthetic data."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from uuid import uuid4

import boto3
from fastapi.testclient import TestClient
from verify_database_restore import create_item, exec_service

from personal_ai_life_os.config import Settings
from personal_ai_life_os.main import create_app
from personal_ai_life_os.models import SourceItem

ENDPOINT = os.environ.get("LIFEOS_REHEARSAL_S3_ENDPOINT", "http://127.0.0.1:15666")
DATABASE = "postgresql+psycopg://lifeos:lifeos_dev@127.0.0.1:5432/"


def register(api: TestClient, label: str) -> dict[str, str]:
    account = api.post("auth/register", json={
        "email": f"{label}-{uuid4().hex}@example.test", "password": uuid4().hex,
    }).raise_for_status().json()
    return {"Authorization": "Bearer " + account["access_token"]}


def version_entries(s3, bucket: str, prefix: str = "") -> list[dict]:
    return [
        {"Key": item["Key"], "VersionId": item["VersionId"]}
        for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket, Prefix=prefix)
        for entry in ("Versions", "DeleteMarkers")
        for item in page.get(entry, [])
    ]


def remove_bucket(s3, bucket: str) -> None:
    versions = version_entries(s3, bucket)
    if versions:
        response = s3.delete_objects(Bucket=bucket, Delete={"Objects": versions})
        assert not response.get("Errors"), response.get("Errors")
    s3.delete_bucket(Bucket=bucket)


def start_rehearsal(database: str, restored_database: str, s3, primary: str, recovery: str, journal: str) -> None:
    config = Settings(
        _env_file=None, app_env="test", database_url=DATABASE + database, auto_create_schema=False,
        object_store_backend="s3", s3_bucket=primary, s3_region="us-east-1",
        s3_endpoint_url=ENDPOINT, s3_deletion_journal_bucket=journal,
        registration_mode="open", model_provider="none", processing_mode="inline",
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env={**os.environ, "DATABASE_URL": config.database_url}, check=True, timeout=60,
    )
    app = create_app(config)
    store = app.state.object_store
    with TestClient(app, base_url="http://testserver/api/v1/") as api:
        owner = register(api, "owner")
        other = register(api, "other")
        api.headers.update(owner)
        removed_source, removed_item = create_item(api, "Synthetic removed source")
        _, kept_item = create_item(api, "Synthetic retained control")
        api.headers.update(other)
        _, other_item = create_item(api, "Synthetic removed account")
        removed_path = f"items/{removed_item}/raw"
        kept_path = f"items/{kept_item}/raw"
        other_path = f"items/{other_item}/raw"
        api.headers.pop("Authorization")
        assert api.get(removed_path).status_code == 401
        assert api.get(removed_path, headers=other).status_code == 404
        assert api.delete(f"sources/{removed_source}", headers=other).status_code == 404

        with app.state.session_factory() as session:
            keys = {item_id: session.get(SourceItem, item_id).object_key for item_id in (
                removed_item, kept_item, other_item,
            )}
        original_bytes = {key: store.get(key) for key in keys.values()}
        removed_key = keys[removed_item]
        s3.delete_object(Bucket=primary, Key=removed_key)
        store.put(removed_key, original_bytes[removed_key], "text/markdown")
        assert len(version_entries(s3, primary, removed_key)) == 3
        assert api.get(removed_path, headers=owner).status_code == 200

        assert api.patch(
            f"sources/{removed_source}/status", headers=owner, json={"status": "paused"},
        ).status_code == 200
        upload = {"file": ("memory.md", b"# Pause check", "text/markdown")}
        import_path = f"sources/{removed_source}/imports"
        assert api.post(import_path, headers=owner, files=upload).status_code == 409
        assert api.post(f"sources/{removed_source}/revoke", headers=owner).status_code == 200
        assert api.post(import_path, headers=owner, files=upload).status_code == 409

        snapshot = exec_service("db", "pg_dump", "-Fc", "-U", "lifeos", database)
        store.journal_bucket = journal + "-unavailable"
        assert api.delete(f"sources/{removed_source}", headers=owner).status_code == 503
        assert api.delete("account", headers=other).status_code == 503
        assert api.get(removed_path, headers=owner).status_code == 200
        assert api.get(other_path, headers=other).status_code == 200
        store.journal_bucket = journal
        after_snapshot = time.monotonic()
        assert api.delete(f"sources/{removed_source}", headers=owner).status_code == 204
        assert api.delete("account", headers=other).status_code == 204
        assert api.get(removed_path, headers=owner).status_code == 404
        assert not version_entries(s3, primary, removed_key)
        assert not version_entries(s3, primary, keys[other_item])
        assert len(store.list_deletion_tombstones()) == 2
        print(f"Post-snapshot source/account deletion and version cleanup completed in {time.monotonic()-after_snapshot:.2f}s.")

    remove_bucket(s3, primary)
    exec_service("db", "dropdb", "-U", "lifeos", database)
    recovery_started = time.monotonic()
    exec_service(
        "db", "pg_restore", "--exit-on-error", "--no-owner", "-U", "lifeos", "-d",
        restored_database, payload=snapshot,
    )
    config.database_url = DATABASE + restored_database
    config.s3_bucket = recovery
    restored_app = create_app(config)
    restored_store = restored_app.state.object_store
    for key, body in original_bytes.items():
        restored_store.put(key, body, "text/markdown")
    with restored_app.state.session_factory() as session:
        for item_id, key in keys.items():
            assert session.get(SourceItem, item_id) is not None
            assert restored_store.get(key) == original_bytes[key]

    with TestClient(restored_app, base_url="http://testserver/api/v1/") as api:
        assert api.get("ready").status_code == 200
        assert api.get(removed_path, headers=owner).status_code == 404
        assert api.get(other_path, headers=other).status_code == 401
        assert api.get(kept_path, headers=owner).content == original_bytes[keys[kept_item]]
        assert not version_entries(s3, recovery, removed_key)
        assert not version_entries(s3, recovery, keys[other_item])
    print(f"Restored database and replacement bucket replayed both deletions in {time.monotonic()-recovery_started:.2f}s.")


def main() -> None:
    # Keep credentials supplied through the environment so the rehearsal can target either
    # the Moto emulator or a real S3-compatible server.
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "synthetic")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "synthetic")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    if not os.environ.get("AWS_SESSION_TOKEN"):
        os.environ.pop("AWS_SESSION_TOKEN", None)
    run = uuid4().hex
    database, restored_database = f"lifeos_joint_{run}", f"lifeos_replay_{run}"
    primary, recovery, journal = (f"lifeos-{role}-{run}" for role in ("primary", "recovery", "journal"))
    s3 = boto3.client("s3", region_name="us-east-1", endpoint_url=ENDPOINT)
    buckets = []
    databases = []
    try:
        for bucket in (primary, recovery, journal):
            s3.create_bucket(Bucket=bucket)
            buckets.append(bucket)
            s3.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
        for name in (database, restored_database):
            exec_service("db", "createdb", "-U", "lifeos", name)
            databases.append(name)
        start_rehearsal(database, restored_database, s3, primary, recovery, journal)
    finally:
        for name in databases:
            exec_service("db", "dropdb", "--if-exists", "-U", "lifeos", name)
        available = {bucket["Name"] for bucket in s3.list_buckets().get("Buckets", [])}
        for bucket in buckets:
            if bucket in available:
                remove_bucket(s3, bucket)


if __name__ == "__main__":
    main()
