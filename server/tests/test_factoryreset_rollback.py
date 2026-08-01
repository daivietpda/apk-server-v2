import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "rom-integration" / "product" / "preinstall" / "factoryreset.conf"


class FactoryResetRollbackTest(unittest.TestCase):
    def test_factoryreset_rejects_sequence_outside_android_safe_range_before_comparison(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("MAX_RELEASE_SEQUENCE=2147483647", source)
        self.assertIn("is_valid_release_sequence()", source)
        self.assertIn('if ! is_valid_release_sequence "${RELEASE_SEQUENCE}"; then'.replace("$", "$"), source)
        self.assertIn('! is_valid_release_sequence "${state_sequence}"'.replace("$", "$"), source)
        self.assertIn('[ "${#release_sequence}" -le 10 ] || return 1'.replace("$", "$"), source)
