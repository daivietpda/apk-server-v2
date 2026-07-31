import importlib.util
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "update_manifest.py"
spec = importlib.util.spec_from_file_location("update_manifest", MODULE)
manifest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifest)


class ManifestV3Test(unittest.TestCase):
    def test_release_id_is_stable_and_content_addressed(self):
        packages = [{"packageName": "com.example.tv", "payload": {"path": "payload/tv.apk", "sha256": "a" * 64, "size": 1}}]
        uninstall = []
        self.assertEqual(manifest.stable_release_id(packages, uninstall), manifest.stable_release_id(packages, uninstall))
        changed = [{"packageName": "com.example.tv", "payload": {"path": "payload/tv.apk", "sha256": "b" * 64, "size": 1}}]
        self.assertNotEqual(manifest.stable_release_id(packages, uninstall), manifest.stable_release_id(changed, uninstall))

    def test_payload_name_is_content_addressed_and_client_safe(self):
        name = manifest.immutable_payload_name(
            "com.example.tv", 120, "a" * 64, ".APK"
        )
        self.assertEqual(name, "com.example.tv-120-aaaaaaaaaaaa.apk")
        self.assertRegex(name, r"^[A-Za-z0-9._-]+$")

    def test_payload_name_rejects_invalid_hash(self):
        with self.assertRaises(ValueError):
            manifest.immutable_payload_name("com.example.tv", 1, "not-a-hash", ".apk")

    def test_invalid_split_limit_is_defined(self):
        self.assertGreater(manifest.MAX_SPLIT_APKS, 0)
        self.assertGreater(manifest.MAX_SPLIT_EXPANDED_BYTES, 0)


if __name__ == "__main__":
    unittest.main()