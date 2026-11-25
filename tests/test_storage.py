import json
from io import BytesIO
from uuid import uuid4

import boto3
from botocore.response import StreamingBody
from botocore.stub import Stubber

from personal_ai_life_os.config import Settings
from personal_ai_life_os.storage import S3ObjectStore


def test_s3_deletion_removes_versions_and_markers_without_creating_another(monkeypatch) -> None:
    client = boto3.client("s3", region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test")
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)
    store = S3ObjectStore(Settings(_env_file=None, s3_bucket="lifeos-primary"))
    lookup = {"Bucket": "lifeos-primary", "Prefix": "original"}
    with Stubber(client) as stub:
        stub.add_response("list_object_versions", {
            "Versions": [{"Key": "original", "VersionId": "old"}],
            "DeleteMarkers": [{"Key": "original", "VersionId": "marker"}],
        }, lookup)
        stub.add_response("delete_objects", {}, {
            "Bucket": "lifeos-primary",
            "Delete": {"Objects": [
                {"Key": "original", "VersionId": "old"},
                {"Key": "original", "VersionId": "marker"},
            ], "Quiet": True},
        })
        stub.add_response("list_object_versions", {
            "Versions": [{"Key": "original-copy", "VersionId": "unrelated"}],
        }, lookup)
        store.delete("original")
        stub.assert_no_pending_responses()


def test_s3_journal_backfills_legacy_tombstones(monkeypatch) -> None:
    client = boto3.client("s3", region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test")
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)
    store = S3ObjectStore(Settings(
        _env_file=None, s3_bucket="lifeos-primary", s3_deletion_journal_bucket="lifeos-journal",
    ))
    owner_id = str(uuid4())
    key = f".deletion-tombstones/accounts/{owner_id}.json"
    payload = json.dumps({"owner_id": owner_id}).encode()
    with Stubber(client) as stub:
        stub.add_response("list_objects_v2", {}, {"Bucket": "lifeos-journal", "Prefix": ".deletion-tombstones/"})
        stub.add_response("list_objects_v2", {"Contents": [{"Key": key}]}, {
            "Bucket": "lifeos-primary", "Prefix": ".deletion-tombstones/",
        })
        stub.add_response("get_object", {"Body": StreamingBody(BytesIO(payload), len(payload))}, {
            "Bucket": "lifeos-primary", "Key": key,
        })
        stub.add_response("put_object", {}, {
            "Bucket": "lifeos-journal", "Key": key, "Body": payload,
            "ContentType": "application/json", "ServerSideEncryption": "AES256",
        })
        assert store.list_deletion_tombstones() == [(key, payload)]
        stub.assert_no_pending_responses()
