import hashlib

from robomcp_platform.hashing import content_hash
from robomcp_platform.security import (
    DISPLAY_PREFIX_LEN,
    KEY_SCHEME,
    display_prefix,
    generate_api_key,
    hash_api_key,
    looks_like_api_key,
)


def test_generated_key_has_scheme_and_enough_entropy():
    key = generate_api_key()
    assert key.plaintext.startswith(KEY_SCHEME)
    assert len(key.plaintext) - len(KEY_SCHEME) >= 43  # 32 random bytes, urlsafe base64
    assert looks_like_api_key(key.plaintext)


def test_stored_fields_do_not_contain_the_secret():
    key = generate_api_key()
    secret_part = key.plaintext[DISPLAY_PREFIX_LEN:]
    assert secret_part not in key.prefix
    assert secret_part not in key.key_hash
    assert key.prefix == key.plaintext[:DISPLAY_PREFIX_LEN]


def test_hash_is_sha256_hex_and_deterministic():
    key = generate_api_key()
    assert key.key_hash == hashlib.sha256(key.plaintext.encode()).hexdigest()
    assert hash_api_key(key.plaintext) == key.key_hash
    assert len(key.key_hash) == 64


def test_different_keys_hash_differently():
    keys = {generate_api_key().key_hash for _ in range(100)}
    assert len(keys) == 100


def test_hash_changes_with_a_single_character():
    key = generate_api_key().plaintext
    tampered = key[:-1] + ("A" if key[-1] != "A" else "B")
    assert hash_api_key(tampered) != hash_api_key(key)


def test_display_prefix_is_short_and_rejects_non_keys():
    assert display_prefix("rmcp_abcdefghXYZ") == "rmcp_abcdefgh"
    assert not looks_like_api_key("Bearer something")
    assert not looks_like_api_key("rmcp_short")


def test_content_hash_ignores_key_order_and_whitespace():
    assert content_hash({"a": 1, "b": [1, 2]}) == content_hash({"b": [1, 2], "a": 1})
    assert content_hash({"a": 1}) != content_hash({"a": 2})
