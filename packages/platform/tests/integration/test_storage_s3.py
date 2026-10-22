"""S3Store against the dev MinIO, in a throwaway bucket that is deleted afterwards."""

from __future__ import annotations

import uuid

import pytest

from robomcp_platform.config import Settings
from robomcp_platform.storage import S3Store


@pytest.fixture
def s3_store():
    settings = Settings()
    if not settings.s3_endpoint_url:
        pytest.exit("S3 integration test needs ROBOMCP_S3_ENDPOINT_URL (run `make services`)", returncode=3)
    store = S3Store(settings.s3_endpoint_url, settings.s3_access_key, settings.s3_secret_key,
                    f"robomcp-test-{uuid.uuid4().hex[:12]}")
    yield store
    for obj in store.client.list_objects_v2(Bucket=store.bucket).get("Contents", []):
        store.client.delete_object(Bucket=store.bucket, Key=obj["Key"])
    store.client.delete_bucket(Bucket=store.bucket)


def test_put_creates_bucket_and_uploads(s3_store, tmp_path):
    src = tmp_path / "episode.env.jsonl"
    src.write_text('{"kind": "episode"}\n')
    uri = s3_store.put("org/project/exp/ep/attempt-1/episode.env.jsonl", src)
    assert uri == f"s3://{s3_store.bucket}/org/project/exp/ep/attempt-1/episode.env.jsonl"
    body = s3_store.client.get_object(Bucket=s3_store.bucket, Key="org/project/exp/ep/attempt-1/episode.env.jsonl")
    assert body["Body"].read().decode() == src.read_text()
