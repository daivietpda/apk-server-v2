# APK Server

GitHub Pages source for remotely installing, updating, enforcing, and uninstalling removable Android applications from an init service.

Vietnamese documentation: [README.vi.md](README.vi.md).

## Published endpoints

- Manifest: `https://daivietpda.github.io/apk-server/manifest.json`
- APK/Split ZIP payloads: `https://daivietpda.github.io/apk-server/apk/<filename>`
- Android HTTPS DEX helper: `https://daivietpda.github.io/apk-server/remote-preinstall.jar`

## Supported payloads

### Single APK

Place an `.apk` file directly under `apk/`. GitHub Actions uses `aapt2` to read its real `packageName` and `versionCode`.

### Split APK ZIP

Place a `.zip` file under `apk/`. The archive must be flat, contain lowercase `.apk` files only, and include `base.apk`:

```text
ExampleTV.zip
├── base.apk
├── split_config.arm64_v8a.apk
├── split_config.en.apk
└── split_config.xhdpi.apk
```

The workflow rejects nested paths, non-APK entries, more than 64 APKs, expansion beyond 1 GiB, or splits with different package/version metadata. Android extracts the ZIP with `unzip` and installs all splits through a PackageInstaller session (`install-create`, `install-write`, `install-commit`).

## Manifest behavior

Generated manifest entries contain the actual APK metadata, SHA-256 and size:

```json
{
  "name": "ExampleTV",
  "packageName": "com.example.tv",
  "versionCode": 120,
  "format": "splitZip",
  "forceInstall": false,
  "url": "https://daivietpda.github.io/apk-server/apk/ExampleTV.zip",
  "sha256": "...",
  "size": 12345678
}
```

At boot or on a manual PreinstallManager request, the ROM:

- installs a package not previously managed;
- updates an installed package only when the server `versionCode` is higher;
- never downgrades;
- leaves a user-removed package absent when `forceInstall=false`;
- reinstalls a missing package when `forceInstall=true`;
- verifies SHA-256 and the installed version after installation.

Updates must keep the same `packageName`, signing certificate, and use a higher `versionCode`.

## Force-install policy

`manifest-policy.json` stores the persistent policy. Enable enforced reinstall locally:

```bat
manifest.bat --aapt2 C:\Android-SDK\build-tools\35.0.1\aapt2.exe --set-apk downloader.apk --package-name com.esaba.downloader --force-install true
```

Disable it:

```bat
manifest.bat --aapt2 C:\Android-SDK\build-tools\35.0.1\aapt2.exe --set-apk downloader.apk --force-install false
```

`packageName` must match the application ID inside the APK/ZIP.

## Remote uninstall policy

Uninstall rules are stored in `uninstall-policy.json` and emitted under `uninstallPackages` in manifest version 2:

```json
{
  "action": "uninstall",
  "packageName": "com.example.oldapp",
  "enforce": true,
  "keepData": false,
  "userId": 0
}
```

Add a one-time rule:

```bat
manifest.bat --aapt2 C:\Android-SDK\build-tools\35.0.1\aapt2.exe --uninstall-package com.example.oldapp --uninstall-action once --uninstall-user-id 0
```

Continuously enforce absence and preserve app data:

```bat
manifest.bat --aapt2 C:\Android-SDK\build-tools\35.0.1\aapt2.exe --uninstall-package com.example.oldapp --uninstall-action enforce --uninstall-keep-data true --uninstall-user-id 0
```

Remove the rule:

```bat
manifest.bat --aapt2 C:\Android-SDK\build-tools\35.0.1\aapt2.exe --uninstall-package com.example.oldapp --uninstall-action remove
```

The ROM uses `pm uninstall [ -k ] --user <id>`. For a system app this removes it only for that Android user; the read-only system APK remains in the image. A package cannot appear in both `packages` and `uninstallPackages`: remove its APK/ZIP from `apk/` before adding an uninstall rule.

There is intentionally no package allowlist in `factoryreset.conf`. Protect repository write access and GitHub Actions credentials accordingly. The manifest currently relies on HTTPS; payload integrity is additionally checked with SHA-256, but the manifest is not offline-signed.

## Run locally

`aapt2` must be on `PATH`, or pass its full path:

```bat
manifest.bat --aapt2 C:\Android-SDK\build-tools\35.0.1\aapt2.exe
```

Commit generated changes to:

```text
manifest.json
manifest-policy.json
uninstall-policy.json
```

## Run with GitHub Actions

Open **Actions → Build manifest and publish APK server → Run workflow**.

Install policy inputs:

- `apk_file`: exact `.apk` or `.zip` filename under `apk/`.
- `package_name`: application ID, required when enabling `force_install`.
- `force_install`: `true`, `false`, or `unchanged`.

Uninstall policy inputs:

- `uninstall_package`: package to remove.
- `uninstall_action`: `once`, `enforce`, `remove`, or `unchanged`.
- `uninstall_keep_data`: preserve package data with `-k`.
- `uninstall_user_id`: Android user, normally `0` on Android TV.

On a normal push, empty workflow inputs default to `unchanged`. The workflow validates all APK/Split ZIP metadata, regenerates policy/manifest files, builds `RemoteFetch.java` as a DEX jar, commits generated changes, and deploys GitHub Pages.

## Server files

```text
apk/                       APK and Split ZIP payloads
scripts/update_manifest.py Manifest/policy generator
tools/RemoteFetch.java     Restricted Android HTTPS downloader
manifest-policy.json       forceInstall policy
uninstall-policy.json      uninstall policy
manifest.json              generated public manifest
```
