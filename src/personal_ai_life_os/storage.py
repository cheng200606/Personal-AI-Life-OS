"""Private object storage adapters. Object keys are never returned to clients."""

import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Protocol
from uuid import UUID

import boto3

from personal_ai_life_os.config import Settings


class ObjectStore(Protocol):
    def put(self, key: str, content: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def write_deletion_tombstone(self, owner_id: str, payload: bytes) -> None: ...

    def write_source_deletion_tombstone(self, owner_id: str, source_id: str, payload: bytes) -> None: ...

    def list_deletion_tombstones(self) -> list[tuple[str, bytes]]: ...

    def delete_owner_objects(self, owner_id: str) -> None: ...

    def delete_source_objects(self, owner_id: str, source_id: str) -> None: ...


def _validate_key(key: str) -> PurePosixPath:
    path = PurePosixPath(key)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Invalid object key.")
    if "\\" in key or "\x00" in key:
        raise ValueError("Invalid object key.")
    return path


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        relative = _validate_key(key)
        result = (self.root / Path(*relative.parts)).resolve()
        if not result.is_relative_to(self.root):
            raise ValueError("Object key escapes the configured storage directory.")
        return result

    def put(self, key: str, content: bytes, content_type: str) -> None:
        del content_type
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, target)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)
        parent = path.parent
        while parent != self.root and self.root in parent.parents:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def write_deletion_tombstone(self, owner_id: str, payload: bytes) -> None:
        UUID(owner_id)
        self.put(f".deletion-tombstones/accounts/{owner_id}.json", payload, "application/json")

    def write_source_deletion_tombstone(self, owner_id: str, source_id: str, payload: bytes) -> None:
        UUID(owner_id)
        UUID(source_id)
        self.put(f".deletion-tombstones/sources/{source_id}.json", payload, "application/json")

    def list_deletion_tombstones(self) -> list[tuple[str, bytes]]:
        directory = self.root / ".deletion-tombstones"
        if not directory.exists():
            return []
        return [
            (path.relative_to(self.root).as_posix(), path.read_bytes())
            for path in sorted(directory.rglob("*.json"))
            if path.is_file() and not path.is_symlink()
        ]

    def delete_owner_objects(self, owner_id: str) -> None:
        safe_id = str(UUID(owner_id))
        candidate = self.root / "owners" / safe_id
        if candidate.is_symlink():
            raise ValueError("Invalid owner object prefix.")
        target = candidate.resolve()
        if not target.is_relative_to(self.root) or target == self.root:
            raise ValueError("Invalid owner object prefix.")
        if target.is_symlink():
            raise ValueError("Invalid owner object prefix.")
        if target.exists():
            shutil.rmtree(target)

    def delete_source_objects(self, owner_id: str, source_id: str) -> None:
        safe_owner = str(UUID(owner_id))
        safe_source = str(UUID(source_id))
        candidate = self.root / "owners" / safe_owner / "sources" / safe_source
        if candidate.is_symlink():
            raise ValueError("Invalid source object prefix.")
        target = candidate.resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("Invalid source object prefix.")
        if target.exists():
            shutil.rmtree(target)


class S3ObjectStore:
    """S3-compatible private bucket adapter using server-side credentials."""

    def __init__(self, config: Settings) -> None:
        if not config.s3_bucket:
            raise ValueError("S3_BUCKET is required for S3 object storage.")
        self.bucket = config.s3_bucket
        self.client = boto3.client(
            "s3",
            region_name=config.s3_region,
            endpoint_url=config.s3_endpoint_url or None,
        )
        self.journal_bucket = config.s3_deletion_journal_bucket or self.bucket
        self.journal_client = self.client
        if config.s3_deletion_journal_region or config.s3_deletion_journal_endpoint_url:
            self.journal_client = boto3.client(
                "s3",
                region_name=config.s3_deletion_journal_region or config.s3_region,
                endpoint_url=config.s3_deletion_journal_endpoint_url or config.s3_endpoint_url or None,
            )

    def put(self, key: str, content: bytes, content_type: str) -> None:
        _validate_key(key)
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )

    def get(self, key: str) -> bytes:
        _validate_key(key)
        return self._read_object(self.client, self.bucket, key)

    @staticmethod
    def _read_object(client, bucket: str, key: str) -> bytes:
        response = client.get_object(Bucket=bucket, Key=key)
        try:
            return response["Body"].read()
        finally:
            response["Body"].close()

    def delete(self, key: str) -> None:
        _validate_key(key)
        if not self._delete_versions(key, exact=True):
            self._delete_unversioned(key)

    def _delete_unversioned(self, key: str) -> None:
        result = self.client.delete_object(Bucket=self.bucket, Key=key)
        if result.get("DeleteMarker"):
            self.client.delete_object(Bucket=self.bucket, Key=key, VersionId=result["VersionId"])

    def write_deletion_tombstone(self, owner_id: str, payload: bytes) -> None:
        UUID(owner_id)
        self._write_journal(f".deletion-tombstones/accounts/{owner_id}.json", payload)

    def write_source_deletion_tombstone(self, owner_id: str, source_id: str, payload: bytes) -> None:
        UUID(owner_id)
        UUID(source_id)
        self._write_journal(f".deletion-tombstones/sources/{source_id}.json", payload)

    def _write_journal(self, key: str, payload: bytes) -> None:
        self.journal_client.put_object(
            Bucket=self.journal_bucket, Key=key, Body=payload,
            ContentType="application/json", ServerSideEncryption="AES256",
        )

    def list_deletion_tombstones(self) -> list[tuple[str, bytes]]:
        journal = dict(self._list_tombstones(self.journal_client, self.journal_bucket))
        if self.journal_bucket != self.bucket or self.journal_client is not self.client:
            # Backfill records written before the independent journal was configured.
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=".deletion-tombstones/"):
                for item in page.get("Contents", []):
                    key = item["Key"]
                    if key not in journal:
                        payload = self.get(key)
                        self._write_journal(key, payload)
                        journal[key] = payload
        return list(journal.items())

    def _list_tombstones(self, client, bucket: str) -> list[tuple[str, bytes]]:
        paginator = client.get_paginator("list_objects_v2")
        result: list[tuple[str, bytes]] = []
        for page in paginator.paginate(Bucket=bucket, Prefix=".deletion-tombstones/"):
            for item in page.get("Contents", []):
                key = item["Key"]
                result.append((key, self._read_object(client, bucket, key)))
        return result

    def delete_owner_objects(self, owner_id: str) -> None:
        safe_id = str(UUID(owner_id))
        self._delete_prefix(f"owners/{safe_id}/")

    def delete_source_objects(self, owner_id: str, source_id: str) -> None:
        safe_owner = str(UUID(owner_id))
        safe_source = str(UUID(source_id))
        self._delete_prefix(f"owners/{safe_owner}/sources/{safe_source}/")

    def _delete_prefix(self, prefix: str) -> None:
        self._delete_versions(prefix)
        # Some compatible stores omit unversioned keys from list_object_versions.
        while objects := self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix).get("Contents"):
            for item in objects:
                self._delete_unversioned(item["Key"])

    def _delete_versions(self, prefix: str, *, exact: bool = False) -> bool:
        removed = False
        while True:
            # Refresh the first page after deletion. Continuation markers may have been deleted.
            page = self.client.list_object_versions(Bucket=self.bucket, Prefix=prefix)
            objects = [
                {"Key": item["Key"], "VersionId": item["VersionId"]}
                for item in page.get("Versions", []) + page.get("DeleteMarkers", [])
                if not exact or item["Key"] == prefix
            ]
            if not objects:
                return removed
            response = self.client.delete_objects(
                Bucket=self.bucket, Delete={"Objects": objects, "Quiet": True},
            )
            if response.get("Errors"):
                raise RuntimeError("Object storage could not fully remove selected files.")
            removed = True


def create_object_store(config: Settings) -> ObjectStore:
    if config.object_store_backend == "s3":
        return S3ObjectStore(config)
    return LocalObjectStore(config.data_dir / "objects")
