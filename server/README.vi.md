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
   - tạo thư mục Pages `manifest.json`, `remote-preinstall.jar`, `payload/`;
   - deploy lên GitHub Pages và custom domain Cloudflare.

Có thể build/publish lại không thay policy bằng cách mở:

**Actions → Build manifest and publish APK server V2 → Run workflow**

Giữ mặc định `force_install=unchanged`, `uninstall_action=unchanged`, để trống các package/file không cần sửa rồi chọn **Run workflow**.

Tên payload nên có versionCode hoặc hash để URL bất biến. Không thay byte mới vào cùng URL payload đã cache lâu.

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

## Cloudflare/GitHub Pages

`apk.daivietpda.com` là custom domain của Pages V2 và DNS đang qua Cloudflare proxy. GitHub Pages direct vẫn là fallback độc lập với hostname Cloudflare.

Cache Rules đề xuất trong Cloudflare Dashboard:

- `apk.daivietpda.com/payload/*`: Cache Everything, Edge TTL 30 ngày;
- `apk.daivietpda.com/manifest.json`: Cache Everything, Edge TTL 60 giây;
- `apk.daivietpda.com/remote-preinstall.jar`: Cache Everything, Edge TTL 5 phút.

Sau khi thay policy/manifest có thể purge riêng `manifest.json`; không purge toàn bộ payload nếu tên payload bất biến.

## Bảo mật

- Chỉ HTTPS và hostname allowlist nhúng trong helper.
- Redirect ra ngoài allowlist bị từ chối.
- Payload phải khớp SHA-256 và size trước khi cài.
- Không commit signing key, token, APK release nội bộ, cache hoặc hai tài liệu tham chiếu riêng.
- Quyền ghi repository/Actions có thể điều khiển chính sách cài/gỡ; chỉ cấp cho người quản trị tin cậy.