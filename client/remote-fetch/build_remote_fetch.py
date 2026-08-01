#!/usr/bin/env python3
"""Compile RemoteFetchV2 and package its DEX as remote-preinstall.jar."""
import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCES = [ROOT / "RemoteFetchV2.java", ROOT / "TelemetryV2.java", ROOT / "ManifestVerifyV2.java"]
BCPROV_VERSION = "1.78.1"
BCPROV_NAME = f"bcprov-jdk15to18-{BCPROV_VERSION}.jar"
BCPROV_URL = f"https://repo1.maven.org/maven2/org/bouncycastle/bcprov-jdk15to18/{BCPROV_VERSION}/{BCPROV_NAME}"
BCPROV_SHA256 = "b6758a0a72ed44dfdb316e50a67919cc4640e160a26b8a7e9d989cdcb3fc8a7f"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_bcprov(configured):
    if configured is not None:
        candidate = configured
    else:
        cache_root = Path(os.environ.get("APK_SERVER_V2_CACHE", tempfile.gettempdir()))
        candidate = cache_root / BCPROV_NAME
        candidate.parent.mkdir(parents=True, exist_ok=True)
        if not candidate.is_file():
            temporary = candidate.with_suffix(".download")
            try:
                with urllib.request.urlopen(BCPROV_URL, timeout=30) as response, temporary.open("wb") as output:
                    shutil.copyfileobj(response, output)
                temporary.replace(candidate)
            finally:
                temporary.unlink(missing_ok=True)
    if not candidate.is_file() or sha256(candidate) != BCPROV_SHA256:
        raise SystemExit("Pinned Bouncy Castle dependency is missing or has an unexpected SHA-256")
    return candidate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--r8-jar", type=Path, required=True, help="R8/D8 distribution jar")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--javac", default="javac")
    parser.add_argument("--java", default="java")
    parser.add_argument("--min-api", default="29")
    parser.add_argument("--bcprov-jar", type=Path, help="Pinned Bouncy Castle provider jar; downloaded to a temporary cache when omitted")
    args = parser.parse_args()
    if not args.r8_jar.is_file():
        raise SystemExit(f"R8 jar not found: {args.r8_jar}")
    bcprov = resolve_bcprov(args.bcprov_jar)
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        classes = temp / "classes"
        dex = temp / "dex"
        classes.mkdir(); dex.mkdir()
        subprocess.run(
            [args.javac, "-source", "8", "-target", "8", "-cp", str(bcprov), "-d", str(classes), *map(str, SOURCES)],
            check=True,
        )
        class_files = sorted(classes.rglob("*.class"))
        if not class_files:
            raise SystemExit("javac did not produce class files")
        subprocess.run([args.java, "-cp", str(args.r8_jar), "com.android.tools.r8.D8", "--min-api", str(args.min_api), "--output", str(dex), *map(str, class_files), str(bcprov)], check=True)
        dex_file = dex / "classes.dex"
        if not dex_file.is_file() or dex_file.stat().st_size == 0:
            raise SystemExit("D8 did not produce classes.dex")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as output:
            output.write(dex_file, "classes.dex")
        temporary.replace(args.output)
    print(f"Built {args.output}")


if __name__ == "__main__":
    main()
