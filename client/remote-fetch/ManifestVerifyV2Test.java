import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.Signature;
import java.util.Arrays;

public final class ManifestVerifyV2Test {
    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    public static void main(String[] args) throws Exception {
        byte[] manifest = new byte[] { 1, 2, 3, 4, 5 };
        KeyPairGenerator generator = KeyPairGenerator.getInstance("Ed25519");
        KeyPair keyPair = generator.generateKeyPair();
        byte[] encodedPublicKey = keyPair.getPublic().getEncoded();
        byte[] publicKey = Arrays.copyOfRange(encodedPublicKey, encodedPublicKey.length - 32, encodedPublicKey.length);
        Signature signer = Signature.getInstance("Ed25519");
        signer.initSign(keyPair.getPrivate());
        signer.update(manifest);
        byte[] signature = signer.sign();

        require(ManifestVerifyV2.verify(manifest, signature, publicKey), "valid signature rejected");
        manifest[0] ^= 1;
        require(!ManifestVerifyV2.verify(manifest, signature, publicKey), "modified manifest accepted");
        manifest[0] ^= 1;
        signature[0] ^= 1;
        require(!ManifestVerifyV2.verify(manifest, signature, publicKey), "modified signature accepted");
        signature[0] ^= 1;
        byte[] otherKey = generator.generateKeyPair().getPublic().getEncoded();
        require(!ManifestVerifyV2.verify(manifest, signature,
                Arrays.copyOfRange(otherKey, otherKey.length - 32, otherKey.length)), "wrong public key accepted");
        require(!ManifestVerifyV2.verify(manifest, new byte[63], publicKey), "wrong signature size accepted");
        System.out.println("ManifestVerifyV2Test: PASS");
    }
}
