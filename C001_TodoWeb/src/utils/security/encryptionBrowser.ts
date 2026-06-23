/**
 * Browser-side encryption and decryption helpers.
 * Uses the Web Crypto API.
 */

// Encryption layout. Keep this in sync with server-side tooling.
const IV_LENGTH = 16;
const AUTH_TAG_LENGTH = 16;
const SALT_LENGTH = 32;

const getWebCrypto = () => {
  if (!globalThis.crypto?.subtle) {
    throw new Error(
      "Web Crypto is unavailable. Open this app through HTTPS or http://localhost. Plain HTTP LAN URLs cannot decrypt synced Todo data.",
    );
  }

  return globalThis.crypto;
};

/**
 * Derive an AES-GCM key from a passphrase.
 */
async function deriveKey(
  passphrase: string,
  salt: Uint8Array,
  usages: KeyUsage[] = ["decrypt"],
): Promise<CryptoKey> {
  const webCrypto = getWebCrypto();
  const encoder = new TextEncoder();
  const passphraseKey = await webCrypto.subtle.importKey(
    "raw",
    encoder.encode(passphrase),
    "PBKDF2",
    false,
    ["deriveBits", "deriveKey"],
  );

  return webCrypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt: salt as BufferSource,
      iterations: 100000,
      hash: "SHA-256",
    },
    passphraseKey,
    { name: "AES-GCM", length: 256 },
    false,
    usages,
  );
}

/**
 * Decode a Base64 string into an ArrayBuffer.
 */
function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const binaryString = atob(base64);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i += 1) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes.buffer;
}

/**
 * Encode an ArrayBuffer as Base64.
 */
function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = "";
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}

/**
 * Encrypt text or binary data.
 */
export async function encrypt(
  data: string | ArrayBuffer,
  passphrase: string,
): Promise<string> {
  const webCrypto = getWebCrypto();
  const salt = webCrypto.getRandomValues(new Uint8Array(SALT_LENGTH));
  const iv = webCrypto.getRandomValues(new Uint8Array(IV_LENGTH));
  const key = await deriveKey(passphrase, salt, ["encrypt"]);
  const payload =
    typeof data === "string" ? new TextEncoder().encode(data) : new Uint8Array(data);

  const cipherBuffer = await webCrypto.subtle.encrypt(
    {
      name: "AES-GCM",
      iv,
      tagLength: AUTH_TAG_LENGTH * 8,
    },
    key,
    payload,
  );

  const cipherBytes = new Uint8Array(cipherBuffer);
  const authTag = cipherBytes.subarray(cipherBytes.length - AUTH_TAG_LENGTH);
  const encrypted = cipherBytes.subarray(0, cipherBytes.length - AUTH_TAG_LENGTH);

  const result = new Uint8Array(
    SALT_LENGTH + IV_LENGTH + AUTH_TAG_LENGTH + encrypted.length,
  );
  result.set(salt, 0);
  result.set(iv, SALT_LENGTH);
  result.set(authTag, SALT_LENGTH + IV_LENGTH);
  result.set(encrypted, SALT_LENGTH + IV_LENGTH + AUTH_TAG_LENGTH);

  return arrayBufferToBase64(result.buffer);
}

function validateDecryptedFile(
  data: ArrayBuffer,
  filename?: string,
): { isValid: boolean; fileType: string; reason?: string } {
  const bytes = new Uint8Array(data);

  if (bytes.length === 0) {
    return { isValid: false, fileType: "unknown", reason: "File is empty" };
  }

  const ext = filename ? filename.toLowerCase().split(".").pop() : "";

  if (ext === "pdf" || filename?.includes(".pdf")) {
    const header = new TextDecoder().decode(
      bytes.subarray(0, Math.min(8, bytes.length)),
    );
    if (header.startsWith("%PDF")) {
      return { isValid: true, fileType: "pdf" };
    }
    return {
      isValid: false,
      fileType: "pdf",
      reason: `Invalid PDF header: ${Array.from(bytes.subarray(0, 8))
        .map((b) => b.toString(16).padStart(2, "0"))
        .join(" ")}`,
    };
  }

  if (ext === "epub" || filename?.includes(".epub")) {
    if (bytes.length < 4) {
      return { isValid: false, fileType: "epub", reason: "File is too small" };
    }
    if (bytes[0] === 0x50 && bytes[1] === 0x4b) {
      return { isValid: true, fileType: "epub" };
    }
    return {
      isValid: false,
      fileType: "epub",
      reason: `Invalid ZIP/EPUB header: ${Array.from(bytes.subarray(0, 4))
        .map((b) => b.toString(16).padStart(2, "0"))
        .join(" ")}`,
    };
  }

  if (ext === "json" || filename?.includes(".json")) {
    try {
      const text = new TextDecoder().decode(data);
      JSON.parse(text);
      return { isValid: true, fileType: "json" };
    } catch {
      return { isValid: false, fileType: "json", reason: "Invalid JSON format" };
    }
  }

  return { isValid: true, fileType: ext || "unknown" };
}

/**
 * Decrypt Base64-encoded encrypted data.
 */
export async function decrypt(
  encryptedData: string,
  passphrase: string,
  filenameOrType?: string,
): Promise<ArrayBuffer> {
  const webCrypto = getWebCrypto();
  const buffer = new Uint8Array(base64ToArrayBuffer(encryptedData));

  const salt = buffer.subarray(0, SALT_LENGTH);
  const iv = buffer.subarray(SALT_LENGTH, SALT_LENGTH + IV_LENGTH);
  const authTag = buffer.subarray(
    SALT_LENGTH + IV_LENGTH,
    SALT_LENGTH + IV_LENGTH + AUTH_TAG_LENGTH,
  );
  const encrypted = buffer.subarray(SALT_LENGTH + IV_LENGTH + AUTH_TAG_LENGTH);

  const key = await deriveKey(passphrase, salt);

  const ciphertext = new Uint8Array(encrypted.length + authTag.length);
  ciphertext.set(encrypted, 0);
  ciphertext.set(authTag, encrypted.length);

  const decrypted = await webCrypto.subtle.decrypt(
    {
      name: "AES-GCM",
      iv,
      tagLength: AUTH_TAG_LENGTH * 8,
    },
    key,
    ciphertext,
  );

  if (filenameOrType) {
    const validation = validateDecryptedFile(decrypted, filenameOrType);
    if (!validation.isValid) {
      console.error(`File validation failed: ${filenameOrType}`);
      console.error(`Reason: ${validation.reason}`);
      throw new Error(`File validation failed: ${validation.reason}`);
    }
    console.log(`File validation passed: ${validation.fileType.toUpperCase()}`);
  }

  return decrypted;
}

/**
 * Decrypt data and return UTF-8 text.
 */
export async function decryptToString(
  encryptedData: string,
  passphrase: string,
): Promise<string> {
  const decrypted = await decrypt(encryptedData, passphrase);
  const decoder = new TextDecoder("utf-8");
  return decoder.decode(decrypted);
}

/**
 * Decrypt data into a Blob.
 */
export async function decryptToBlob(
  encryptedData: string,
  passphrase: string,
  mimeType: string = "application/octet-stream",
): Promise<Blob> {
  const decrypted = await decrypt(encryptedData, passphrase);
  return new Blob([decrypted], { type: mimeType });
}

/**
 * Check whether a string looks like encrypted payload data.
 */
export function isEncrypted(data: string): boolean {
  const trimmed = data.trim();

  const minLength = Math.ceil(
    ((SALT_LENGTH + IV_LENGTH + AUTH_TAG_LENGTH + 1) * 4) / 3,
  );
  if (trimmed.length < minLength) {
    return false;
  }

  const checkLength = Math.min(100, Math.floor(trimmed.length / 2));
  const start = trimmed.substring(0, checkLength);
  const end = trimmed.substring(trimmed.length - checkLength);
  const base64Regex = /^[A-Za-z0-9+/=\s]+$/;

  if (!base64Regex.test(start) || !base64Regex.test(end)) {
    return false;
  }

  try {
    const buffer = base64ToArrayBuffer(trimmed);
    return buffer.byteLength >= SALT_LENGTH + IV_LENGTH + AUTH_TAG_LENGTH + 1;
  } catch {
    return false;
  }
}

/**
 * Get the encryption key from Vite environment variables.
 */
export function getEncryptionKey(): string {
  const key = import.meta.env.VITE_ENCRYPTION_KEY || "";
  return key;
}

/**
 * Load content from a URL or string and decrypt it when needed.
 */
export async function smartLoad(
  urlOrContent: string,
  options: {
    asText?: boolean;
    mimeType?: string;
  } = {},
): Promise<string | Blob> {
  const { asText = true, mimeType = "application/octet-stream" } = options;
  const encryptionKey = getEncryptionKey();

  const isUrl =
    urlOrContent.startsWith("http://") ||
    urlOrContent.startsWith("https://") ||
    (urlOrContent.startsWith("/") && urlOrContent.length < 1000);

  let content: string;
  if (isUrl) {
    const response = await fetch(urlOrContent);
    content = await response.text();
  } else {
    content = urlOrContent;
  }

  const encrypted = encryptionKey ? isEncrypted(content) : false;
  if (encryptionKey && encrypted) {
    try {
      if (asText) {
        return await decryptToString(content, encryptionKey);
      }
      return await decryptToBlob(content, encryptionKey, mimeType);
    } catch (error) {
      console.error("Decrypt failed:", error);
      throw new Error("File decrypt failed. Check that the key is correct.");
    }
  }

  if (asText) {
    return content;
  }
  return new Blob([content], { type: mimeType });
}
