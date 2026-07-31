# Telemetry V2

Telemetry này chỉ dành cho APK Server V2. V1 không bị thay đổi và không gửi dữ liệu.

## Thành phần

- `src/worker.js`: API ingest, API thống kê, R2 storage-health và dashboard tiếng Việt.
- `migrations/0001_initial.sql`: schema Cloudflare D1.
- `wrangler.toml.example`: hai Worker route dưới `apk.daivietpda.com` và binding `ARTIFACTS` tới bucket `apk-server-v2-artifacts`; không chặn manifest hay payload.
- `test/`: unit test chạy bằng Node.js, không cần Cloudflare account.
- Android gửi hàng đợi qua lớp `TelemetryV2` nằm chung `remote-preinstall.jar`.

Dashboard: `https://apk.daivietpda.com/telemetry`

Dashboard có bảng **Tổng thiết bị theo Model / SDK**. Mỗi dòng hiển thị Model, Android SDK, tổng số thiết bị đã ghi nhận và số thiết bị online trong 10 phút gần nhất. Model hoặc SDK trống được gom vào nhóm `Không xác định`. API Basic Auth `/api/v2/stats` trả dữ liệu này trong mảng `deviceGroups` với các trường `model`, `sdk`, `deviceCount`, `onlineDevices`.

Health check công khai: `https://apk.daivietpda.com/api/v2/health`

Storage health có Basic Authentication: `https://apk.daivietpda.com/api/v2/storage-health`

## Dữ liệu được lưu

Mỗi lần cài V2 tạo một UUID ngẫu nhiên trong `/data/local/tmp/.preinstall_v2_device_id`. UUID mất khi factory reset/data bị xóa. Không gửi serial, MAC, IMEI, Android ID hoặc địa chỉ IP vào D1.

Các event: heartbeat, bắt đầu/kết thúc run, manifest, download, install và uninstall. Worker giữ event chi tiết 90 ngày và dọn nền theo xác suất thấp khi nhận event; bảng thiết bị giữ `first_seen`, `last_seen` và trạng thái cuối.

## Tạo D1 và deploy lần đầu

Yêu cầu Node.js 22 và Wrangler 4:

```powershell
cd D:\apk-server-v2\telemetry
npx wrangler@4 login
npx wrangler@4 d1 create apk-server-v2-telemetry
Copy-Item wrangler.toml.example wrangler.toml
```

Thay `REPLACE_WITH_D1_DATABASE_ID` trong `wrangler.toml` bằng ID vừa tạo. File thật bị `.gitignore`.

Tạo hai token ngẫu nhiên khác nhau, tối thiểu lần lượt 32 và 24 ký tự. Không commit hoặc ghi token vào tài liệu:

```powershell
npx wrangler@4 secret put INGEST_TOKEN --config wrangler.toml
npx wrangler@4 secret put DASHBOARD_TOKEN --config wrangler.toml
npx wrangler@4 d1 migrations apply apk-server-v2-telemetry --remote --config wrangler.toml
npx wrangler@4 deploy --config wrangler.toml
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

`factoryreset.conf` chỉ ghi file event atomic vào `/data/local/tmp/preinstall-v2-telemetry/`, tối đa 200 event. Nó không mở kết nối mạng và không đổi exit code cài đặt.

`preinstall-listener.conf`:

- gửi tối đa 5 event mỗi vòng;
- heartbeat mỗi 5 phút;
- coi thiết bị online khi heartbeat trong 10 phút;
- retry từ 30 giây đến tối đa 15 phút;
- chỉ xóa file event sau HTTP 200/202;
- tiếp tục cài APK bình thường nếu token/API/Internet không hoạt động.

## Kiểm thử

```powershell
cd D:\apk-server-v2\telemetry
node --test
node --check src\worker.js
```
