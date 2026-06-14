import base64
import ctypes
import hashlib
from ctypes import wintypes

BCRYPT_USE_SYSTEM_PREFERRED_RNG = 0x00000002
BCRYPT_CHAINING_MODE = "ChainingMode"
BCRYPT_CHAIN_MODE_GCM = "ChainingModeGCM"
BCRYPT_AUTH_TAG_LENGTH = "AuthTagLength"
BCRYPT_AES_ALGORITHM = "AES"

STATUS_SUCCESS = 0

bcrypt = ctypes.WinDLL("bcrypt.dll")


class BcryptError(RuntimeError):
    pass


class BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.ULONG),
        ("dwInfoVersion", wintypes.ULONG),
        ("pbNonce", ctypes.POINTER(ctypes.c_ubyte)),
        ("cbNonce", wintypes.ULONG),
        ("pbAuthData", ctypes.POINTER(ctypes.c_ubyte)),
        ("cbAuthData", wintypes.ULONG),
        ("pbTag", ctypes.POINTER(ctypes.c_ubyte)),
        ("cbTag", wintypes.ULONG),
        ("pbMacContext", ctypes.POINTER(ctypes.c_ubyte)),
        ("cbMacContext", wintypes.ULONG),
        ("cbAAD", wintypes.ULONG),
        ("cbData", ctypes.c_ulonglong),
        ("dwFlags", wintypes.ULONG),
    ]


def _check(status, message):
    if status != STATUS_SUCCESS:
        raise BcryptError(f"{message}: Windows status 0x{status & 0xFFFFFFFF:08x}")


def _bytes_buffer(data):
    if not data:
        return None, 0
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return buffer, len(data)


def _random_bytes(length):
    buffer = (ctypes.c_ubyte * length)()
    status = bcrypt.BCryptGenRandom(
        None,
        buffer,
        length,
        BCRYPT_USE_SYSTEM_PREFERRED_RNG,
    )
    _check(status, "BCryptGenRandom failed")
    return bytes(buffer)


def _derive_key(passphrase, salt):
    return hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode("utf-8"),
        salt,
        200_000,
        dklen=32,
    )


def _open_aes_gcm_provider():
    alg_handle = ctypes.c_void_p()
    status = bcrypt.BCryptOpenAlgorithmProvider(
        ctypes.byref(alg_handle),
        BCRYPT_AES_ALGORITHM,
        None,
        0,
    )
    _check(status, "BCryptOpenAlgorithmProvider failed")

    mode_bytes = (BCRYPT_CHAIN_MODE_GCM + "\0").encode("utf-16-le")
    status = bcrypt.BCryptSetProperty(
        alg_handle,
        BCRYPT_CHAINING_MODE,
        mode_bytes,
        len(mode_bytes),
        0,
    )
    _check(status, "BCryptSetProperty failed")
    return alg_handle


def _close_provider(alg_handle):
    if alg_handle:
        bcrypt.BCryptCloseAlgorithmProvider(alg_handle, 0)


def _destroy_key(key_handle):
    if key_handle:
        bcrypt.BCryptDestroyKey(key_handle)


def _make_key(alg_handle, key):
    key_handle = ctypes.c_void_p()
    key_buffer, key_len = _bytes_buffer(key)
    status = bcrypt.BCryptGenerateSymmetricKey(
        alg_handle,
        ctypes.byref(key_handle),
        None,
        0,
        key_buffer,
        key_len,
        0,
    )
    _check(status, "BCryptGenerateSymmetricKey failed")
    return key_handle


def _auth_info(nonce, tag):
    nonce_buffer, nonce_len = _bytes_buffer(nonce)
    tag_buffer, tag_len = _bytes_buffer(tag)
    info = BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO()
    info.cbSize = ctypes.sizeof(BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO)
    info.dwInfoVersion = 1
    info.pbNonce = nonce_buffer
    info.cbNonce = nonce_len
    info.pbTag = tag_buffer
    info.cbTag = tag_len
    return info, tag_buffer


def aes_gcm_encrypt(plaintext, passphrase):
    salt = _random_bytes(16)
    nonce = _random_bytes(12)
    tag = bytearray(16)
    key = _derive_key(passphrase, salt)

    alg_handle = None
    key_handle = None
    try:
        alg_handle = _open_aes_gcm_provider()
        key_handle = _make_key(alg_handle, key)
        plaintext_bytes = plaintext.encode("utf-8")
        input_buffer, input_len = _bytes_buffer(plaintext_bytes)
        output_buffer = (ctypes.c_ubyte * input_len)()
        tag_buffer = (ctypes.c_ubyte * len(tag)).from_buffer(tag)

        info = BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO()
        info.cbSize = ctypes.sizeof(BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO)
        info.dwInfoVersion = 1
        nonce_buffer, nonce_len = _bytes_buffer(nonce)
        info.pbNonce = nonce_buffer
        info.cbNonce = nonce_len
        info.pbTag = tag_buffer
        info.cbTag = len(tag)

        bytes_done = wintypes.ULONG()
        status = bcrypt.BCryptEncrypt(
            key_handle,
            input_buffer,
            input_len,
            ctypes.byref(info),
            None,
            0,
            output_buffer,
            input_len,
            ctypes.byref(bytes_done),
            0,
        )
        _check(status, "BCryptEncrypt failed")
        return {
            "version": 1,
            "algorithm": "AES-256-GCM",
            "kdf": "PBKDF2-HMAC-SHA256",
            "iterations": 200000,
            "salt": base64.b64encode(salt).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(bytes(output_buffer)).decode("ascii"),
            "tag": base64.b64encode(bytes(tag)).decode("ascii"),
        }
    finally:
        _destroy_key(key_handle)
        _close_provider(alg_handle)


def aes_gcm_decrypt(payload, passphrase):
    salt = base64.b64decode(payload["salt"])
    nonce = base64.b64decode(payload["nonce"])
    ciphertext = base64.b64decode(payload["ciphertext"])
    tag = base64.b64decode(payload["tag"])
    key = _derive_key(passphrase, salt)

    alg_handle = None
    key_handle = None
    try:
        alg_handle = _open_aes_gcm_provider()
        key_handle = _make_key(alg_handle, key)
        input_buffer, input_len = _bytes_buffer(ciphertext)
        output_buffer = (ctypes.c_ubyte * input_len)()
        info, _ = _auth_info(nonce, tag)
        bytes_done = wintypes.ULONG()
        status = bcrypt.BCryptDecrypt(
            key_handle,
            input_buffer,
            input_len,
            ctypes.byref(info),
            None,
            0,
            output_buffer,
            input_len,
            ctypes.byref(bytes_done),
            0,
        )
        _check(status, "BCryptDecrypt failed")
        return bytes(output_buffer[: bytes_done.value]).decode("utf-8")
    finally:
        _destroy_key(key_handle)
        _close_provider(alg_handle)
