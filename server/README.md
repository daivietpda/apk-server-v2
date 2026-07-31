# APK Server V2

Android removable-preinstall delivery for single APK and flat Split APK ZIP packages. Vietnamese operations documentation: [README.vi.md](README.vi.md).

## Endpoints

- Primary R2/CDN: `https://apk.daivietpda.com/`
- Independent GitHub Pages fallback: `https://daivietpda.github.io/apk-server-v2/`
- R2 shadow used during rollout: `https://r2-apk.daivietpda.com/`

The schema-v3 manifest contains relative paths only. `RemoteFetchV2` owns a build-time HTTPS allowlist and rejects redirects outside it.

## Release layout

```text
manifest.json
remote-preinstall.jar
payload/<packageName>-<versionCode>-<sha12>.apk
payload/<packageName>-<versionCode>-<sha12>.zip
```

Payload keys are content-addressed and immutable. The installer verifies the declared size and SHA-256 before installation.

## Add, update, enforce, or uninstall applications

Place `.apk` or flat Split APK `.zip` sources under `server/apk/`. The generator reads the real package name and version code with `aapt2`. Persistent reinstall policy lives in `manifest-policy.json`; remote uninstall policy lives in `uninstall-policy.json`.

Run locally:

```bat
manifest.bat --aapt2 C:\Android-SDK\build-tools\35.0.1\aapt2.exe
```

Run **Actions → Build manifest and publish APK server V2** to rebuild without policy changes, or use its install/uninstall inputs. The workflow rejects package conflicts, malformed split archives, invalid metadata, and duplicate packages.

## R2 dual publish

Production artifacts are uploaded directly to the `apk-server-v2-artifacts` R2 bucket and also deployed to GitHub Pages. APK data does not pass through the telemetry Worker.

Repository variables:

```text
R2_BUCKET_NAME=apk-server-v2-artifacts
R2_SHADOW_BASE_URL=https://r2-apk.daivietpda.com/
R2_PUBLISH_ENABLED=true
```

Repository secrets:

```text
CLOUDFLARE_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
```

Use an R2 Object Read & Write token scoped only to this bucket. The publisher uploads immutable payloads first, then the helper and release index, and writes mutable `manifest.json` last. `verify_dual_origin` checks R2 and GitHub Pages expose the same complete release.

Never use routine `sync --delete`. Retain old payloads for rollback and only introduce lifecycle deletion after a dry-run and a tested retention policy.

## Security

- HTTPS hosts are compiled into the Android helper.
- Payload size and SHA-256 are mandatory.
- A package cannot exist in install and uninstall policy at the same time.
- Do not commit signing material, Cloudflare tokens, local deployment configuration, or the private V1/V2 reference documents.
- Repository write access and Actions secrets can change device install/uninstall policy; restrict them to trusted administrators.
