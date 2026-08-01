#!/usr/bin/env python3
"""Sign and verify an exact manifest.json byte stream with Ed25519."""
import argparse
import base64
import subprocess
import tempfile
from pathlib import Path


PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64
ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def read_public_key(path):
    value = Path(path).read_bytes()
    if len(value) != PUBLIC_KEY_BYTES:
        raise ValueError("Ed25519 public key must be exactly 32 raw bytes")
    return value


def public_key_pem(public_key):
    if len(public_key) != PUBLIC_KEY_BYTES:
        raise ValueError("Ed25519 public key must be exactly 32 raw bytes")
    der = ED25519_SPKI_PREFIX + public_key
    encoded = base64.encodebytes(der).decode("ascii")
    return "-----BEGIN PUBLIC KEY-----\n" + encoded + "-----END PUBLIC KEY-----\n"


def command(args):
    try:
        return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError("OpenSSL Ed25519 operation failed") from error


def public_key_from_private(private_key):
    result = command(["openssl", "pkey", "-in", str(private_key), "-pubout", "-outform", "DER"])
    value = result.stdout
    if len(value) != len(ED25519_SPKI_PREFIX) + PUBLIC_KEY_BYTES or not value.startswith(ED25519_SPKI_PREFIX):
        raise ValueError("Private key is not an Ed25519 key")
    return value[len(ED25519_SPKI_PREFIX):]


def verify_manifest(manifest, signature, public_key):
    manifest = Path(manifest)
    signature = Path(signature)
    public_key = bytes(public_key)
    if not manifest.is_file() or not signature.is_file() or signature.stat().st_size != SIGNATURE_BYTES:
        raise ValueError("Manifest or Ed25519 signature is invalid")
    with tempfile.TemporaryDirectory() as directory:
        public_pem = Path(directory) / "manifest-ed25519-public.pem"
        public_pem.write_text(public_key_pem(public_key), encoding="ascii")
        command([
            "openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", str(public_pem),
            "-in", str(manifest), "-sigfile", str(signature),
        ])


def sign_manifest(manifest, private_key, signature, public_key):
    manifest = Path(manifest)
    private_key = Path(private_key)
    signature = Path(signature)
    expected_public_key = read_public_key(public_key)
    if not manifest.is_file() or not private_key.is_file():
        raise ValueError("Manifest or private signing key is missing")
    if public_key_from_private(private_key) != expected_public_key:
        raise ValueError("Private signing key does not match the configured public key")
    signature.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(signature.parent)) as directory:
        temporary = Path(directory) / "manifest.sig"
        command([
            "openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(private_key),
            "-in", str(manifest), "-out", str(temporary),
        ])
        if temporary.stat().st_size != SIGNATURE_BYTES:
            raise ValueError("OpenSSL did not create a 64-byte Ed25519 signature")
        verify_manifest(manifest, temporary, expected_public_key)
        temporary.replace(signature)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--signature", type=Path, required=True)
    args = parser.parse_args()
    sign_manifest(args.manifest, args.private_key, args.signature, args.public_key)


if __name__ == "__main__":
    main()
