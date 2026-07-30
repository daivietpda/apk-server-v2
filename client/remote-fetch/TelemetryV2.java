import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import javax.net.ssl.HttpsURLConnection;

/** Fixed-endpoint, best-effort telemetry client for APK Server V2 only. */
public final class TelemetryV2 {
    private static final String ENDPOINT = "https://apk.daivietpda.com/api/v2/telemetry";
    private static final File TOKEN_FILE = new File("/product/preinstall/telemetry.key");
    private static final int CONNECT_TIMEOUT_MS = 8_000;
    private static final int READ_TIMEOUT_MS = 8_000;
    private static final int MAX_RESPONSE_BYTES = 4_096;
    private static final String RUNTIME_VERSION = "2.2-telemetry1";
    private static final String[] EVENTS = {
        "heartbeat", "run_started", "manifest_loaded", "manifest_failed",
        "download_started", "download_completed", "download_failed",
        "install_started", "install_completed", "install_failed",
        "uninstall_started", "uninstall_completed", "uninstall_failed",
        "run_completed", "run_failed"
    };

    private TelemetryV2() { }

    public static void main(String[] args) {
        try {
            run(args);
        } catch (Throwable error) {
            System.err.println("TelemetryV2 failed: " + error);
            System.exit(1);
        }
    }

    private static void run(String[] args) throws Exception {
        if (args.length != 15 || !"--post".equals(args[0])) {
            throw new IllegalArgumentException("usage: TelemetryV2 --post DEVICE_ID EVENT EVENT_TIME RUN_ID STATE PHASE PACKAGE VERSION RELEASE ENDPOINT MESSAGE MODEL SDK ROM");
        }
        String deviceId = validate(args[1], "deviceId", 36, false);
        if (!deviceId.matches("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")) {
            throw new SecurityException("invalid deviceId");
        }
        String event = validate(args[2], "event", 32, false);
        if (!isAllowedEvent(event)) throw new SecurityException("invalid event");
        String eventTime = validateDigits(args[3], "eventTime", 13, false);
        String runId = validate(args[4], "runId", 64, true);
        String state = validate(args[5], "state", 24, true);
        String phase = validate(args[6], "phase", 32, true);
        String packageName = validate(args[7], "packageName", 160, true);
        String versionCode = validateDigits(args[8], "versionCode", 20, true);
        String releaseId = validate(args[9], "releaseId", 96, true);
        String selectedEndpoint = validate(args[10], "endpoint", 160, true);
        String message = validate(args[11], "message", 240, true);
        String model = validate(args[12], "model", 96, true);
        String sdk = validateDigits(args[13], "sdk", 3, true);
        String romVersion = validate(args[14], "romVersion", 128, true);
        String token = readToken();

        String json = "{" +
                pair("schemaVersion", "1") + "," +
                pair("deviceId", deviceId) + "," +
                pair("event", event) + "," +
                pair("eventTime", eventTime) + "," +
                pair("runId", runId) + "," +
                pair("state", state) + "," +
                pair("phase", phase) + "," +
                pair("packageName", packageName) + "," +
                pair("versionCode", versionCode) + "," +
                pair("releaseId", releaseId) + "," +
                pair("endpoint", selectedEndpoint) + "," +
                pair("message", message) + "," +
                pair("model", model) + "," +
                pair("sdk", sdk) + "," +
                pair("romVersion", romVersion) + "," +
                pair("runtimeVersion", RUNTIME_VERSION) + "}";
        post(json.getBytes(StandardCharsets.UTF_8), token);
        System.out.println("TelemetryV2: accepted event=" + event);
    }

    private static boolean isAllowedEvent(String event) {
        for (String allowed : EVENTS) if (allowed.equals(event)) return true;
        return false;
    }

    private static String validate(String value, String name, int max, boolean emptyAllowed) {
        if (value == null || value.length() > max || (!emptyAllowed && value.length() == 0)) {
            throw new SecurityException("invalid " + name);
        }
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            if (character < 0x20 || character == 0x7f) throw new SecurityException("invalid " + name);
        }
        return value;
    }

    private static String validateDigits(String value, String name, int max, boolean emptyAllowed) {
        validate(value, name, max, emptyAllowed);
        if (value.length() > 0 && !value.matches("[0-9]+")) throw new SecurityException("invalid " + name);
        return value;
    }

    private static String readToken() throws Exception {
        if (!TOKEN_FILE.isFile() || TOKEN_FILE.length() < 32 || TOKEN_FILE.length() > 256) {
            throw new SecurityException("telemetry token is unavailable");
        }
        byte[] bytes = readLimited(new FileInputStream(TOKEN_FILE), 256);
        String token = new String(bytes, StandardCharsets.US_ASCII).trim();
        if (!token.matches("[A-Za-z0-9._~-]{32,128}")) throw new SecurityException("invalid telemetry token");
        return token;
    }

    private static String pair(String key, String value) {
        return "\"" + key + "\":\"" + escape(value) + "\"";
    }

    private static String escape(String value) {
        StringBuilder output = new StringBuilder(value.length() + 16);
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            if (character == '\\' || character == '"') output.append('\\');
            output.append(character);
        }
        return output.toString();
    }

    private static void post(byte[] body, String token) throws Exception {
        URL url = new URL(ENDPOINT);
        HttpsURLConnection connection = (HttpsURLConnection) url.openConnection();
        connection.setInstanceFollowRedirects(false);
        connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
        connection.setReadTimeout(READ_TIMEOUT_MS);
        connection.setRequestMethod("POST");
        connection.setDoOutput(true);
        connection.setFixedLengthStreamingMode(body.length);
        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        connection.setRequestProperty("User-Agent", "Android-RemotePreinstall/V2-Telemetry");
        connection.setRequestProperty("X-Telemetry-Key", token);
        try {
            try (OutputStream output = connection.getOutputStream()) {
                output.write(body);
                output.flush();
            }
            int status = connection.getResponseCode();
            InputStream response = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
            if (response != null) readLimited(response, MAX_RESPONSE_BYTES);
            if (status != HttpURLConnection.HTTP_OK && status != HttpURLConnection.HTTP_ACCEPTED) {
                throw new IllegalStateException("HTTP status " + status);
            }
        } finally {
            connection.disconnect();
        }
    }

    private static byte[] readLimited(InputStream input, int maxBytes) throws Exception {
        try (InputStream source = input; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[1024];
            int total = 0;
            for (int count; (count = source.read(buffer)) != -1;) {
                total += count;
                if (total > maxBytes) throw new SecurityException("response exceeds limit");
                output.write(buffer, 0, count);
            }
            return output.toByteArray();
        }
    }
}
