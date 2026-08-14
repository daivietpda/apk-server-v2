# Telemetry V2

Telemetry này chỉ dành cho APK Server V2. V1 không bị thay đổi và không gửi dữ liệu.

## Thành phần

- `src/worker.js`: API ingest, API thống kê, R2 storage-health và dashboard tiếng Việt.
- `migrations/0001_initial.sql`: schema Cloudflare D1.
- `wrangler.toml.example`: hai Worker route dưới `apk.daivietpda.com` và binding `ARTIFACTS` tới bucket `apk-server-v2-artifacts`; không chặn manifest hay payload.
- `test/`: unit test chạy bằng Node.js, không cần Cloudflare account.
- Android gửi hàng đợi qua lớp `TelemetryV2` nằm chung `remote-preinstall.jar`.

Dashboard: `https://apk.daivietpda.com/telemetry`

Dashboard có bảng **Tổng thiết bị theo Model / SDK** và danh sách thiết bị đã hoàn tất preinstall lần đầu. Không còn thống kê online. Model hoặc SDK trống được gom vào nhóm `Không xác định`.

Health check công khai: `https://apk.daivietpda.com/api/v2/health`

Storage health có Basic Authentication: `https://apk.daivietpda.com/api/v2/storage-health`

## Dữ liệu được lưu

Listener ưu tiên đọc MAC của `eth0`, sau đó `wlan0`, và tạo Device ID ổn định từ MAC. MAC, Device ID, thời điểm ghi nhận đầu tiên, model, SDK, ROM và release đầu tiên được lưu trong D1. Nếu không đọc được MAC, listener dùng UUID lưu tại `/data/local/tmp/.preinstall_v2_device_id`.

ROM mới chỉ gửi event `preinstall_registered` sau khi lượt preinstall đầu tiên hoàn tất thành công. Worker dùng `INSERT ... ON CONFLICT DO NOTHING`; không cập nhật `last_seen`, không ghi bảng `events` và không ghi `telemetry_nonces`. MAC là dữ liệu nhận dạng bền vững, vì vậy dashboard và API stats phải luôn được bảo vệ bằng `DASHBOARD_TOKEN`.

## Xác thực và migration telemetry

Client mới (runtime `2.5-enrollment`) gửi `schemaVersion: "2"`, `authVersion: "2"`, nonce ngẫu nhiên và chữ ký HMAC-SHA256 bao gồm cả MAC. Worker chỉ chấp nhận timestamp trong ±10 phút. Replay không cần ghi nonce vì câu lệnh enrollment là idempotent và không thay đổi dòng đã tồn tại. Chữ ký dùng `INGEST_TOKEN`; Device ID/MAC vẫn là dữ liệu client tự khai báo, không phải bằng chứng danh tính.

Worker từ chối payload schema cũ, heartbeat, event chi tiết và payload thiếu `authVersion`/`nonce`/`signature` trước khi chạm D1. Vì vậy phải deploy Worker, JAR và hai script ROM mới trong cùng đợt chuyển đổi.

Worker có rate limit best-effort theo IP Cloudflare, token chung và deviceId claim. Rate limit giúp hạn chế lưu lượng; vì token đang được provision chung trong ROM, nó không thay thế credential riêng từng thiết bị và telemetry không được dùng cho quyết định bảo mật hoặc thanh toán.

## Tạo D1 và deploy lần đầu

Yêu cầu Node.js 22 và Wrangler 4:

```powershell
cd D:\apk-server-v2\telemetry
npm ci
npx --no-install wrangler login
npx --no-install wrangler d1 create apk-server-v2-telemetry
Copy-Item wrangler.toml.example wrangler.toml
```

Thay `REPLACE_WITH_D1_DATABASE_ID` trong `wrangler.toml` bằng ID vừa tạo. File thật bị `.gitignore`.

Tạo hai token ngẫu nhiên khác nhau, tối thiểu lần lượt 32 và 24 ký tự. Không commit hoặc ghi token vào tài liệu:

```powershell
npx --no-install wrangler secret put INGEST_TOKEN --config wrangler.toml
npx --no-install wrangler secret put DASHBOARD_TOKEN --config wrangler.toml
npx --no-install wrangler d1 migrations apply apk-server-v2-telemetry --remote --config wrangler.toml
npx --no-install wrangler deploy --config wrangler.toml
```

Đặt đúng giá trị `INGEST_TOKEN` vào ROM tại:

```text
/product/preinstall/telemetry.key
```

Dùng mẫu `rom-integration/product/preinstall/telemetry.key.example`. File `telemetry.key` bị ignore và không được đưa lên GitHub. Khóa trong firmware chỉ chống gửi rác thông thường, không phải bí mật chống trích xuất ROM; số liệu telemetry không được dùng cho thanh toán hay quyết định bảo mật.

Mở dashboard. Trình duyệt sẽ hỏi Basic Authentication:

```text
Username: admin
Password: giá trị DASHBOARD_TOKEN
```

Có thể thay Basic Authentication bằng Cloudflare Access sau này.

## Deploy bằng GitHub Actions

Tạo repository secrets:

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `TELEMETRY_D1_DATABASE_ID`
- `TELEMETRY_INGEST_TOKEN`
- `TELEMETRY_DASHBOARD_TOKEN`

Mở **Actions → Test and deploy V2 telemetry → Run workflow**, bật `deploy=true`. Push thông thường chỉ chạy test, không tự deploy Worker.

## R2 storage health

Worker dùng binding `ARTIFACTS` theo hướng chỉ đọc trong mã nguồn: chỉ gọi `get`/`head`, không có `put`, `delete` hoặc multipart upload. API đọc `manifest.json`, HEAD tất cả payload và helper rồi báo:

- release ID và thời gian upload manifest;
- số object khai báo/hiện có;
- object thiếu hoặc sai kích thước;
- tổng dung lượng payload theo manifest.

Kết quả được cache 120 giây trong isolate để tránh HEAD toàn bộ bucket ở mỗi lần refresh. Endpoint và dashboard yêu cầu cùng `DASHBOARD_TOKEN`; `/api/v2/health` vẫn công khai và không chạm D1/R2.

## Hành vi Android

`factoryreset.conf` chỉ tạo `enrollment.event` sau `run_completed` thành công. Nó không mở kết nối mạng và không đổi exit code cài đặt. Các event chi tiết chỉ được ghi vào log cục bộ.

`preinstall-listener.conf`:

- chỉ gửi enrollment khi chưa có marker `/data/local/tmp/.preinstall_v2_telemetry_registered`;
- không gửi heartbeat và không thống kê online;
- retry từ 30 giây đến tối đa 15 phút;
- chỉ xóa enrollment và tạo marker sau HTTP 200/202;
- tiếp tục cài APK bình thường nếu token/API/Internet không hoạt động.

## Kiểm thử

```powershell
cd D:\apk-server-v2\telemetry
node --test
node --check src\worker.js
```
