from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from ugai_workflow.payload_cipher import TaskPayloadCipher


def test_active_key_encrypts_and_decrypts_payload():
    key = Fernet.generate_key().decode("ascii")
    cipher = TaskPayloadCipher(key, key_id="key-v2")
    encrypted, digest = cipher.encrypt({"intent": "hello", "nested": {"value": 1}})
    assert cipher.decrypt(encrypted, expected_sha256=digest, key_id="key-v2") == {
        "intent": "hello",
        "nested": {"value": 1},
    }


def test_previous_key_decrypts_old_payload_after_active_key_rotation():
    old_key = Fernet.generate_key().decode("ascii")
    new_key = Fernet.generate_key().decode("ascii")
    old_cipher = TaskPayloadCipher(old_key, key_id="key-v1")
    encrypted, digest = old_cipher.encrypt({"intent": "legacy task"})

    rotated = TaskPayloadCipher(
        new_key,
        key_id="key-v2",
        previous_keys={"key-v1": old_key},
    )
    assert rotated.decrypt(encrypted, expected_sha256=digest, key_id="key-v1") == {
        "intent": "legacy task"
    }

    new_ciphertext, new_digest = rotated.encrypt({"intent": "new task"})
    assert rotated.decrypt(
        new_ciphertext, expected_sha256=new_digest, key_id="key-v2"
    ) == {"intent": "new task"}


def test_unknown_previous_key_fails_closed():
    cipher = TaskPayloadCipher(Fernet.generate_key().decode("ascii"), key_id="key-v2")
    with pytest.raises(ValueError, match="decryption_key_unavailable"):
        cipher.decrypt(b"invalid", expected_sha256="a" * 64, key_id="removed-key")


def test_duplicate_active_and_previous_key_ids_are_rejected():
    key = Fernet.generate_key().decode("ascii")
    with pytest.raises(ValueError, match="key_id_duplicate"):
        TaskPayloadCipher(key, key_id="v1", previous_keys={"v1": key})


def test_tampered_payload_fails_integrity_check():
    cipher = TaskPayloadCipher(Fernet.generate_key().decode("ascii"), key_id="v1")
    encrypted, digest = cipher.encrypt({"intent": "safe"})
    with pytest.raises(ValueError, match="decryption_failed"):
        cipher.decrypt(encrypted[:-2] + b"xx", expected_sha256=digest, key_id="v1")
