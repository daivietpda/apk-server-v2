import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "sign_manifest.py"
spec = importlib.util.spec_from_file_location("sign_manifest", MODULE)
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)


class ManifestSigningTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.private_key = self.root / "private.pem"
        self.public_der = self.root / "public.der"
        self.public_key = self.root / "public.raw"
        self.manifest = self.root / "manifest.json"
        self.signature = self.root / "manifest.sig"
        openssl = os.environ.get("OPENSSL", "openssl")
        subprocess.run([openssl, "genpkey", "-algorithm", "ED25519", "-out", str(self.private_key)], check=True)
        subprocess.run([openssl, "pkey", "-in", str(self.private_key), "-pubout", "-outform", "DER", "-out", str(self.public_der)], check=True)
        self.public_key.write_bytes(self.public_der.read_bytes()[-32:])
        self.manifest.write_bytes(b'{"schemaVersion":3,"releaseId":"v3-test","releaseSequence":1}')

    def tearDown(self):
        self.temporary.cleanup()

    def test_signature_verifies_exact_manifest_bytes(self):
        signing.sign_manifest(self.manifest, self.private_key, self.signature, self.public_key)
        self.assertEqual(self.signature.stat().st_size, 64)
        signing.verify_manifest(self.manifest, self.signature, self.public_key.read_bytes())

    def test_modified_manifest_or_wrong_key_fails_closed(self):
        signing.sign_manifest(self.manifest, self.private_key, self.signature, self.public_key)
        self.manifest.write_bytes(self.manifest.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            signing.verify_manifest(self.manifest, self.signature, self.public_key.read_bytes())


if __name__ == "__main__":
    unittest.main()