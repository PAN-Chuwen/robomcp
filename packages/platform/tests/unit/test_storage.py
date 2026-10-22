from pathlib import Path

from robomcp_platform.config import Settings
from robomcp_platform.storage import LocalStore, S3Store, make_store


def test_local_store_copies_under_key(tmp_path):
    src = tmp_path / "trace.jsonl"
    src.write_text('{"kind": "start"}\n')
    uri = LocalStore(tmp_path / "artifacts").put("org/exp/ep/attempt-1/trace.jsonl", src)
    assert uri.startswith("file://")
    assert Path(uri.removeprefix("file://")).read_text() == src.read_text()


def test_store_choice_follows_settings(tmp_path):
    assert isinstance(make_store(Settings(s3_endpoint_url=None, artifact_dir=str(tmp_path))), LocalStore)
    assert isinstance(make_store(Settings(s3_endpoint_url="http://localhost:9010")), S3Store)
