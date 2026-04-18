package com.budou.incentive;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.IvParameterSpec;
import java.security.SecureRandom;
import java.util.Base64;

public class AESTest {

    // Generate AES SecretKey with 128-bit key size
    private static SecretKey generateKey() throws Exception {
        KeyGenerator keyGen = KeyGenerator.getInstance("AES");
        keyGen.init(128);
        return keyGen.generateKey();
//        Object o = new Object();
    }

    // Generate Initialization Vector (IV)
    private static byte[] generateIV() {
        byte[] iv = new byte[16];
        new SecureRandom().nextBytes(iv);
        return iv;
    }

    // Encrypt the plaintext using AES-CFB
    public static String encrypt(String plaintext, SecretKey key, byte[] iv) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/CFB/NoPadding");
        IvParameterSpec ivSpec = new IvParameterSpec(iv);
        cipher.init(Cipher.ENCRYPT_MODE, key, ivSpec);
        byte[] encrypted = cipher.doFinal(plaintext.getBytes());
        return Base64.getEncoder().encodeToString(encrypted);
    }

    // Decrypt the ciphertext using AES-CFB (method implemented but not invoked)
    public static String decrypt(String ciphertext, SecretKey key, byte[] iv) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/CFB/NoPadding");
        IvParameterSpec ivSpec = new IvParameterSpec(iv);
        cipher.init(Cipher.DECRYPT_MODE, key, ivSpec);
        byte[] decodedCiphertext = Base64.getDecoder().decode(ciphertext);
        byte[] decrypted = cipher.doFinal(decodedCiphertext);
        return new String(decrypted);
    }

    public static void main(String[] args) {
        try {
            String plaintext = "Hello, AES-CFB Encryption!";

            // Generate key and IV
            SecretKey key = generateKey();
            byte[] iv = generateIV();

            // Encrypt the plaintext
            String encryptedText = encrypt(plaintext, key, iv);

            // Output key, IV, plaintext, and ciphertext
            System.out.println("Generated Key: " + Base64.getEncoder().encodeToString(key.getEncoded()));
            System.out.println("Generated IV: " + Base64.getEncoder().encodeToString(iv));
            System.out.println("Plaintext: " + plaintext);
            System.out.println("Encrypted: " + encryptedText);
        } catch (Exception e) {
            e.printStackTrace();
        }
    }
}