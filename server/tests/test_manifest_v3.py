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

    def test_invalid_split_limit_is_defined(self):
        self.assertGreater(manifest.MAX_SPLIT_APKS, 0)
        self.assertGreater(manifest.MAX_SPLIT_EXPANDED_BYTES, 0)


if __name__ == "__main__":
    unittest.main()