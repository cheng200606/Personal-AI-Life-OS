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
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        try:
            return response["Body"].read()
        finally:
            response["Body"].close()

    def delete(self, key: str) -> None:
        _validate_key(key)
        paginator = self.client.get_paginator("list_object_versions")
        versions = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=key):
            versions.extend(
                {"Key": item["Key"], "VersionId": item["VersionId"]}
                for item in page.get("Versions", []) + page.get("DeleteMarkers", [])
                if item["Key"] == key
            )
        for offset in range(0, len(versions), 1000):
            result = self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": versions[offset : offset + 1000], "Quiet": True},
            )
            if result.get("Errors"):
                raise RuntimeError("Object storage could not fully remove a selected source file.")
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def write_deletion_tombstone(self, owner_id: str, payload: bytes) -> None:
        UUID(owner_id)
        self.put(f".deletion-tombstones/accounts/{owner_id}.json", payload, "application/json")

    def write_source_deletion_tombstone(self, owner_id: str, source_id: str, payload: bytes) -> None:
        UUID(owner_id)
        UUID(source_id)
        self.put(f".deletion-tombstones/sources/{source_id}.json", payload, "application/json")

    def list_deletion_tombstones(self) -> list[tuple[str, bytes]]:
        paginator = self.client.get_paginator("list_objects_v2")
        result: list[tuple[str, bytes]] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=".deletion-tombstones/"):
            for item in page.get("Contents", []):
                key = item["Key"]
                result.append((key, self.get(key)))
        return result

    def delete_owner_objects(self, owner_id: str) -> None:
        safe_id = str(UUID(owner_id))
        self._delete_prefix(f"owners/{safe_id}/")

    def delete_source_objects(self, owner_id: str, source_id: str) -> None:
        safe_owner = str(UUID(owner_id))
        safe_source = str(UUID(source_id))
        self._delete_prefix(f"owners/{safe_owner}/sources/{safe_source}/")

    def _delete_prefix(self, prefix: str) -> None:
        paginator = self.client.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            objects = [
                {"Key": item["Key"], "VersionId": item["VersionId"]}
                for item in page.get("Versions", []) + page.get("DeleteMarkers", [])
            ]
            for offset in range(0, len(objects), 1000):
                response = self.client.delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": objects[offset : offset + 1000], "Quiet": True},
                )
                if response.get("Errors"):
                    raise RuntimeError("Object storage could not fully remove this account's files.")
        # Buckets without versioning do not return content from list_object_versions.
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            for offset in range(0, len(objects), 1000):
                response = self.client.delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": objects[offset : offset + 1000], "Quiet": True},
                )
                if response.get("Errors"):
                    raise RuntimeError("Object storage could not fully remove this account's files.")


def create_object_store(config: Settings) -> ObjectStore:
    if config.object_store_backend == "s3":
        return S3ObjectStore(config)
    return LocalObjectStore(config.data_dir / "objects")
