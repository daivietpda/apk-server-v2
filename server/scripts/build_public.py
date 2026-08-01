#!/usr/bin/env python3
"""Build the immutable GitHub Pages payload directory from a validated V2 manifest."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=ROOT / "manifest.json")
    parser.add_argument("--signature", type=Path, default=ROOT / "manifest.sig")
    parser.add_argument("--artifact-dir", type=Path, default=ROOT / "apk")
    parser.add_argument("--remote-jar", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "public")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 3 or not manifest.get("releaseId"):
        raise SystemExit("Expected manifest schemaVersion=3 with releaseId")
    output = args.output.resolve()
    if output.exists():
        shutil.rmtree(output)
    payload = output / "payload"
    payload.mkdir(parents=True)
    if not args.signature.is_file() or args.signature.stat().st_size != 64:
        raise SystemExit("manifest.sig must contain exactly one 64-byte Ed25519 signature")
    shutil.copy2(args.manifest, output / "manifest.json")
    shutil.copy2(args.signature, output / "manifest.sig")
    if not args.remote_jar.is_file():
        raise SystemExit(f"Remote helper jar is missing: {args.remote_jar}")
    shutil.copy2(args.remote_jar, output / "remote-preinstall.jar")

    artifacts_by_digest = {}
    for artifact in args.artifact_dir.iterdir():
        if artifact.is_file() and artifact.suffix.lower() in (".apk", ".zip"):
            artifact_digest = digest(artifact)
            if artifact_digest in artifacts_by_digest:
                raise SystemExit(f"Duplicate artifact content: {artifact} and {artifacts_by_digest[artifact_digest]}")
            artifacts_by_digest[artifact_digest] = artifact

    seen = set()
    for package in manifest.get("packages", []):
        payload_info = package.get("payload", {})
        relative = payload_info.get("path", "")
        rel_path = PurePosixPath(relative)
        if len(rel_path.parts) != 2 or rel_path.parts[0] != "payload" or rel_path.name != relative.split("/")[-1]:
            raise SystemExit(f"Unsafe payload path: {relative}")
        if relative in seen:
            raise SystemExit(f"Duplicate payload path: {relative}")
        seen.add(relative)
        source = artifacts_by_digest.get(payload_info.get("sha256"))
        if source is None or source.stat().st_size != payload_info.get("size"):
            raise SystemExit(f"Payload source does not match manifest: {relative}")
        shutil.copy2(source, output / rel_path)
    print(f"Built {output} for {manifest['releaseId']}")


if __name__ == "__main__":
    main()
