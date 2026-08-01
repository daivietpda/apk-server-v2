#!/usr/bin/env python3
"""Generate the signed-by-hash, URL-free APK Server V2 manifest."""
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
APK_DIR = ROOT / "apk"
POLICY_PATH = ROOT / "manifest-policy.json"
UNINSTALL_POLICY_PATH = ROOT / "uninstall-policy.json"
MANIFEST_PATH = ROOT / "manifest.json"
PACKAGE_RE = re.compile(r"^[A-Za-z0-9._]+$")
BADGING_RE = re.compile(r"^package: name='([^']+)' versionCode='([0-9]+)'", re.MULTILINE)
MAX_SPLIT_APKS = 64
MAX_SPLIT_EXPANDED_BYTES = 1024 * 1024 * 1024
MAX_RELEASE_SEQUENCE = 2_147_483_647


def read_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_policy():
    data = read_json(POLICY_PATH, {})
    return {
        item["file"]: {
            "packageName": str(item.get("packageName", "")),
            "forceInstall": bool(item.get("forceInstall", False)),
        }
        for item in data.get("packages", [])
        if isinstance(item, dict) and item.get("file")
    }


def read_uninstall_policy():
    data = read_json(UNINSTALL_POLICY_PATH, {})
    return {
        item["packageName"]: {
            "enforce": bool(item.get("enforce", False)),
            "keepData": bool(item.get("keepData", False)),
            "userId": int(item.get("userId", 0)),
        }
        for item in data.get("uninstallPackages", [])
        if isinstance(item, dict) and item.get("packageName")
    }


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def immutable_payload_name(package_name, version_code, artifact_sha256, suffix):
    if not PACKAGE_RE.fullmatch(package_name) or not re.fullmatch(r"[0-9a-f]{64}", artifact_sha256):
        raise ValueError("Cannot build immutable payload name from invalid metadata")
    return f"{package_name}-{version_code}-{artifact_sha256[:12]}{suffix.lower()}"


def apk_metadata(aapt2, path):
    result = subprocess.run(
        [aapt2, "dump", "badging", str(path)], check=True, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    match = BADGING_RE.search(result.stdout)
    if not match:
        raise ValueError(f"Cannot read packageName/versionCode from {path.name}")
    return match.group(1), int(match.group(2))


def package_metadata(aapt2, path):
    if path.suffix.lower() == ".apk":
        package_name, version_code = apk_metadata(aapt2, path)
        return "apk", package_name, version_code

    try:
        with zipfile.ZipFile(path) as archive:
            entries = [item for item in archive.infolist() if not item.is_dir()]
            names = [item.filename for item in entries]
            if "base.apk" not in names:
                raise ValueError(f"Split ZIP must contain base.apk: {path.name}")
            if not names or any(
                "/" in name or "\\" in name or PurePosixPath(name).name != name
                for name in names
            ):
                raise ValueError(f"Split ZIP entries must be flat filenames: {path.name}")
            apk_names = sorted(name for name in names if name.endswith(".apk"))
            if len(apk_names) != len(names):
                raise ValueError(f"Split ZIP may contain lowercase .apk files only: {path.name}")
            if len(apk_names) > MAX_SPLIT_APKS:
                raise ValueError(f"Split ZIP contains too many APK files: {path.name}")
            if sum(item.file_size for item in entries) > MAX_SPLIT_EXPANDED_BYTES:
                raise ValueError(f"Split ZIP expands beyond 1 GiB: {path.name}")
            with tempfile.TemporaryDirectory() as temporary:
                extracted = Path(temporary)
                archive.extractall(extracted)
                metadata = [apk_metadata(aapt2, extracted / name) for name in apk_names]
    except zipfile.BadZipFile as error:
        raise ValueError(f"Invalid Split ZIP: {path.name}") from error

    package_name, version_code = metadata[0]
    for split_name, (split_package, split_version) in zip(apk_names, metadata):
        if split_package != package_name or split_version != version_code:
            raise ValueError(
                f"Split metadata mismatch in {path.name}/{split_name}: "
                f"{split_package}@{split_version}, expected {package_name}@{version_code}"
            )
    return "splitZip", package_name, version_code


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def release_payload(packages, uninstall_packages, release_sequence):
    if (isinstance(release_sequence, bool) or not isinstance(release_sequence, int)
            or not 1 <= release_sequence <= MAX_RELEASE_SEQUENCE):
        raise ValueError(f"releaseSequence must be an integer from 1 to {MAX_RELEASE_SEQUENCE}")
    return {
        "schemaVersion": 3,
        "releaseSequence": release_sequence,
        "packages": packages,
        "uninstallPackages": uninstall_packages,
    }


def stable_release_id(packages, uninstall_packages, release_sequence):
    payload = json.dumps(
        release_payload(packages, uninstall_packages, release_sequence),
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return "v3-" + hashlib.sha256(payload).hexdigest()[:20]


def next_release_sequence(packages, uninstall_packages, previous_manifest):
    if not isinstance(previous_manifest, dict):
        return 1
    if "releaseSequence" not in previous_manifest:
        return 1
    previous_sequence = previous_manifest.get("releaseSequence")
    if (isinstance(previous_sequence, bool) or not isinstance(previous_sequence, int)
            or not 1 <= previous_sequence <= MAX_RELEASE_SEQUENCE):
        raise ValueError("Existing manifest has an invalid releaseSequence")
    previous_payload = release_payload(
        previous_manifest.get("packages"),
        previous_manifest.get("uninstallPackages"),
        previous_sequence,
    )
    candidate_payload = release_payload(packages, uninstall_packages, previous_sequence)
    if previous_payload == candidate_payload:
        return previous_sequence
    if previous_sequence == MAX_RELEASE_SEQUENCE:
        raise ValueError("releaseSequence has reached its supported maximum")
    return previous_sequence + 1


def build_manifest(aapt2, policies, uninstall_policies):
    apk_files = sorted(
        (item for item in APK_DIR.iterdir() if item.is_file() and item.suffix.lower() in (".apk", ".zip")),
        key=lambda item: item.name.lower(),
    )
    if not apk_files:
        raise ValueError(f"No APK files found in {APK_DIR}")

    normalized_policies, packages = [], []
    for artifact in apk_files:
        package_format, package_name, version_code = package_metadata(aapt2, artifact)
        if not PACKAGE_RE.fullmatch(package_name):
            raise ValueError(f"Invalid packageName in {artifact.name}: {package_name}")
        policy = policies.get(artifact.name, {"packageName": "", "forceInstall": False})
        configured_package = str(policy.get("packageName", ""))
        force_install = bool(policy.get("forceInstall", False))
        if configured_package and configured_package != package_name:
            raise ValueError(f"packageName policy mismatch for {artifact.name}: configured={configured_package}, actual={package_name}")
        artifact_sha256 = sha256(artifact)
        payload_name = immutable_payload_name(package_name, version_code, artifact_sha256, artifact.suffix)
        normalized_policies.append({"file": artifact.name, "packageName": package_name if force_install else "", "forceInstall": force_install})
        packages.append({
            "name": artifact.stem,
            "packageName": package_name,
            "versionCode": version_code,
            "format": package_format,
            "forceInstall": force_install,
            "payload": {"path": f"payload/{payload_name}", "sha256": artifact_sha256, "size": artifact.stat().st_size},
        })

    if len({item["packageName"] for item in packages}) != len(packages):
        raise ValueError("Multiple artifacts declare the same packageName")

    normalized_uninstall = []
    for package_name in sorted(uninstall_policies):
        if not PACKAGE_RE.fullmatch(package_name):
            raise ValueError(f"Invalid uninstall packageName: {package_name}")
        policy = uninstall_policies[package_name]
        user_id = int(policy.get("userId", 0))
        if user_id < 0 or user_id > 999:
            raise ValueError(f"Invalid uninstall userId for {package_name}: {user_id}")
        normalized_uninstall.append({"action": "uninstall", "packageName": package_name, "enforce": bool(policy.get("enforce", False)), "keepData": bool(policy.get("keepData", False)), "userId": user_id})

    conflicts = sorted({item["packageName"] for item in packages}.intersection(uninstall_policies))
    if conflicts:
        raise ValueError("Packages cannot be installed and uninstalled together: " + ", ".join(conflicts))

    previous_manifest = read_json(MANIFEST_PATH, None)
    release_sequence = next_release_sequence(packages, normalized_uninstall, previous_manifest)
    manifest = {
        "schemaVersion": 3,
        "releaseSequence": release_sequence,
        "packages": packages,
        "uninstallPackages": normalized_uninstall,
    }
    manifest["releaseId"] = stable_release_id(packages, normalized_uninstall, release_sequence)
    return manifest, normalized_policies, normalized_uninstall


def main():
    parser = argparse.ArgumentParser(description="Generate APK Server V2 manifest schema v3")
    parser.add_argument("--aapt2", default="aapt2", help="Path to Android aapt2")
    parser.add_argument("--set-apk", help="Artifact filename whose forceInstall policy will be changed")
    parser.add_argument("--package-name", default="")
    parser.add_argument("--force-install", choices=("true", "false"))
    parser.add_argument("--uninstall-package", default="")
    parser.add_argument("--uninstall-action", choices=("unchanged", "once", "enforce", "remove"), default="unchanged")
    parser.add_argument("--uninstall-keep-data", choices=("true", "false"), default="false")
    parser.add_argument("--uninstall-user-id", type=int, default=0)
    parser.add_argument("--base-url", help=argparse.SUPPRESS)  # accepted only to ease local V1 tooling migration
    args = parser.parse_args()

    policies, uninstall_policies = read_policy(), read_uninstall_policy()
    if args.set_apk:
        selected = APK_DIR / args.set_apk
        if not selected.is_file() or selected.suffix.lower() not in (".apk", ".zip"):
            raise SystemExit(f"APK or Split ZIP does not exist: {args.set_apk}")
        if args.force_install is None:
            raise SystemExit("--force-install is required with --set-apk")
        enabled = args.force_install == "true"
        if enabled and not PACKAGE_RE.fullmatch(args.package_name):
            raise SystemExit("A valid --package-name is required for force-install=true")
        policies[selected.name] = {"packageName": args.package_name if enabled else "", "forceInstall": enabled}

    if args.uninstall_action != "unchanged":
        if not PACKAGE_RE.fullmatch(args.uninstall_package):
            raise SystemExit("A valid --uninstall-package is required")
        if args.uninstall_action == "remove":
            uninstall_policies.pop(args.uninstall_package, None)
        else:
            uninstall_policies[args.uninstall_package] = {"enforce": args.uninstall_action == "enforce", "keepData": args.uninstall_keep_data == "true", "userId": args.uninstall_user_id}

    try:
        manifest, normalized_policies, normalized_uninstall = build_manifest(args.aapt2, policies, uninstall_policies)
    except (ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error
    atomic_json(POLICY_PATH, {"version": 1, "packages": normalized_policies})
    atomic_json(UNINSTALL_POLICY_PATH, {"version": 1, "uninstallPackages": [{key: value for key, value in item.items() if key != "action"} for item in normalized_uninstall]})
    atomic_json(MANIFEST_PATH, manifest)
    print(f"Generated {MANIFEST_PATH} releaseId={manifest['releaseId']} packages={len(manifest['packages'])} uninstallRules={len(normalized_uninstall)}")


if __name__ == "__main__":
    main()
