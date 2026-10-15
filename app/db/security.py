import hashlib
import hmac
import os

ITERACIONES = 200_000


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERACIONES)
    return digest.hex(), salt.hex()


def verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
    nuevo, _ = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(nuevo, hash_hex)
