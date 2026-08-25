from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from secret_store import KeyStore, WindowsDPAPI  # noqa: E402
from sqlcipher_codec import DEFAULT_PROFILE  # noqa: E402


class FakeProtector:
    def protect(self, cleartext: bytes, entropy: bytes) -> bytes:
        return bytes(value ^ entropy[index % len(entropy)] for index, value in enumerate(cleartext))

    def unprotect(self, ciphertext: bytes, entropy: bytes) -> bytes:
        return self.protect(ciphertext, entropy)


class SecretStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "account"
        self.root.mkdir()
        self.path = Path(self.temporary.name) / "keys.json"
        self.key = bytes(range(32))
        self.salt = bytes(range(16))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_key_is_not_stored_as_plain_hex(self) -> None:
        store = KeyStore(self.path, self.root, FakeProtector())
        store.put("message/message_0.db", self.key, self.salt, DEFAULT_PROFILE, "test")
        serialized = self.path.read_text(encoding="utf-8")
        self.assertNotIn(self.key.hex(), serialized)
        restored, profile = store.get("message/message_0.db")
        self.assertEqual(restored, self.key)
        self.assertEqual(profile, DEFAULT_PROFILE)
        metadata = store.metadata()["message/message_0.db"]
        self.assertNotIn("protected_key", metadata)

    def test_store_is_bound_to_account_root(self) -> None:
        store = KeyStore(self.path, self.root, FakeProtector())
        store.put("contact/contact.db", self.key, self.salt, DEFAULT_PROFILE, "test")
        other = Path(self.temporary.name) / "other-account"
        other.mkdir()
        with self.assertRaises(ValueError):
            KeyStore(self.path, other, FakeProtector()).metadata()

    @unittest.skipUnless(os.name == "nt", "DPAPI test requires Windows")
    def test_real_dpapi_round_trip(self) -> None:
        protector = WindowsDPAPI()
        entropy = bytes(range(32))
        protected = protector.protect(self.key, entropy)
        self.assertNotEqual(protected, self.key)
        self.assertEqual(protector.unprotect(protected, entropy), self.key)


if __name__ == "__main__":
    unittest.main()
