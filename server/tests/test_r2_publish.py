import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "publish_r2.py"
spec = importlib.util.spec_from_file_location("publish_r2", MODULE)
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


class R2PublisherTest(unittest.TestCase):
    def make_layout(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        payload_dir = root / "payload"
        payload_dir.mkdir()
        payload = payload_dir / "com.example.tv-42-aaaaaaaaaaaa.apk"
        payload.write_bytes(b"apk-data")
        helper = root / "remote-preinstall.jar"
        helper.write_bytes(b"dex-helper")
        manifest = {
            "schemaVersion": 3,
            "releaseId": "v3-test",
            "packages": [{
                "packageName": "com.example.tv",
                "versionCode": 42,
                "payload": {
                    "path": "payload/com.example.tv-42-aaaaaaaaaaaa.apk",
                    "sha256": hashlib.sha256(b"apk-data").hexdigest(),
                    "size": len(b"apk-data"),
                },
            }],
            "uninstallPackages": [],
        }
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return temporary, root

    def test_valid_public_layout_is_accepted(self):
        temporary, root = self.make_layout()
        try:
            manifest, manifest_path, helper, signature = publish.validate_manifest(root)
            self.assertEqual(manifest["releaseId"], "v3-test")
            self.assertEqual(manifest_path.name, "manifest.json")
            self.assertEqual(helper.name, "remote-preinstall.jar")
            self.assertIsNone(signature)
        finally:
            temporary.cleanup()

    def test_payload_hash_mismatch_is_rejected(self):
        temporary, root = self.make_layout()
        try:
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["packages"][0]["payload"]["sha256"] = "b" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                publish.validate_manifest(root)
        finally:
            temporary.cleanup()

    def test_unsafe_object_key_is_rejected(self):
        for key in ("../manifest.json", "/manifest.json", "payload/bad name.apk", "payload//x.apk"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                publish.safe_key(key)

    def test_invalid_signature_size_is_rejected(self):
        temporary, root = self.make_layout()
        try:
            (root / "manifest.sig").write_bytes(b"not-an-ed25519-signature")
            with self.assertRaises(ValueError):
                publish.validate_manifest(root)
        finally:
            temporary.cleanup()

    def test_manifest_is_the_final_publish_operation(self):
        temporary, root = self.make_layout()
        uploaded_keys = []

        def record_upload(_client, _bucket, key, *_args):
            uploaded_keys.append(key)

        try:
            with mock.patch.dict(sys.modules, {"boto3": SimpleNamespace(client=lambda *_args, **_kwargs: object())}):
                with mock.patch.object(publish, "upload", side_effect=record_upload):
                    with mock.patch.object(
                        sys,
                        "argv",
                        [
                            "publish_r2.py",
                            "--public-dir",
                            str(root),
                            "--bucket",
                            "test-bucket",
                            "--endpoint",
                            "https://example.r2.cloudflarestorage.com",
                        ],
                    ):
                        publish.main()
            self.assertEqual(uploaded_keys[-1], "manifest.json")
            self.assertIn("remote-preinstall.jar", uploaded_keys)
            self.assertIn("release-index/v3-test.json", uploaded_keys)
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
