# APK Server V2

V2 is an Android removable-preinstall delivery system. It generates a schema-v3 manifest with immutable relative payload paths and SHA-256, downloads only from an allowlisted HTTPS endpoint set, and lets a ROM init service install/update APK or Split APK ZIP payloads after boot.

## Publish layout

GitHub Pages is built by `.github/workflows/pages.yml`:

```text
manifest.json
remote-preinstall.jar
payload/<immutable APK or ZIP filename>
```

`manifest.json` has no server-provided URL. The ROM helper owns the fixed endpoint allowlist. The generated `releaseId` is content-addressed and stays identical when policies and payload bytes have not changed.

## Release workflow

1. Place APK or flat Split APK ZIP files in `server/apk/`.
2. Update `server/manifest-policy.json` for `forceInstall`, and `server/uninstall-policy.json` for uninstall policy.
3. Run `server/manifest.bat` locally, inspect the diff, then commit/push.
4. GitHub Actions validates artifacts, rebuilds the V2 manifest and DEX helper, then deploys Pages.

Do not commit signing keys, release APKs, local Android caches, or the private V1/V2 reference documents.