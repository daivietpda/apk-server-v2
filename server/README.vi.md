# APK Server V2 — hướng dẫn vận hành

Repository: `https://github.com/daivietpda/apk-server-v2`

Endpoint V2:

- CDN chính: `https://apk.daivietpda.com/`
- GitHub Pages dự phòng: `https://daivietpda.github.io/apk-server-v2/`
- Manifest: `manifest.json`
- Payload: `payload/<filename>`

Manifest schema v3 không chứa URL từ server. Android helper chỉ nhận relative path và tự chọn endpoint trong HTTPS allowlist được nhúng khi build.

## Build manifest và publish APK

1. Mở thư mục `server/apk/`.
2. Thêm, thay hoặc xóa file `.apk` hay Split APK `.zip`.
3. Commit và push lên nhánh `master`.
4. Workflow **Build manifest and publish APK server V2** tự động:
   - kiểm tra APK/Split ZIP bằng `aapt2`;
   - chạy unit test;
   - tạo `manifest.json` schema v3;
   - kiểm tra package, versionCode, size và SHA-256;
   - build `RemoteFetchV2` thành DEX jar;
   - tạo một public layout duy nhất gồm `manifest.json`, `remote-preinstall.jar`, `payload/`;
   - deploy cùng byte lên GitHub Pages và R2; R2 luôn upload payload/helper trước, `manifest.json` cuối cùng;
   - kiểm chứng release, size và toàn bộ object trên cả hai origin.

Có thể build/publish lại không thay policy bằng cách mở:

**Actions → Build manifest and publish APK server V2 → Run workflow**

Giữ mặc định `force_install=unchanged`, `uninstall_action=unchanged`, để trống các package/file không cần sửa rồi chọn **Run workflow**.

Generator tự tạo key bất biến dạng `payload/<packageName>-<versionCode>-<sha12>.apk|zip`. Không thay byte mới vào cùng key payload đã cache lâu.

## Nhóm cài đặt

Các input trong **Run workflow**:

- `apk_file`: tên chính xác file `.apk` hoặc `.zip` trong `server/apk/`.
- `package_name`: application ID thực tế; bắt buộc khi `force_install=true`.
- `force_install`:
  - `unchanged`: giữ policy hiện tại;
  - `true`: nếu người dùng gỡ app, lượt chạy sau sẽ cài lại;
  - `false`: người dùng được phép gỡ, hệ thống không tự cài lại app đã gỡ.

Ví dụ bật bắt buộc cài lại Downloader:

```text
apk_file: downloader.apk
package_name: com.esaba.downloader
force_install: true
uninstall_action: unchanged
```

Ví dụ tắt bắt buộc cài lại:

```text
apk_file: downloader.apk
package_name: để trống
force_install: false
uninstall_action: unchanged
```

Policy được lưu tại `server/manifest-policy.json`. Workflow commit policy và manifest sinh tự động trở lại nhánh `master`, vì vậy thay đổi vẫn còn ở lần publish tiếp theo.

## Nhóm gỡ ứng dụng

Các input:

- `uninstall_package`: application ID cần gỡ.
- `uninstall_action`:
  - `unchanged`: giữ policy hiện tại;
  - `once`: chỉ áp dụng khi manifest/release thay đổi;
  - `enforce`: mỗi lượt chạy đều bảo đảm package không còn cài cho user chỉ định;
  - `remove`: xóa quy tắc gỡ khỏi policy.
- `uninstall_keep_data`: bật để dùng `pm uninstall -k`.
- `uninstall_user_id`: Android user ID, thông thường là `0` trên Android TV.

Ví dụ luôn gỡ package nhưng giữ data:

```text
force_install: unchanged
uninstall_package: com.example.oldapp
uninstall_action: enforce
uninstall_keep_data: true
uninstall_user_id: 0
```

Xóa quy tắc:

```text
force_install: unchanged
uninstall_package: com.example.oldapp
uninstall_action: remove
uninstall_keep_data: false
uninstall_user_id: 0
```

Một package không được xuất hiện đồng thời trong nhóm cài và nhóm gỡ. Muốn thêm uninstall rule cho package đang có payload, phải xóa APK/ZIP đó khỏi `server/apk/` trước; generator sẽ từ chối nếu phát hiện xung đột.

Policy gỡ được lưu tại `server/uninstall-policy.json`. ROM dùng `pm uninstall [ -k ] --user <id>`. Với system app, APK read-only vẫn nằm trong image nhưng package bị gỡ/ẩn cho Android user tương ứng.

## Split APK ZIP

ZIP phải phẳng, chỉ chứa `.apk` viết thường và có `base.apk` ở thư mục gốc:

```text
base.apk
split_config.armeabi_v7a.apk
split_config.xhdpi.apk
split_config.vi.apk
```

Tất cả split phải cùng packageName và versionCode. Generator giới hạn số split và tổng dung lượng giải nén; Android dùng PackageInstaller session, abandon session nếu lỗi.

## Chạy cục bộ

```bat
server\manifest.bat --aapt2 C:\Android-SDK\build-tools\35.0.1\aapt2.exe
```

Bật forceInstall cục bộ:

```bat
server\manifest.bat --aapt2 C:\Android-SDK\build-tools\35.0.1\aapt2.exe --set-apk downloader.apk --package-name com.esaba.downloader --force-install true
```

## Cloudflare R2 và GitHub Pages

Kiến trúc production:

- primary artifact: `https://apk.daivietpda.com/` → Cloudflare Cache → bucket R2 `apk-server-v2-artifacts`;
- fallback độc lập: `https://daivietpda.github.io/apk-server-v2/` → GitHub Pages;
- Worker chỉ bắt `/api/v2/*` và `/telemetry*`; APK/ZIP không đi xuyên qua Worker;
- domain shadow dùng khi thử release/cutover: `https://r2-apk.daivietpda.com/`.

Repository variables:

```text
R2_BUCKET_NAME=apk-server-v2-artifacts
R2_SHADOW_BASE_URL=https://r2-apk.daivietpda.com/
R2_PUBLISH_ENABLED=true
```

Repository secrets cần cho GitHub Actions:

```text
CLOUDFLARE_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
```

Tạo R2 API token loại **Object Read & Write**, chỉ áp dụng bucket `apk-server-v2-artifacts`. Không dùng Global API Key và không cấp quyền xóa bucket. Workflow dùng S3 endpoint `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.

Thứ tự publish cố định:

1. validate/build public layout;
2. upload payload bất biến;
3. upload helper immutable và `remote-preinstall.jar`;
4. upload `release-index/<releaseId>.json`;
5. upload `manifest.json` cuối cùng;
6. kiểm chứng domain R2 và GitHub Pages cùng release.

Cache Rules đề xuất:

- `/payload/*`: Cache Everything, Edge TTL 30 ngày hoặc lâu hơn;
- `/manifest.json`: Edge TTL 60 giây;
- `/remote-preinstall.jar`: Edge TTL 5 phút;
- `/api/v2/*` và `/telemetry*`: bypass cache.

Chỉ purge `manifest.json` và helper tên ổn định sau publish; không purge payload bất biến. Không dùng `sync --delete`. Giữ payload cũ tối thiểu 90–180 ngày và diễn tập rollback trước khi bật lifecycle delete.

### Publish R2 bằng GitHub Actions

1. Tạo hai R2 secrets và ba variables ở trên.
2. Chạy workflow một lần khi `R2_PUBLISH_ENABLED=false` để kiểm tra Pages.
3. Đổi `R2_PUBLISH_ENABLED=true`.
4. Mở **Actions → Build manifest and publish APK server V2 → Run workflow**.
5. Kiểm tra các job `deploy_pages`, `publish_r2` và `verify_dual_origin` đều thành công.
6. Mở dashboard `/telemetry`, mục **R2 storage** phải báo đủ object và đúng release ID.

Nếu job R2 lỗi, không xóa payload đã upload. Sửa secret/object rồi chạy lại; publisher có thể dùng lại object immutable đã xác minh và vẫn chỉ thay manifest ở bước cuối.

## Bảo mật

- Chỉ HTTPS và hostname allowlist nhúng trong helper.
- Redirect ra ngoài allowlist bị từ chối.
- Payload phải khớp SHA-256 và size trước khi cài.
- Không commit signing key, token, APK release nội bộ, cache hoặc hai tài liệu tham chiếu riêng.
- Quyền ghi repository/Actions có thể điều khiển chính sách cài/gỡ; chỉ cấp cho người quản trị tin cậy.
