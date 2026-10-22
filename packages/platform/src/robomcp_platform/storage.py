"""Artifact storage for episode outputs (trace, episode log, later frames and videos).

S3-compatible object storage (MinIO in dev) when ROBOMCP_S3_ENDPOINT_URL is set, else a local directory.
Keys are tenant-prefixed (`<org>/<project>/<experiment>/<episode>/attempt-<n>/<file>`) so a bucket policy or
a presigned-URL service can scope access by org.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol

from robomcp_platform.config import Settings


class ArtifactStore(Protocol):
    def put(self, key: str, path: Path) -> str:
        """Store the file at `path` under `key` and return its URI."""
        ...

    def get(self, uri: str) -> bytes:
        """Contents of an artifact this store wrote."""
        ...


class LocalStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def put(self, key: str, path: Path) -> str:
        dest = self.root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        return dest.as_uri()

    def get(self, uri: str) -> bytes:
        path = Path(uri.removeprefix("file://")).resolve()
        if not path.is_relative_to(self.root):  # URIs come from the DB; never read outside the store
            raise ValueError(f"{uri} is outside the artifact directory")
        return path.read_bytes()


class S3Store:
    def __init__(self, endpoint_url: str, access_key: str | None, secret_key: str | None, bucket: str):
        import boto3  # imported lazily: only workers that upload need it
        from botocore.config import Config

        self.bucket = bucket
        # Path-style addressing: with a custom endpoint, virtual-host style puts the bucket in the hostname
        # and MinIO then sees every request at "/".
        self.client = boto3.client("s3", endpoint_url=endpoint_url, aws_access_key_id=access_key,
                                   aws_secret_access_key=secret_key, region_name="us-east-1",
                                   config=Config(s3={"addressing_style": "path"}))
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except self.client.exceptions.ClientError:
            self.client.create_bucket(Bucket=self.bucket)
        self._bucket_ready = True

    def put(self, key: str, path: Path) -> str:
        self._ensure_bucket()
        self.client.upload_file(str(path), self.bucket, key)
        return f"s3://{self.bucket}/{key}"

    def get(self, uri: str) -> bytes:
        bucket, _, key = uri.removeprefix("s3://").partition("/")
        if bucket != self.bucket:
            raise ValueError(f"{uri} is not in bucket {self.bucket}")
        return self.client.get_object(Bucket=bucket, Key=key)["Body"].read()


def make_store(settings: Settings) -> ArtifactStore:
    if settings.s3_endpoint_url:
        return S3Store(settings.s3_endpoint_url, settings.s3_access_key, settings.s3_secret_key, settings.s3_bucket)
    return LocalStore(Path(settings.artifact_dir))
