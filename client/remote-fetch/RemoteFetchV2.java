import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import javax.net.ssl.HttpsURLConnection;

/** Minimal HTTPS downloader used by the removable-preinstall init service. */
public final class RemoteFetchV2 {
    private static final String ALLOWED_HOST = "daivietpda.github.io";
    private static final int MAX_REDIRECTS = 5;

    private static URL validateUrl(String value) throws Exception {
        URI uri = new URI(value);
        if (!"https".equalsIgnoreCase(uri.getScheme())
                || !ALLOWED_HOST.equalsIgnoreCase(uri.getHost())) {
            throw new SecurityException("URL is outside HTTPS allowlist: " + value);
        }
        return uri.toURL();
    }

    public static void main(String[] args) {
        try {
            run(args);
        } catch (Throwable error) {
            System.err.println("RemoteFetch failed: " + error);
            error.printStackTrace(System.err);
            System.exit(1);
        }
    }

    private static void run(String[] args) throws Exception {
        if (args.length != 3) {
            throw new IllegalArgumentException("usage: RemoteFetch URL OUTPUT MAX_BYTES");
        }

        URL url = validateUrl(args[0]);
        File output = new File(args[1]);
        long maxBytes = Long.parseLong(args[2]);
        if (maxBytes <= 0) {
            throw new IllegalArgumentException("MAX_BYTES must be positive");
        }

        for (int redirects = 0; ; redirects++) {
            HttpsURLConnection connection = (HttpsURLConnection) url.openConnection();
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(30_000);
            connection.setReadTimeout(120_000);
            connection.setRequestProperty("User-Agent", "Android-RemotePreinstall/1");
            connection.connect();

            int status = connection.getResponseCode();
            if (status == HttpURLConnection.HTTP_MOVED_PERM
                    || status == HttpURLConnection.HTTP_MOVED_TEMP
                    || status == HttpURLConnection.HTTP_SEE_OTHER
                    || status == 307 || status == 308) {
                if (redirects >= MAX_REDIRECTS) {
                    throw new SecurityException("too many redirects");
                }
                String location = connection.getHeaderField("Location");
                connection.disconnect();
                url = validateUrl(new URL(url, location).toString());
                continue;
            }

            if (status != HttpURLConnection.HTTP_OK) {
                connection.disconnect();
                throw new IllegalStateException("HTTP status " + status);
            }

            long declaredLength = connection.getContentLengthLong();
            if (declaredLength > maxBytes) {
                connection.disconnect();
                throw new SecurityException("declared content is too large");
            }

            long total = 0;
            byte[] buffer = new byte[32 * 1024];
            try (InputStream input = connection.getInputStream();
                 FileOutputStream file = new FileOutputStream(output)) {
                int count;
                while ((count = input.read(buffer)) != -1) {
                    total += count;
                    if (total > maxBytes) {
                        throw new SecurityException("download exceeds size limit");
                    }
                    file.write(buffer, 0, count);
                }
                file.getFD().sync();
            } catch (Throwable error) {
                output.delete();
                throw error;
            } finally {
                connection.disconnect();
            }

            if (total == 0) {
                output.delete();
                throw new IllegalStateException("empty response");
            }
            return;
        }
    }
}
