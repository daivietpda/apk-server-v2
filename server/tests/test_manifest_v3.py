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
        self.assertEqual(
            manifest.stable_release_id(packages, uninstall, 1),
            manifest.stable_release_id(packages, uninstall, 1),
        )
        changed = [{"packageName": "com.example.tv", "payload": {"path": "payload/tv.apk", "sha256": "b" * 64, "size": 1}}]
        self.assertNotEqual(
            manifest.stable_release_id(packages, uninstall, 1),
            manifest.stable_release_id(changed, uninstall, 1),
        )
        self.assertNotEqual(
            manifest.stable_release_id(packages, uninstall, 1),
            manifest.stable_release_id(packages, uninstall, 2),
        )

    def test_release_sequence_stays_for_identical_policy_and_increments_for_change(self):
        packages = [{"packageName": "com.example.tv", "payload": {"path": "payload/tv.apk", "sha256": "a" * 64, "size": 1}}]
        uninstall = []
        previous = {
            "schemaVersion": 3,
            "releaseSequence": 7,
            "packages": packages,
            "uninstallPackages": uninstall,
        }
        self.assertEqual(manifest.next_release_sequence(packages, uninstall, previous), 7)
        updated = [{"packageName": "com.example.tv", "payload": {"path": "payload/tv.apk", "sha256": "b" * 64, "size": 1}}]
        self.assertEqual(manifest.next_release_sequence(updated, uninstall, previous), 8)

    def test_release_sequence_bootstraps_legacy_manifest_and_rejects_invalid_value(self):
        packages = [{"packageName": "com.example.tv", "payload": {"path": "payload/tv.apk", "sha256": "a" * 64, "size": 1}}]
        self.assertEqual(manifest.next_release_sequence(packages, [], {"schemaVersion": 3}), 1)
        with self.assertRaises(ValueError):
            manifest.stable_release_id(packages, [], 0)

    def test_release_sequence_has_a_fixed_android_safe_upper_bound(self):
        packages = [{"packageName": "com.example.tv", "payload": {"path": "payload/tv.apk", "sha256": "a" * 64, "size": 1}}]
        maximum = manifest.MAX_RELEASE_SEQUENCE
        self.assertEqual(manifest.next_release_sequence(packages, [], {
            "releaseSequence": maximum, "packages": packages, "uninstallPackages": [],
        }), maximum)
        changed = [{"packageName": "com.example.tv", "payload": {"path": "payload/tv.apk", "sha256": "b" * 64, "size": 1}}]
        with self.assertRaises(ValueError):
            manifest.next_release_sequence(changed, [], {
                "releaseSequence": maximum, "packages": packages, "uninstallPackages": [],
            })
        for value in (0, -1, maximum + 1, True, "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                manifest.release_payload(packages, [], value)
            with self.subTest(previous=value), self.assertRaises(ValueError):
                manifest.next_release_sequence(packages, [], {"releaseSequence": value})

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
