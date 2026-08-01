#!/usr/bin/env python3
"""Publish a validated V2 public layout to R2 with manifest-last semantics."""
import argparse
import hashlib
import json
import mimetypes
import os
import re
from pathlib import Path, PurePosixPath


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def safe_key(value):
    path = PurePosixPath(value)
    if (not value or value.startswith("/") or "\\" in value or "//" in value
            or any(part in ("", ".", "..") for part in path.parts)
            or any(not re.fullmatch(r"[A-Za-z0-9._-]+", part) for part in path.parts)):
        raise ValueError(f"Unsafe R2 object key: {value}")
    return value


def content_type(path):
    return {
        ".apk": "application/vnd.android.package-archive",
        ".zip": "application/zip",
        ".jar": "application/java-archive",
        ".json": "application/json; charset=utf-8",
    }.get(path.suffix.lower(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")


def head(client, bucket, key):
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except Exception as error:
        response = getattr(error, "response", {})
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = response.get("Error", {}).get("Code")
        if status == 404 or code in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def upload(client, bucket, key, path, metadata, cache_control, immutable):
    key = safe_key(key)
    expected_sha = digest(path)
    expected_size = path.stat().st_size
    existing = head(client, bucket, key)
    if existing is not None and immutable:
        existing_sha = existing.get("Metadata", {}).get("sha256", "")
        if existing.get("ContentLength") != expected_size:
            raise RuntimeError(f"Immutable R2 object has different size: {key}")
        if existing_sha == expected_sha:
            print(f"R2 immutable object already verified: {key}")
            return
        if existing_sha:
            raise RuntimeError(f"Immutable R2 object has different sha256 metadata: {key}")
        print(f"R2 object lacks sha256 metadata; re-uploading verified local object: {key}")

    object_metadata = {str(k): str(v) for k, v in metadata.items() if v is not None}
    object_metadata["sha256"] = expected_sha
    client.upload_file(
        str(path), bucket, key,
        ExtraArgs={
            "ContentType": content_type(path),
            "CacheControl": cache_control,
            "Metadata": object_metadata,
        },
    )
    uploaded = head(client, bucket, key)
    if (uploaded is None or uploaded.get("ContentLength") != expected_size
            or uploaded.get("Metadata", {}).get("sha256") != expected_sha):
        raise RuntimeError(f"R2 verification failed after upload: {key}")
    print(f"R2 uploaded and verified: {key} bytes={expected_size}")


def validate_manifest(public_dir):
    manifest_path = public_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 3 or not isinstance(manifest.get("releaseId"), str):
        raise ValueError("Expected manifest schemaVersion=3 and releaseId")
    packages = manifest.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("Manifest packages must be a non-empty array")
    seen = set()
    for package in packages:
        payload = package.get("payload", {})
        relative = safe_key(payload.get("path", ""))
        if not relative.startswith("payload/") or relative in seen:
            raise ValueError(f"Invalid or duplicate manifest payload: {relative}")
        seen.add(relative)
        if not SHA256_RE.fullmatch(payload.get("sha256", "")) or not isinstance(payload.get("size"), int):
            raise ValueError(f"Invalid payload metadata: {relative}")
        local = public_dir / PurePosixPath(relative)
        if not local.is_file() or local.stat().st_size != payload["size"] or digest(local) != payload["sha256"]:
            raise ValueError(f"Public payload does not match manifest: {relative}")
    helper = public_dir / "remote-preinstall.jar"
    if not helper.is_file() or helper.stat().st_size == 0:
        raise ValueError("remote-preinstall.jar is missing")
    signature = public_dir / "manifest.sig"
    if not signature.is_file() or signature.stat().st_size != 64:
        raise ValueError("manifest.sig must contain exactly one 64-byte Ed25519 signature")
    return manifest, manifest_path, helper, signature


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-dir", type=Path, required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--endpoint", default=os.environ.get("AWS_ENDPOINT_URL"))
    args = parser.parse_args()
    if not args.endpoint or not args.endpoint.startswith("https://"):
        raise SystemExit("A valid HTTPS --endpoint or AWS_ENDPOINT_URL is required")

    import boto3
    public_dir = args.public_dir.resolve()
    manifest, manifest_path, helper, signature = validate_manifest(public_dir)
    client = boto3.client("s3", endpoint_url=args.endpoint, region_name="auto")
    release_id = manifest["releaseId"]

    for package in manifest["packages"]:
        payload = package["payload"]
        key = payload["path"]
        upload(client, args.bucket, key, public_dir / PurePosixPath(key), {
            "package-name": package.get("packageName", ""),
            "version-code": package.get("versionCode", ""),
            "release-id": release_id,
        }, "public, max-age=31536000, immutable", True)

    helper_sha = digest(helper)
    immutable_helper = f"remote-preinstall-{helper_sha[:12]}.jar"
    upload(client, args.bucket, immutable_helper, helper, {"release-id": release_id},
           "public, max-age=31536000, immutable", True)
    upload(client, args.bucket, "remote-preinstall.jar", helper, {"release-id": release_id},
           "public, max-age=300, must-revalidate", False)

    release_key = safe_key(f"release-index/{release_id}.json")
    upload(client, args.bucket, release_key, manifest_path, {"release-id": release_id},
           "public, max-age=31536000, immutable", True)
    upload(client, args.bucket, safe_key(f"release-index/{release_id}.sig"), signature, {"release-id": release_id},
           "public, max-age=31536000, immutable", True)
    upload(client, args.bucket, "manifest.sig", signature, {"release-id": release_id},
           "public, max-age=60, must-revalidate", False)

    # Mutable manifest is deliberately the final write of a release.
    upload(client, args.bucket, "manifest.json", manifest_path, {"release-id": release_id},
           "public, max-age=60, must-revalidate", False)
    print(f"R2 publish complete bucket={args.bucket} releaseId={release_id}")


if __name__ == "__main__":
    main()
