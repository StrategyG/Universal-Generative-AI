from __future__ import annotations

import hashlib

import pytest
from cryptography.fernet import Fernet

from ugai_workflow.payload_cipher import TaskPayloadCipher


def valid_key() -> str:
    return Fernet.generate_key().decode("ascii")


@pytest.mark.parametrize("key_id", ["", " ", "x" * 65, "bad\nkey", "bad\u007fkey"])
def test_cipher_rejects_invalid_key_identifiers(key_id):
    with pytest.raises(ValueError, match="key_id_invalid"):
        TaskPayloadCipher(valid_key(), key_id=key_id)


def test_cipher_rejects_missing_and_malformed_active_keys():
    with pytest.raises(ValueError, match="active_key_required"):
        TaskPayloadCipher("")
    with pytest.raises(ValueError, match="active_key_invalid"):
        TaskPayloadCipher("not-a-fernet-key")
    with pytest.raises(ValueError, match="active_key_invalid"):
        TaskPayloadCipher("non-ascii-🔐")


def test_cipher_rejects_invalid_previous_keyring_shapes_and_values():
    with pytest.raises(ValueError, match="previous_keys_must_be_object"):
        TaskPayloadCipher(valid_key(), previous_keys=[])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="key_id_invalid"):
        TaskPayloadCipher(valid_key(), previous_keys={"": valid_key()})
    with pytest.raises(ValueError, match="previous_key_invalid"):
        TaskPayloadCipher(valid_key(), previous_keys={"old": 123})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="previous_key_invalid"):
        TaskPayloadCipher(valid_key(), previous_keys={"old": ""})
    with pytest.raises(ValueError, match="previous_key_invalid"):
        TaskPayloadCipher(valid_key(), previous_keys={"old": "not-a-fernet-key"})


def test_canonical_payload_requires_finite_bounded_json_object():
    with pytest.raises(TypeError, match="must_be_object"):
        TaskPayloadCipher.canonical_bytes(["not", "an", "object"])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite_json"):
        TaskPayloadCipher.canonical_bytes({"not_json": object()})
    with pytest.raises(ValueError, match="finite_json"):
        TaskPayloadCipher.canonical_bytes({"not_finite": float("nan")})
    with pytest.raises(ValueError, match="size_invalid"):
        TaskPayloadCipher.canonical_bytes({"payload": "x" * (128 * 1024)})


@pytest.mark.parametrize(
    ("ciphertext", "digest", "key_id", "message"),
    [
        (None, "a" * 64, None, "encrypted_task_payload_size_invalid"),
        (b"", "a" * 64, None, "encrypted_task_payload_size_invalid"),
        (b"x" * (256 * 1024 + 1), "a" * 64, None, "encrypted_task_payload_size_invalid"),
        (b"ciphertext", "A" * 64, None, "task_payload_digest_invalid"),
        (b"ciphertext", "short", None, "task_payload_digest_invalid"),
        (b"ciphertext", None, None, "task_payload_digest_invalid"),
    ],
)
def test_decrypt_rejects_invalid_ciphertext_and_digest_inputs(ciphertext, digest, key_id, message):
    cipher = TaskPayloadCipher(valid_key(), key_id="active")
    with pytest.raises(ValueError, match=message):
        cipher.decrypt(ciphertext, expected_sha256=digest, key_id=key_id)  # type: ignore[arg-type]


def test_decrypt_rejects_valid_ciphertext_with_wrong_digest():
    cipher = TaskPayloadCipher(valid_key(), key_id="active")
    encrypted, _digest = cipher.encrypt({"intent": "private"})
    with pytest.raises(ValueError, match="integrity_check_failed"):
        cipher.decrypt(encrypted, expected_sha256="b" * 64)


def test_decrypt_rejects_authenticated_non_object_plaintext():
    key = valid_key()
    cipher = TaskPayloadCipher(key, key_id="active")
    plaintext = b"[]"
    encrypted = Fernet(key.encode("ascii")).encrypt(plaintext)
    digest = hashlib.sha256(plaintext).hexdigest()
    with pytest.raises(ValueError, match="decode_to_object"):
        cipher.decrypt(encrypted, expected_sha256=digest)
