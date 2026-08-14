# Telemetry chỉ ghi thiết bị ở lần preinstall đầu tiên

Tài liệu này mô tả cơ chế enrollment một lần thay cho `presence_only`. Telemetry không còn thống kê online, không gửi heartbeat định kỳ và không lưu lịch sử cài đặt. Mục đích duy nhất là biết những thiết bị nào đã hoàn tất preinstall ít nhất một lần.

## 1. Dữ liệu được giữ

Mỗi thiết bị có tối đa một dòng trong bảng `devices`, gồm:

- Device ID ổn định;
- địa chỉ MAC dùng để nhận dạng và chống tạo dòng trùng sau factory reset;
- thời điểm Worker ghi nhận lần đầu (`first_seen`);
- model, Android SDK, phiên bản ROM và release preinstall đầu tiên.

Migration `0005_compact_enrollment_data.sql` đã loại bỏ các cột trạng thái/package/message legacy khỏi `devices`. Bảng `events` và `telemetry_nonces` cũng được xoá vì Worker không còn sử dụng.

Địa chỉ MAC là dữ liệu nhận dạng thiết bị. Dashboard phải tiếp tục được bảo vệ bằng `DASHBOARD_TOKEN`, và dữ liệu này không được dùng cho quyết định bảo mật, thanh toán hoặc theo dõi người dùng.

## 2. Luồng trên ROM

1. `factoryreset.conf` chạy preinstall như bình thường và giữ log chi tiết ở thiết bị.
2. Chỉ khi toàn bộ lượt preinstall kết thúc thành công (`run_completed`), script tạo một file `enrollment.event`.
3. `preinstall-listener.conf` đọc MAC, model, SDK và ROM rồi gọi:

```text
TelemetryV2 --enroll DEVICE_ID MAC EVENT_TIME RELEASE MODEL SDK ROM
```

4. Nếu chưa có mạng, listener retry với backoff từ 30 giây đến tối đa 15 phút.
5. Sau HTTP 200/202, listener tạo marker:

```text
/data/local/tmp/.preinstall_v2_telemetry_registered
```

6. Khi marker tồn tại, listener không tạo hoặc gửi thêm telemetry. Không có timer heartbeat.

Device ID được tạo ổn định từ MAC theo mẫu `00000000-0000-4000-8000-xxxxxxxxxxxx`. Ưu tiên `eth0`, sau đó `wlan0`. Nếu không đọc được MAC hợp lệ, listener dùng UUID lưu cục bộ; trường hợp fallback này có thể tạo một dòng mới sau khi `/data` bị xóa.

## 3. Luồng trên Worker và D1

Payload enrollment dùng `schemaVersion=2`, event duy nhất là `preinstall_registered`, và vẫn được xác thực bằng HMAC/timestamp như trước.

Worker chỉ chạy một câu lệnh:

```sql
INSERT INTO devices (..., mac_address)
VALUES (...)
ON CONFLICT DO NOTHING;
```

Các ràng buộc chống trùng gồm:

- khóa chính `device_id`;
- unique index có điều kiện trên `mac_address` khi MAC không rỗng.

Vì vậy retry, replay, reboot hoặc factory reset không cập nhật dòng đã có. Worker chỉ nhận `schemaVersion=2` với `preinstall_registered`; heartbeat và mọi event chi tiết của ROM cũ bị từ chối trước khi chạm D1.

Không còn `TELEMETRY_MODE` hoặc `LEGACY_AUTH_MODE`: enrollment có HMAC, insert-only là hành vi mặc định và duy nhất.

## 4. Dashboard và thống kê

Dashboard đã bỏ:

- số thiết bị online;
- cửa sổ online và `last_seen` động;
- số thiết bị đang cài đặt;
- download/install/failure 24 giờ;
- lịch sử event.

Dashboard chỉ hiển thị:

- tổng số thiết bị đã preinstall;
- tổng theo Model/SDK;
- danh sách MAC, Device ID, ROM, release và thời điểm ghi nhận đầu tiên;
- trạng thái R2 storage độc lập với telemetry.

Mỗi lần refresh chỉ gọi `/api/v2/stats` một lần.

## 5. Migration và thứ tự triển khai

Migration mới:

```text
telemetry/migrations/0004_device_mac_address.sql
```

Triển khai theo thứ tự:

```powershell
cd D:\apk-server-v2\telemetry
npx --no-install wrangler d1 migrations apply apk-server-v2-telemetry --remote --config wrangler.toml
npx --no-install wrangler deploy --config wrangler.toml
```

Sau đó build lại `remote-preinstall.jar`, đưa JAR, `factoryreset.conf` và `preinstall-listener.conf` mới vào cùng một ROM. Listener mới yêu cầu helper có lệnh `--enroll`; không trộn listener mới với JAR cũ.

## 6. Kiểm tra sau deploy

1. Flash ROM sạch và chờ preinstall hoàn tất.
2. Kiểm tra log có dòng `telemetry initial preinstall registered`.
3. Kiểm tra dashboard xuất hiện đúng một thiết bị với MAC mong đợi.
4. Reboot và xác nhận không có request enrollment mới từ listener.
5. Chạy preinstall thủ công và xác nhận marker ngăn gửi lại.
6. Nếu factory reset, ROM có thể gửi lại một request vì marker trong `/data` bị xóa, nhưng `ON CONFLICT DO NOTHING` phải giữ nguyên `first_seen` và không tạo dòng mới.
7. Trong D1 Metrics, Rows written chỉ tăng khi có MAC/Device ID chưa từng được ghi nhận hoặc khi chạy migration/deploy có thao tác schema.

## 7. Giới hạn nhận dạng bằng MAC

- Một số thiết bị có thể không cho user `shell` đọc MAC; lúc đó hệ thống fallback sang UUID.
- Nếu nhà sản xuất cấp trùng MAC cho nhiều box, unique index sẽ coi chúng là một thiết bị. Cần sửa dữ liệu nguồn của ROM/nhà máy thay vì bỏ chống trùng.
- Nếu phần cứng thay MAC hoặc chuyển ưu tiên từ `eth0` sang `wlan0`, thiết bị có thể có nhận dạng mới. Danh sách interface phải được cố định theo dòng sản phẩm.
- MAC được gửi qua HTTPS nhưng vẫn là định danh bền vững; chỉ cấp quyền dashboard cho người vận hành cần thiết.
