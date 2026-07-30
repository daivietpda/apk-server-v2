# PreinstallManager

Android TV privileged system app yêu cầu chạy lại `/product/preinstall/factoryreset.conf` mà không reboot và không cần platform key hay custom SELinux policy.

## Cơ chế

APK ghi marker nguyên tử vào thư mục external riêng:

```text
/sdcard/Android/data/com.daivietpda.preinstallmanager/files/run
```

Init khởi động `preinstall_listener` với cùng UID/domain đã dùng thành công cho `factoryreset` (`shell`, `inet`, `u:r:shell:s0`). Listener kiểm tra marker mỗi 3 giây, xóa marker trước rồi gọi payload trực tiếp. Listener xử lý tuần tự nên không tạo hai lượt cập nhật từ nhiều lần bấm liên tiếp.

Signing key riêng vẫn được dùng để bảo đảm chỉ APK do chủ ROM phát hành có thể cập nhật đè package. Không cần mapping certificate vào SELinux.

Certificate SHA-256:

```text
609941c719f277aeb9f338a96fb0312f9174048e6e211d655985ab3ec8c90d26
```

## Build

```bat
build-release.bat
```

Kết quả:

```text
release/PreinstallManager.apk
```

Giữ an toàn `signing/preinstall-manager.p12` và `signing.properties`. Không commit hai file này vào repository công khai.

## Thành phần tích hợp ROM

```text
rom-integration/product/PreinstallManager.apk
rom-integration/product/Android.bp
rom-integration/product/product.mk
rom-integration/product/preinstall-listener.conf
rom-integration/init/preinstall-manager.rc
```

APK phải nằm tại `/product/priv-app/PreinstallManager/PreinstallManager.apk`; listener tại `/product/preinstall/preinstall-listener.conf`. Merge service/action trong file rc vào init rc được import lúc boot.

Không cần `mac_permissions.xml`, `seapp_contexts`, `property_contexts` hoặc `.te` mới.

## Kiểm tra

```sh
getprop init.svc.preinstall_listener
ps -AZ | grep preinstall-listener
ls -l /sdcard/Android/data/com.daivietpda.preinstallmanager/files/run
cat /data/local/tmp/product_preinstall.log
logcat -b all -d | grep -E 'preinstall_listener|factoryreset|avc: denied'
```

Log sau khi nhấn nút:

```text
listener: request received
preinstall: start uid=2000 context=u:r:shell:s0 selinux=Enforcing
listener: factoryreset payload finished result=0
```

`preinstall_listener` là service `oneshot` nhưng script chạy vòng lặp, nên trạng thái bình thường là `running`. `factoryreset` không được init start trong lượt thủ công này; listener gọi cùng payload trực tiếp.

## Giới hạn bảo mật

Trên Android 10, app khác thường không ghi được app-specific external directory nếu không có quyền storage phù hợp. Tuy nhiên marker trên shared storage không mạnh bằng Binder/property với SELinux domain riêng. Listener không đọc lệnh hoặc URL từ marker; nội dung marker bị bỏ qua và hành động duy nhất là chạy payload cố định read-only trong `/product`.
