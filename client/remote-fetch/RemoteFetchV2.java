import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import javax.net.ssl.HttpsURLConnection;

/**
 * HTTPS downloader for APK Server V2. The service supplies only a relative path;
 * endpoint selection and redirect allowlisting remain in this immutable helper.
 */
public final class RemoteFetchV2 {
    private static final String[] BASE_ENDPOINTS = {
        "https://apk.daivietpda.com/",
        "https://daivietpda.github.io/apk-server-v2/"
        // Add an independent third mirror here only after it is provisioned and tested.
    };
    private static final int MAX_REDIRECTS = 5;
    private static final int CONNECT_TIMEOUT_MS = 30_000;
    private static final int READ_TIMEOUT_MS = 120_000;

    private RemoteFetchV2() { }

    public static void main(String[] args) {
        try {
            run(args);
        } catch (Throwable error) {
            System.err.println("RemoteFetchV2 failed: " + error);
            error.printStackTrace(System.err);
            System.exit(1);
        }
    }

    private static void run(String[] args) throws Exception {
        if (args.length != 4 || !"--relative".equals(args[0])) {
            throw new IllegalArgumentException("usage: RemoteFetchV2 --relative PATH OUTPUT MAX_BYTES");
        }
        String relativePath = validateRelativePath(args[1]);
        File output = new File(args[2]);
        long maxBytes = Long.parseLong(args[3]);
        if (maxBytes <= 0 || maxBytes > 536_870_912L) {
            throw new IllegalArgumentException("MAX_BYTES must be between 1 and 536870912");
        }
        File parent = output.getParentFile();
        if (parent == null || !parent.isDirectory()) {
            throw new IllegalArgumentException("OUTPUT parent directory does not exist");
        }

        Throwable lastError = null;
        String preferred = System.getenv("REMOTE_FETCH_PREFERRED_ENDPOINT");
        int preferredIndex = endpointIndex(preferred);
        for (int attempt = 0; attempt < BASE_ENDPOINTS.length; attempt++) {
            int endpointIndex = preferredIndex >= 0 ? (preferredIndex + attempt) % BASE_ENDPOINTS.length : attempt;
            String endpoint = BASE_ENDPOINTS[endpointIndex];
            URL initial = new URL(endpoint + relativePath);
            try {
                System.out.println("RemoteFetchV2: attempt endpoint=" + endpoint + " path=" + relativePath);
                download(initial, output, maxBytes);
                System.out.println("RemoteFetchV2: success endpoint=" + endpoint + " path=" + relativePath);
                return;
            } catch (Throwable error) {
                output.delete();
                lastError = error;
                System.err.println("RemoteFetchV2: endpoint failed=" + endpoint + " error=" + error);
            }
        }
        throw new IllegalStateException("all configured endpoints failed for " + relativePath, lastError);
    }

    private static int endpointIndex(String value) {
        if (value == null) return -1;
        for (int index = 0; index < BASE_ENDPOINTS.length; index++) {
            if (BASE_ENDPOINTS[index].equals(value)) return index;
        }
        return -1;
    }
    private static String validateRelativePath(String value) throws Exception {
        URI uri = new URI(value);
        if (value.length() == 0 || value.length() > 240 || uri.isAbsolute() || uri.getRawQuery() != null
                || uri.getRawFragment() != null || value.startsWith("/") || value.contains("\\")
                || value.contains("//")) {
            throw new SecurityException("invalid relative path");
        }
        for (String component : value.split("/")) {
            if (component.length() == 0 || ".".equals(component) || "..".equals(component)
                    || !component.matches("[A-Za-z0-9._-]+")) {
                throw new SecurityException("invalid relative path component");
            }
        }
        if (!(value.equals("manifest.json") || value.equals("manifest.sig")
                || value.equals("remote-preinstall.jar") || value.startsWith("payload/"))) {
            throw new SecurityException("relative path is outside V2 publish layout");
        }
        return value;
    }

    private static boolean isAllowed(URL url) {
        if (!"https".equalsIgnoreCase(url.getProtocol())) return false;
        int port = url.getPort();
        if (port != -1 && port != 443) return false;
        for (String endpoint : BASE_ENDPOINTS) {
            try {
                URL allowed = new URL(endpoint);
                if (allowed.getHost().equalsIgnoreCase(url.getHost())) return true;
            } catch (Exception ignored) { }
        }
        return false;
    }

    private static void download(URL initial, File output, long maxBytes) throws Exception {
        URL url = initial;
        for (int redirects = 0; ; redirects++) {
            if (!isAllowed(url)) throw new SecurityException("redirect is outside HTTPS allowlist: " + url);
            HttpsURLConnection connection = (HttpsURLConnection) url.openConnection();
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
            connection.setReadTimeout(READ_TIMEOUT_MS);
            connection.setRequestProperty("User-Agent", "Android-RemotePreinstall/V2");
            try {
                int status = connection.getResponseCode();
                if (status == HttpURLConnection.HTTP_MOVED_PERM || status == HttpURLConnection.HTTP_MOVED_TEMP
                        || status == HttpURLConnection.HTTP_SEE_OTHER || status == 307 || status == 308) {
                    if (redirects >= MAX_REDIRECTS) throw new SecurityException("too many redirects");
                    String location = connection.getHeaderField("Location");
                    if (location == null || location.length() == 0) throw new SecurityException("redirect has no location");
                    url = new URL(url, location);
                    continue;
                }
                if (status != HttpURLConnection.HTTP_OK) throw new IllegalStateException("HTTP status " + status);
                long declaredLength = connection.getContentLengthLong();
                if (declaredLength == 0 || declaredLength > maxBytes) throw new SecurityException("declared content size is invalid");

                long total = 0;
                byte[] buffer = new byte[32 * 1024];
                try (InputStream input = connection.getInputStream(); FileOutputStream file = new FileOutputStream(output)) {
                    for (int count; (count = input.read(buffer)) != -1;) {
                        total += count;
                        if (total > maxBytes) throw new SecurityException("download exceeds size limit");
                        file.write(buffer, 0, count);
                    }
                    file.getFD().sync();
                } catch (Throwable error) {
                    output.delete();
                    throw error;
                }
                if (total == 0) {
                    output.delete();
                    throw new IllegalStateException("empty response");
                }
                return;
            } finally {
                connection.disconnect();
            }
        }
    }
}