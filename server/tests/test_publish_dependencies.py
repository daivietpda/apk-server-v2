import subprocess
import sys
import tempfile
import unittest
import zipfile
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = ROOT / "server" / "requirements-publish.txt"
WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"
EXPECTED_PACKAGES = {
    "boto3": "1.43.62",
    "botocore": "1.43.62",
    "jmespath": "1.1.0",
    "python-dateutil": "2.9.0.post0",
    "s3transfer": "0.19.2",
    "six": "1.17.0",
    "urllib3": "2.7.0",
}


def workflow_step(text, name):
    marker = f"      - name: {name}\n"
    start = text.index(marker)
    end = text.find("      - name:", start + len(marker))
    return text[start:] if end == -1 else text[start:end]


def workflow_job(text, name):
    match = re.search(
        rf"^  {re.escape(name)}:\n(.*?)(?=^  [A-Za-z_][A-Za-z0-9_]*:|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise AssertionError(f"Workflow job is missing: {name}")
    return match.group(0)


class PublisherDependencyTests(unittest.TestCase):
    def test_publish_requirements_pin_every_package_and_hash(self):
        packages = {}
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            name_version, hash_option = line.split()
            name, version = name_version.split("==", 1)
            self.assertRegex(hash_option, r"^--hash=sha256:[0-9a-f]{64}$")
            packages[name] = version
        self.assertEqual(packages, EXPECTED_PACKAGES)

    def test_pip_rejects_a_requirement_with_an_incorrect_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            wheel = directory / "testpkg-1.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(
                    "testpkg-1.0.dist-info/WHEEL",
                    "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
                )
                archive.writestr(
                    "testpkg-1.0.dist-info/METADATA",
                    "Metadata-Version: 2.1\nName: testpkg\nVersion: 1.0\n",
                )
                archive.writestr("testpkg-1.0.dist-info/RECORD", "")
            requirements = directory / "bad-requirements.txt"
            requirements.write_text(
                f"testpkg @ {wheel.as_uri()} --hash=sha256:{'0' * 64}\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable, "-m", "pip", "download", "--no-index",
                    "--require-hashes", "--no-deps", "--dest", str(directory / "download"),
                    "-r", str(requirements),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hash", result.stdout.lower() + result.stderr.lower())

    def test_workflow_installs_dependencies_without_secrets_then_publishes(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        install = workflow_step(text, "Install locked publisher dependencies")
        publish = workflow_step(text, "Publish payload first and manifest last")

        self.assertIn("--require-hashes", install)
        self.assertIn("--only-binary=:all:", install)
        self.assertIn("--no-deps", install)
        self.assertIn("-r server/requirements-publish.txt", install)
        self.assertNotIn("AWS_", install)
        self.assertNotIn("R2_", install)
        self.assertNotIn("CLOUDFLARE_", install)
        self.assertIn("AWS_ACCESS_KEY_ID", publish)
        self.assertIn("AWS_SECRET_ACCESS_KEY", publish)
        self.assertIn("R2_BUCKET_NAME", publish)
        self.assertNotIn("pip install", publish)
        self.assertIn(".venv-publisher/bin/python server/scripts/publish_r2.py", publish)

    def test_workflow_scopes_write_permission_to_manifest_commit_job(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        build = workflow_job(text, "build")
        commit_manifest = workflow_job(text, "commit_manifest")
        deploy_pages = workflow_job(text, "deploy_pages")
        self.assertIn("contents: read", build)
        self.assertIn("persist-credentials: false", build)
        self.assertNotIn("git push", build)
        self.assertIn("contents: write", commit_manifest)
        self.assertIn("git push origin HEAD:master", commit_manifest)
        self.assertIn("needs: [build, commit_manifest]", deploy_pages)
        self.assertIn("pages: write", deploy_pages)
        self.assertIn("id-token: write", deploy_pages)
