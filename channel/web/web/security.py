import hashlib
import hmac
import secrets
import time


HASH_PREFIX = "pbkdf2_sha256"
ITERATIONS = 260_000


def hash_password(password: str) -> str:
    password = str(password or "")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), ITERATIONS)
    return f"{HASH_PREFIX}${ITERATIONS}${salt}${digest.hex()}"


def is_hashed_password(value: str) -> bool:
    return str(value or "").startswith(f"{HASH_PREFIX}$")


def verify_password(password: str, stored: str) -> bool:
    stored = str(stored or "")
    password = str(password or "")
    if not stored:
        return False
    if not is_hashed_password(stored):
        return hmac.compare_digest(password, stored)
    try:
        _prefix, iterations, salt, expected = stored.split("$", 3)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("ascii"),
            int(iterations),
        ).hex()
    except Exception:
        return False
    return hmac.compare_digest(digest, expected)


def signing_secret(stored_password: str) -> bytes:
    stored = str(stored_password or "")
    if is_hashed_password(stored):
        return stored.encode("utf-8")
    return hashlib.sha256(stored.encode("utf-8")).hexdigest().encode("ascii")


def create_session_token(stored_password: str) -> str:
    ts = format(int(time.time()), "x")
    nonce = secrets.token_hex(16)
    body = f"{ts}.{nonce}"
    sig = hmac.new(signing_secret(stored_password), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_session_token(token: str, stored_password: str, max_age_seconds: int) -> bool:
    if not token:
        return False
    parts = str(token).split(".")
    if len(parts) == 2:
        ts_hex, sig = parts
        body = ts_hex
    elif len(parts) == 3:
        ts_hex, _nonce, sig = parts
        body = ".".join(parts[:2])
    else:
        return False
    try:
        ts = int(ts_hex, 16)
    except ValueError:
        return False
    if time.time() - ts > max_age_seconds:
        return False
    expected = hmac.new(signing_secret(stored_password), body.encode("ascii"), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        return True
    if len(parts) == 2 and not is_hashed_password(stored_password):
        legacy = hmac.new(str(stored_password or "").encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, legacy)
    return False
