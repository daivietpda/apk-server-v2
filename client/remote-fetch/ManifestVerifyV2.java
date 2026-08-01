import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;

import org.bouncycastle.crypto.params.Ed25519PublicKeyParameters;
import org.bouncycastle.crypto.signers.Ed25519Signer;

/**
 * Verifies a detached Ed25519 signature over the exact manifest.json bytes.
 *
 * This uses Bouncy Castle's lightweight API because Android's public Ed25519
 * Signature API is not available on every supported API 29 runtime.
 */
public final class ManifestVerifyV2 {
    private static final int MAX_MANIFEST_BYTES = 1_048_576;
    private static final int PUBLIC_KEY_BYTES = 32;
    private static final int SIGNATURE_BYTES = 64;

    private ManifestVerifyV2() { }

    public static void main(String[] args) {
        try {
            run(args);
        } catch (Throwable error) {
            System.err.println("ManifestVerifyV2 failed: " + error.getMessage());
            System.exit(1);
        }
    }

    static void run(String[] args) throws Exception {
        if (args.length != 6 || !"--manifest".equals(args[0]) || !"--signature".equals(args[2])
                || !"--public-key".equals(args[4])) {
            throw new IllegalArgumentException(
                    "usage: ManifestVerifyV2 --manifest MANIFEST --signature SIGNATURE --public-key PUBLIC_KEY");
        }
        byte[] manifest = readFile(new File(args[1]), MAX_MANIFEST_BYTES);
        byte[] signature = readFile(new File(args[3]), SIGNATURE_BYTES);
        byte[] publicKey = readFile(new File(args[5]), PUBLIC_KEY_BYTES);
        if (signature.length != SIGNATURE_BYTES) {
            throw new SecurityException("signature length is invalid");
        }
        if (publicKey.length != PUBLIC_KEY_BYTES) {
            throw new SecurityException("public key length is invalid");
        }
        if (!verify(manifest, signature, publicKey)) {
            throw new SecurityException("manifest signature verification failed");
        }
    }

    static boolean verify(byte[] manifest, byte[] signature, byte[] publicKey) {
        if (manifest == null || signature == null || publicKey == null
                || signature.length != SIGNATURE_BYTES || publicKey.length != PUBLIC_KEY_BYTES) {
            return false;
        }
        Ed25519Signer verifier = new Ed25519Signer();
        verifier.init(false, new Ed25519PublicKeyParameters(publicKey, 0));
        verifier.update(manifest, 0, manifest.length);
        return verifier.verifySignature(signature);
    }

    private static byte[] readFile(File file, int maximumBytes) throws IOException {
        if (!file.isFile() || file.length() < 0 || file.length() > maximumBytes) {
            throw new IOException("input file is missing or exceeds its size limit");
        }
        ByteArrayOutputStream output = new ByteArrayOutputStream((int) file.length());
        try (FileInputStream input = new FileInputStream(file)) {
            byte[] buffer = new byte[8192];
            for (int count; (count = input.read(buffer)) != -1;) {
                if (output.size() + count > maximumBytes) {
                    throw new IOException("input file exceeds its size limit");
                }
                output.write(buffer, 0, count);
            }
        }
        return output.toByteArray();
    }
}
