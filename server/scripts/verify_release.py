#!/usr/bin/env python3
"""Verify every public V2 origin exposes one complete signed release."""
import argparse
import base64
import hashlib
import json
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


MAX_MANIFEST_BYTES = 2 * 1024 * 1024
PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64
ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_public_key(path):
    value = Path(path).read_bytes()
    if len(value) != PUBLIC_KEY_BYTES:
        raise ValueError("Ed25519 public key must contain exactly 32 raw bytes")
    return value


def public_key_pem(public_key):
    if len(public_key) != PUBLIC_KEY_BYTES:
        raise ValueError("Ed25519 public key must contain exactly 32 raw bytes")
    der = ED25519_SPKI_PREFIX + public_key
    return "-----BEGIN PUBLIC KEY-----\n" + base64.encodebytes(der).decode("ascii") + "-----END PUBLIC KEY-----\n"


def verify_signature(manifest_bytes, signature, public_key, label):
    if len(signature) != SIGNATURE_BYTES:
        raise ValueError(f"Manifest signature has an invalid size at {label}")
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        manifest_path = directory / "manifest.json"
        signature_path = directory / "manifest.sig"
        public_path = directory / "manifest-ed25519-public.pem"
        manifest_path.write_bytes(manifest_bytes)
        signature_path.write_bytes(signature)
        public_path.write_text(public_key_pem(public_key), encoding="ascii")
        result = subprocess.run(
            ["openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", str(public_path),
             "-in", str(manifest_path), "-sigfile", str(signature_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            raise ValueError(f"Manifest signature verification failed at {label}")


def open_with_retry(value, url, method, attempts):
    retryable_status = {408, 425, 429, 500, 502, 503, 504}
    for attempt in range(1, attempts + 1):
        try:
            return urllib.request.urlopen(value, timeout=45, context=ssl.create_default_context())
        except urllib.error.HTTPError as error:
            if error.code not in retryable_status or attempt == attempts:
                raise
            error.close()
        except urllib.error.URLError:
            if attempt == attempts:
                raise
        delay = min(5 * attempt, 20)
        print(f"Retrying method={method} url={url} attempt={attempt + 1}/{attempts} delay={delay}s")
        time.sleep(delay)
    raise RuntimeError(f"Request retry loop exhausted: {url}")


def request(url, method="GET", attempts=5):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Only HTTPS endpoints are accepted: {url}")
    value = urllib.request.Request(url, method=method, headers={"User-Agent": "APK-Server-V2-Release-Verify/2"})
    return open_with_retry(value, url, method, attempts)


def require_same_origin(base_url, final_url):
    base = urllib.parse.urlparse(base_url)
    final = urllib.parse.urlparse(final_url)
    if (base.scheme, base.netloc) != (final.scheme, final.netloc):
        raise ValueError(f"Cross-origin redirect is not allowed: base={base_url} final={final_url}")


def fetch_manifest(base_url):
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", "manifest.json")
    with request(url) as response:
        data = response.read(MAX_MANIFEST_BYTES + 1)
        final_url = response.geturl()
    if len(data) > MAX_MANIFEST_BYTES:
        raise ValueError(f"Manifest exceeds size limit at {url}")
    manifest = json.loads(data.decode("utf-8"))
    if manifest.get("schemaVersion") != 3 or not manifest.get("releaseId"):
        raise ValueError(f"Invalid V2 manifest at {url}")
    return data, manifest, final_url


def fetch_signature(base_url):
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", "manifest.sig")
    with request(url) as response:
        data = response.read(SIGNATURE_BYTES + 1)
        final_url = response.geturl()
    if len(data) != SIGNATURE_BYTES:
        raise ValueError(f"Manifest signature has an invalid size at {url}")
    return data, final_url


def remote_size(url):
    with request(url, "HEAD") as response:
        value = response.headers.get("Content-Length")
        if value is None:
            raise ValueError(f"Missing Content-Length: {url}")
        return int(value), response.geturl()


def verify_origin(base_url, expected_bytes, expected_signature, expected_manifest, helper_size, public_key):
    actual_bytes, actual, final_url = fetch_manifest(base_url)
    require_same_origin(base_url, final_url)
    if actual_bytes != expected_bytes:
        raise ValueError(f"Manifest bytes differ at {base_url}")
    if actual.get("releaseId") != expected_manifest.get("releaseId"):
        raise ValueError(f"releaseId differs at {base_url}")
    actual_signature, signature_final_url = fetch_signature(base_url)
    require_same_origin(base_url, signature_final_url)
    if actual_signature != expected_signature:
        raise ValueError(f"Manifest signature bytes differ at {base_url}")
    verify_signature(actual_bytes, actual_signature, public_key, base_url)
    print(f"Verified signed manifest base={base_url} final={final_url} releaseId={actual['releaseId']}")
    for package in actual.get("packages", []):
        payload = package.get("payload", {})
        url = urllib.parse.urljoin(base_url.rstrip("/") + "/", payload.get("path", ""))
        size, final = remote_size(url)
        require_same_origin(base_url, final)
        if size != payload.get("size"):
            raise ValueError(f"Payload size differs at {url}: remote={size} manifest={payload.get('size')}")
        print(f"Verified payload package={package.get('packageName')} bytes={size} final={final}")
    helper_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", "remote-preinstall.jar")
    size, final = remote_size(helper_url)
    require_same_origin(base_url, final)
    if size != helper_size:
        raise ValueError(f"Helper size differs at {helper_url}: remote={size} expected={helper_size}")
    print(f"Verified helper bytes={size} final={final}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-dir", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--base-url", action="append", required=True)
    args = parser.parse_args()
    public_dir = args.public_dir.resolve()
    manifest_path = public_dir / "manifest.json"
    signature_path = public_dir / "manifest.sig"
    helper_path = public_dir / "remote-preinstall.jar"
    expected_bytes = manifest_path.read_bytes()
    expected_signature = signature_path.read_bytes()
    expected_manifest = json.loads(expected_bytes.decode("utf-8"))
    if expected_manifest.get("schemaVersion") != 3 or not expected_manifest.get("releaseId"):
        raise SystemExit("Local public manifest is invalid")
    public_key = read_public_key(args.public_key)
    verify_signature(expected_bytes, expected_signature, public_key, "local public layout")
    helper_size = helper_path.stat().st_size
    for base_url in args.base_url:
        verify_origin(base_url, expected_bytes, expected_signature, expected_manifest, helper_size, public_key)
    print(f"All origins match signed releaseId={expected_manifest['releaseId']} manifestSha256={digest(expected_bytes)}")


if __name__ == "__main__":
    main()