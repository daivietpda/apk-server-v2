# APK Server

Nguồn GitHub Pages dùng để cài đặt, cập nhật, bắt buộc duy trì hoặc gỡ từ xa các ứng dụng Android dạng data app có thể gỡ.

Tài liệu tiếng Anh: [README.md](README.md).

## URL công khai

- Manifest: `https://daivietpda.github.io/apk-server/manifest.json`
- APK/Split ZIP: `https://daivietpda.github.io/apk-server/apk/<tên-file>`
- DEX helper tải HTTPS: `https://daivietpda.github.io/apk-server/remote-preinstall.jar`

## Định dạng payload

### APK đơn

Đặt file `.apk` trực tiếp trong `apk/`. GitHub Actions dùng `aapt2` đọc `packageName` và `versionCode` thực tế từ APK.

### Split APK dạng ZIP

Đặt file `.zip` trong `apk/`. ZIP phải có cấu trúc phẳng, chỉ chứa file `.apk` viết thường và bắt buộc có `base.apk`:

```text
ExampleTV.zip
├── base.apk
├── split_config.arm64_v8a.apk
├── split_config.vi.apk
└── split_config.xhdpi.apk
```

Workflow từ chối thư mục con, file không phải APK, trên 64 APK, dung lượng giải nén trên 1 GiB hoặc các split không cùng package/version. Android giải nén bằng `unzip` rồi cài toàn bộ split qua PackageInstaller session: `install-create`, `install-write`, `install-commit`.

## Hành vi manifest

Mỗi entry được sinh từ metadata thật, SHA-256 và kích thước payload:

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

Khi boot hoặc khi PreinstallManager yêu cầu chạy thủ công, ROM sẽ:

- cài package chưa từng được quản lý;
- chỉ cập nhật khi `versionCode` trên server cao hơn;
- không downgrade;
- tôn trọng package người dùng đã gỡ nếu `forceInstall=false`;
- cài lại package bị thiếu nếu `forceInstall=true`;
- kiểm tra SHA-256 và phiên bản sau khi cài.

Bản cập nhật phải giữ cùng `packageName`, cùng signing certificate và tăng `versionCode`.

## Chính sách forceInstall

Policy được lưu lâu dài trong `manifest-policy.json`. Bật bắt buộc cài lại:

```bat
manifest.bat --aapt2 C:\Android-SDK\build-tools\35.0.1\aapt2.exe --set-apk downloader.apk --package-name com.esaba.downloader --force-install true
```

Tắt chính sách:

```bat
manifest.bat --aapt2 C:\Android-SDK\build-tools\35.0.1\aapt2.exe --set-apk downloader.apk --force-install false
```

`packageName` phải khớp application ID thật bên trong APK/ZIP.

## Chính sách gỡ ứng dụng từ xa

Quy tắc gỡ được lưu trong `uninstall-policy.json` và xuất hiện dưới `uninstallPackages` của manifest v2:

```json
{
  "action": "uninstall",
  "packageName": "com.example.oldapp",
  "enforce": true,
  "keepData": false,
  "userId": 0
}
```

Thêm quy tắc gỡ một lần khi manifest thay đổi:

```bat
manifest.bat --aapt2 C:\Android-SDK\build-tools\35.0.1\aapt2.exe --uninstall-package com.example.oldapp --uninstall-action once --uninstall-user-id 0
```

Luôn bảo đảm package bị gỡ và giữ dữ liệu:

```bat
manifest.bat --aapt2 C:\Android-SDK\build-tools\35.0.1\aapt2.exe --uninstall-package com.example.oldapp --uninstall-action enforce --uninstall-keep-data true --uninstall-user-id 0
```

Xóa quy tắc khỏi policy:

```bat
manifest.bat --aapt2 C:\Android-SDK\build-tools\35.0.1\aapt2.exe --uninstall-package com.example.oldapp --uninstall-action remove
```

ROM dùng `pm uninstall [ -k ] --user <id>`. Với system app, thao tác chỉ gỡ package cho Android user tương ứng; APK read-only vẫn nằm trong image. Một package không được đồng thời xuất hiện trong `packages` và `uninstallPackages`: phải xóa APK/ZIP khỏi `apk/` trước khi thêm quy tắc gỡ.

Theo yêu cầu thiết kế, `factoryreset.conf` không có allowlist package được gỡ. Cần bảo vệ quyền ghi repository và tài khoản GitHub Actions. Manifest hiện dựa vào HTTPS; payload được kiểm tra thêm SHA-256 nhưng manifest chưa được ký bằng khóa offline.

## Chạy cục bộ

`aapt2` phải có trong `PATH` hoặc truyền đường dẫn đầy đủ:

```bat
manifest.bat --aapt2 C:\Android-SDK\build-tools\35.0.1\aapt2.exe
```

Commit các file được sinh/cập nhật:

```text
manifest.json
manifest-policy.json
uninstall-policy.json
```

## Chạy bằng GitHub Actions

Mở **Actions → Build manifest and publish APK server → Run workflow**.

Nhóm cài đặt:

- `apk_file`: tên chính xác của `.apk` hoặc `.zip` trong `apk/`.
- `package_name`: application ID, bắt buộc khi bật `force_install`.
- `force_install`: `true`, `false` hoặc `unchanged`.

Nhóm gỡ ứng dụng:

- `uninstall_package`: package cần gỡ.
- `uninstall_action`: `once`, `enforce`, `remove` hoặc `unchanged`.
- `uninstall_keep_data`: giữ dữ liệu bằng tùy chọn `-k`.
- `uninstall_user_id`: Android user, thông thường là `0` trên Android TV.

Khi push thông thường, input rỗng mặc định thành `unchanged`. Workflow kiểm tra toàn bộ APK/Split ZIP, tạo lại policy/manifest, build `RemoteFetch.java` thành DEX jar, commit file sinh tự động và deploy GitHub Pages.

## Cấu trúc server

```text
apk/                       APK và Split ZIP
scripts/update_manifest.py Công cụ tạo manifest/policy
tools/RemoteFetch.java     Helper Android tải HTTPS có giới hạn host
manifest-policy.json       Chính sách forceInstall
uninstall-policy.json      Chính sách gỡ package
manifest.json              Manifest công khai được sinh tự động
```
