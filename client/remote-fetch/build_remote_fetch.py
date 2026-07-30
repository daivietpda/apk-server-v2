#!/usr/bin/env python3
"""Compile RemoteFetchV2 and package its DEX as remote-preinstall.jar."""
import argparse
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCES = [ROOT / "RemoteFetchV2.java", ROOT / "TelemetryV2.java"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--r8-jar", type=Path, required=True, help="R8/D8 distribution jar")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--javac", default="javac")
    parser.add_argument("--java", default="java")
    parser.add_argument("--min-api", default="29")
    args = parser.parse_args()
    if not args.r8_jar.is_file():
        raise SystemExit(f"R8 jar not found: {args.r8_jar}")
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        classes = temp / "classes"
        dex = temp / "dex"
        classes.mkdir(); dex.mkdir()
        subprocess.run(
            [args.javac, "-source", "8", "-target", "8", "-d", str(classes), *map(str, SOURCES)],
            check=True,
        )
        class_files = sorted(classes.glob("*.class"))
        if not class_files:
            raise SystemExit("javac did not produce class files")
        subprocess.run([args.java, "-cp", str(args.r8_jar), "com.android.tools.r8.D8", "--min-api", str(args.min_api), "--output", str(dex), *map(str, class_files)], check=True)
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
