#!/usr/bin/env python3
"""Verify that public V2 origins expose one complete, matching release."""
import argparse
import hashlib
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


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
        print(f'Retrying method={method} url={url} attempt={attempt + 1}/{attempts} delay={delay}s')
        time.sleep(delay)
    raise RuntimeError(f'Request retry loop exhausted: {url}')


def request(url, method="GET", attempts=5):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Only HTTPS endpoints are accepted: {url}")
    value = urllib.request.Request(url, method=method, headers={"User-Agent": "APK-Server-V2-Release-Verify/1"})
    return open_with_retry(value, url, method, attempts)


def require_same_origin(base_url, final_url):
    base = urllib.parse.urlparse(base_url)
    final = urllib.parse.urlparse(final_url)
    if (base.scheme, base.netloc) != (final.scheme, final.netloc):
        raise ValueError(f'Cross-origin redirect is not allowed: base={base_url} final={final_url}')


def fetch_manifest(base_url):
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", "manifest.json")
    with request(url) as response:
        data = response.read(2 * 1024 * 1024)
        final_url = response.geturl()
    manifest = json.loads(data.decode("utf-8"))
    if manifest.get("schemaVersion") != 3 or not manifest.get("releaseId"):
        raise ValueError(f"Invalid V2 manifest at {url}")
    return data, manifest, final_url


def remote_size(url):
    with request(url, "HEAD") as response:
        value = response.headers.get("Content-Length")
        if value is None:
            raise ValueError(f"Missing Content-Length: {url}")
        return int(value), response.geturl()


def verify_origin(base_url, expected_bytes, expected_manifest, helper_size):
    actual_bytes, actual, final_url = fetch_manifest(base_url)
    require_same_origin(base_url, final_url)
    if actual_bytes != expected_bytes:
        raise ValueError(f"Manifest bytes differ at {base_url}")
    if actual.get("releaseId") != expected_manifest.get("releaseId"):
        raise ValueError(f"releaseId differs at {base_url}")
    print(f"Verified manifest base={base_url} final={final_url} releaseId={actual['releaseId']}")
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
    parser.add_argument("--base-url", action="append", required=True)
    args = parser.parse_args()
    public_dir = args.public_dir.resolve()
    manifest_path = public_dir / "manifest.json"
    helper_path = public_dir / "remote-preinstall.jar"
    expected_bytes = manifest_path.read_bytes()
    expected_manifest = json.loads(expected_bytes.decode("utf-8"))
    if expected_manifest.get("schemaVersion") != 3 or not expected_manifest.get("releaseId"):
        raise SystemExit("Local public manifest is invalid")
    helper_size = helper_path.stat().st_size
    for base_url in args.base_url:
        verify_origin(base_url, expected_bytes, expected_manifest, helper_size)
    print(f"All origins match releaseId={expected_manifest['releaseId']} manifestSha256={digest(expected_bytes)}")


if __name__ == "__main__":
    main()
