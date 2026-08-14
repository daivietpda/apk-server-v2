import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Base64;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import javax.net.ssl.HttpsURLConnection;

/** Fixed-endpoint, best-effort telemetry client for APK Server V2 only. */
public final class TelemetryV2 {
    private static final String ENDPOINT = "https://apk.daivietpda.com/api/v2/telemetry";
    private static final File TOKEN_FILE = new File("/product/preinstall/telemetry.key");
    private static final int CONNECT_TIMEOUT_MS = 8_000;
    private static final int READ_TIMEOUT_MS = 8_000;
    private static final int MAX_RESPONSE_BYTES = 4_096;
    private static final String RUNTIME_VERSION = "2.5-enrollment";
    private static final String AUTH_VERSION = "2";
    private static final SecureRandom RANDOM = new SecureRandom();
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
        if (args.length != 8 || !"--enroll".equals(args[0])) {
            throw new IllegalArgumentException("usage: TelemetryV2 --enroll DEVICE_ID MAC EVENT_TIME RELEASE MODEL SDK ROM");
        }
        String deviceId = validateDeviceId(args[1]);
        String macAddress = validate(args[2], "macAddress", 17, true).toLowerCase();
        if (macAddress.length() > 0 && !macAddress.matches("[0-9a-f]{2}(:[0-9a-f]{2}){5}")) {
            throw new SecurityException("invalid macAddress");
        }
        String eventTime = validateDigits(args[3], "eventTime", 13, false);
        String releaseId = validate(args[4], "releaseId", 96, true);
        String model = validate(args[5], "model", 96, true);
        String sdk = validateDigits(args[6], "sdk", 3, true);
        String romVersion = validate(args[7], "romVersion", 128, true);
        String token = readToken();
        postEnrollment(deviceId, macAddress, "preinstall_registered", eventTime, "", "installed",
                "preinstall", "", "", releaseId, "", "Initial preinstall completed", model, sdk,
                romVersion, RUNTIME_VERSION, token);
        System.out.println("TelemetryV2: accepted initial preinstall registration");
    }

    private static String validateDeviceId(String value) {
        String deviceId = validate(value, "deviceId", 36, false);
        if (!deviceId.matches("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")) {
            throw new SecurityException("invalid deviceId");
        }
        return deviceId;
    }

    private static void postEnrollment(String deviceId, String macAddress,
            String event, String eventTime, String runId,
            String state, String phase, String packageName, String versionCode, String releaseId,
            String selectedEndpoint, String message, String model, String sdk, String romVersion,
            String runtimeVersion, String token) throws Exception {
        String nonce = newNonce();
        String canonical = canonicalEvent(deviceId, macAddress, event, eventTime,
                runId, state, phase, packageName,
                versionCode, releaseId, selectedEndpoint, message, model, sdk, romVersion, runtimeVersion, nonce);
        String signature = sign(canonical, token);
        String json = "{" +
                pair("schemaVersion", "2") + "," +
                pair("deviceId", deviceId) + "," +
                pair("macAddress", macAddress) + "," +
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
                pair("runtimeVersion", runtimeVersion) + "," +
                pair("authVersion", AUTH_VERSION) + "," +
                pair("nonce", nonce) + "," +
                pair("signature", signature) + "}";
        post(json.getBytes(StandardCharsets.UTF_8), token);
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

    private static String newNonce() {
        byte[] bytes = new byte[24];
        RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private static String canonicalEvent(String deviceId, String macAddress,
            String event, String eventTime, String runId,
            String state, String phase, String packageName, String versionCode, String releaseId,
            String selectedEndpoint, String message, String model, String sdk, String romVersion, String runtimeVersion, String nonce) {
        return "apk-server-v2-telemetry\n" + AUTH_VERSION + "\n" + deviceId.toLowerCase() + "\n"
                + macAddress + "\n" + event + "\n"
                + eventTime + "\n" + runId + "\n" + state + "\n" + phase + "\n" + packageName + "\n"
                + versionCode + "\n" + releaseId + "\n" + selectedEndpoint + "\n" + message + "\n"
                + model + "\n" + sdk + "\n" + romVersion + "\n" + runtimeVersion + "\n" + nonce;
    }

    private static String sign(String canonical, String token) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(token.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        return Base64.getUrlEncoder().withoutPadding().encodeToString(
                mac.doFinal(canonical.getBytes(StandardCharsets.UTF_8)));
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
