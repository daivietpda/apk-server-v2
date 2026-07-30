#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
APK_DIR = ROOT / "apk"
POLICY_PATH = ROOT / "manifest-policy.json"
UNINSTALL_POLICY_PATH = ROOT / "uninstall-policy.json"
MANIFEST_PATH = ROOT / "manifest.json"
DEFAULT_BASE_URL = "https://daivietpda.github.io/apk-server/apk"
PACKAGE_RE = re.compile(r"^[A-Za-z0-9._]+$")
BADGING_RE = re.compile(
    r"^package: name='([^']+)' versionCode='([0-9]+)'", re.MULTILINE
)


def read_policy():
    if not POLICY_PATH.exists():
        return {}
    data = json.loads(POLICY_PATH.read_text(encoding="utf-8-sig"))
    return {
        item["file"]: {
            "packageName": item.get("packageName", ""),
            "forceInstall": bool(item.get("forceInstall", False)),
        }
        for item in data.get("packages", [])
        if item.get("file")
    }


def read_uninstall_policy():
    if not UNINSTALL_POLICY_PATH.exists():
        return {}
    data = json.loads(UNINSTALL_POLICY_PATH.read_text(encoding="utf-8-sig"))
    return {
        item["packageName"]: {
            "enforce": bool(item.get("enforce", False)),
            "keepData": bool(item.get("keepData", False)),
            "userId": int(item.get("userId", 0)),
        }
        for item in data.get("uninstallPackages", []) if item.get("packageName")
    }


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def apk_metadata(aapt2, path):
    result = subprocess.run(
        [aapt2, "dump", "badging", str(path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    match = BADGING_RE.search(result.stdout)
    if not match:
        raise SystemExit(f"Cannot read packageName/versionCode from {path.name}")
    return match.group(1), int(match.group(2))


def package_metadata(aapt2, path):
    if path.suffix.lower() == ".apk":
        package_name, version_code = apk_metadata(aapt2, path)
        return "apk", package_name, version_code

    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [item.filename for item in entries if not item.is_dir()]
        if "base.apk" not in names:
            raise SystemExit(f"Split ZIP must contain base.apk: {path.name}")
        if any(
            "/" in name or "\\" in name or name in (".", "..")
            for name in names
        ):
            raise SystemExit(f"Split ZIP entries must be flat filenames: {path.name}")
        apk_names = sorted(name for name in names if name.endswith(".apk"))
        if len(apk_names) != len(names):
            raise SystemExit(
                f"Split ZIP may contain lowercase .apk files only: {path.name}"
            )
        if len(apk_names) > 64:
            raise SystemExit(f"Split ZIP contains too many APK files: {path.name}")
        if sum(item.file_size for item in entries) > 1024 * 1024 * 1024:
            raise SystemExit(f"Split ZIP expands beyond 1 GiB: {path.name}")

        with tempfile.TemporaryDirectory() as temporary:
            extracted = Path(temporary)
            archive.extractall(extracted)
            metadata = [apk_metadata(aapt2, extracted / name) for name in apk_names]

    package_name, version_code = metadata[0]
    for split_name, (split_package, split_version) in zip(apk_names, metadata):
        if split_package != package_name or split_version != version_code:
            raise SystemExit(
                f"Split metadata mismatch in {path.name}/{split_name}: "
                f"{split_package}@{split_version}, expected {package_name}@{version_code}"
            )
    return "splitZip", package_name, version_code


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description="Generate remote APK manifest")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--set-apk", help="APK filename whose policy will be changed")
    parser.add_argument("--package-name", default="")
    parser.add_argument("--force-install", choices=("true", "false"))
    parser.add_argument("--aapt2", default="aapt2", help="Path to Android aapt2")
    parser.add_argument("--uninstall-package", default="")
    parser.add_argument("--uninstall-action", choices=("unchanged", "once", "enforce", "remove"), default="unchanged")
    parser.add_argument("--uninstall-keep-data", choices=("true", "false"), default="false")
    parser.add_argument("--uninstall-user-id", type=int, default=0)
    args = parser.parse_args()

    apk_files = sorted(
        [item for item in APK_DIR.iterdir() if item.suffix.lower() in (".apk", ".zip")],
        key=lambda item: item.name.lower(),
    )
    if not apk_files:
        raise SystemExit(f"No APK files found in {APK_DIR}")

    policies = read_policy()
    uninstall_policies = read_uninstall_policy()
    if args.set_apk:
        selected = APK_DIR / args.set_apk
        if not selected.is_file() or selected.suffix.lower() not in (".apk", ".zip"):
            raise SystemExit(f"APK or split ZIP does not exist: {args.set_apk}")
        if args.force_install is None:
            raise SystemExit("--force-install is required with --set-apk")
        enabled = args.force_install == "true"
        if enabled and not PACKAGE_RE.fullmatch(args.package_name):
            raise SystemExit("A valid --package-name is required for force-install=true")
        policies[selected.name] = {
            "packageName": args.package_name if enabled else "",
            "forceInstall": enabled,
        }

    if args.uninstall_action != "unchanged":
        if not PACKAGE_RE.fullmatch(args.uninstall_package):
            raise SystemExit("A valid --uninstall-package is required")
        if args.uninstall_action == "remove":
            uninstall_policies.pop(args.uninstall_package, None)
        else:
            if args.uninstall_user_id < 0 or args.uninstall_user_id > 999:
                raise SystemExit("--uninstall-user-id must be between 0 and 999")
            uninstall_policies[args.uninstall_package] = {
                "enforce": args.uninstall_action == "enforce",
                "keepData": args.uninstall_keep_data == "true",
                "userId": args.uninstall_user_id,
            }

    normalized_policies = []
    packages = []
    base_url = args.base_url.rstrip("/")
    for apk in apk_files:
        policy = policies.get(apk.name, {"packageName": "", "forceInstall": False})
        package_format, package_name, version_code = package_metadata(args.aapt2, apk)
        configured_package = str(policy.get("packageName", ""))
        force_install = bool(policy.get("forceInstall", False))
        if configured_package and configured_package != package_name:
            raise SystemExit(
                f"packageName policy mismatch for {apk.name}: "
                f"configured={configured_package}, actual={package_name}"
            )
        normalized_policies.append({
            "file": apk.name,
            "packageName": package_name if force_install else "",
            "forceInstall": force_install,
        })
        packages.append({
            "name": apk.stem,
            "packageName": package_name,
            "versionCode": version_code,
            "format": package_format,
            "forceInstall": force_install,
            "url": f"{base_url}/{quote(apk.name)}",
            "sha256": sha256(apk),
            "size": apk.stat().st_size,
        })

    install_package_names = {item["packageName"] for item in packages}
    conflicts = sorted(install_package_names.intersection(uninstall_policies))
    if conflicts:
        raise SystemExit("Packages cannot be installed and uninstalled together: " + ", ".join(conflicts))

    normalized_uninstall = []
    for package_name in sorted(uninstall_policies):
        if not PACKAGE_RE.fullmatch(package_name):
            raise SystemExit(f"Invalid uninstall packageName: {package_name}")
        policy = uninstall_policies[package_name]
        user_id = int(policy.get("userId", 0))
        if user_id < 0 or user_id > 999:
            raise SystemExit(f"Invalid uninstall userId for {package_name}: {user_id}")
        normalized_uninstall.append({
            "packageName": package_name,
            "enforce": bool(policy.get("enforce", False)),
            "keepData": bool(policy.get("keepData", False)),
            "userId": user_id,
        })

    atomic_json(POLICY_PATH, {"version": 1, "packages": normalized_policies})
    atomic_json(UNINSTALL_POLICY_PATH, {"version": 1, "uninstallPackages": normalized_uninstall})
    atomic_json(MANIFEST_PATH, {
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "version": 2,
        "packages": packages,
        "uninstallPackages": [{"action": "uninstall", **item} for item in normalized_uninstall],
    })
    print(f"Generated {MANIFEST_PATH} with {len(packages)} APK(s) and {len(normalized_uninstall)} uninstall rule(s)")


if __name__ == "__main__":
    main()
