"""Password protection: login sessions, HTTP Basic for scripts, lockout.

The password is stored as a salted PBKDF2-SHA256 hash in the settings file.
Until a password has been set, the default password applies.
"""
import base64
import hashlib
import hmac
import secrets
import threading
import time

from .config import load_settings, save_settings

DEFAULT_PASSWORD = "linuxrox"
COOKIE_NAME = "bp_session"
SESSION_TTL = 7 * 24 * 3600          # a week of inactivity
MAX_FAILURES = 5
LOCKOUT_SECONDS = 30
PBKDF2_ROUNDS = 200_000

_sessions = {}      # token -> expiry
_failures = {}      # ip -> [count, locked_until]
_lock = threading.Lock()


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt),
                                 PBKDF2_ROUNDS).hex()
    return digest, salt


def password_is_default(settings=None):
    settings = settings or load_settings()
    return not settings.get("password_hash")


def verify_password(password, settings=None):
    settings = settings or load_settings()
    password = password or ""
    stored = settings.get("password_hash") or ""
    if stored:
        digest, _ = hash_password(password, settings.get("password_salt") or "00")
        return hmac.compare_digest(digest, stored)
    return hmac.compare_digest(password, DEFAULT_PASSWORD)


def set_password(new_password):
    if not new_password or len(new_password) < 4:
        return False, "Password must be at least 4 characters"
    if len(new_password) > 128:
        return False, "Password is too long"
    digest, salt = hash_password(new_password)
    save_settings({"password_hash": digest, "password_salt": salt},
                  allow=("password_hash", "password_salt"))
    with _lock:
        _sessions.clear()        # every browser must log in again
    return True, None


# ------------------------------------------------------------------ sessions
def create_session():
    token = secrets.token_urlsafe(32)
    with _lock:
        now = time.time()
        for t, exp in list(_sessions.items()):
            if exp < now:
                del _sessions[t]
        _sessions[token] = now + SESSION_TTL
    return token


def session_valid(token):
    if not token:
        return False
    with _lock:
        exp = _sessions.get(token)
        if not exp or exp < time.time():
            _sessions.pop(token, None)
            return False
        _sessions[token] = time.time() + SESSION_TTL
        return True


def destroy_session(token):
    with _lock:
        _sessions.pop(token, None)


def session_count():
    with _lock:
        return len(_sessions)


# ------------------------------------------------------------------ lockout
def locked_for(ip):
    """Seconds remaining in the lockout for this IP, or 0."""
    with _lock:
        entry = _failures.get(ip)
        if not entry:
            return 0
        remaining = entry[1] - time.time()
        return int(remaining) + 1 if remaining > 0 else 0


def record_failure(ip):
    with _lock:
        count, _ = _failures.get(ip, [0, 0])
        count += 1
        until = time.time() + LOCKOUT_SECONDS if count >= MAX_FAILURES else 0
        if count >= MAX_FAILURES:
            count = 0
        _failures[ip] = [count, until]


def clear_failures(ip):
    with _lock:
        _failures.pop(ip, None)


# ------------------------------------------------------------------ headers
def parse_cookies(header):
    out = {}
    for part in (header or "").split(";"):
        if "=" in part:
            k, _, v = part.strip().partition("=")
            out[k] = v
    return out


def basic_auth_password(header):
    """Return the password from an 'Authorization: Basic' header, or None."""
    if not header or not header.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(header.split(None, 1)[1].strip()).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    return raw.partition(":")[2] if ":" in raw else raw


def authenticate(headers, settings=None):
    """True if the request carries a valid session cookie or Basic password."""
    cookies = parse_cookies(headers.get("Cookie"))
    if session_valid(cookies.get(COOKIE_NAME)):
        return True
    pw = basic_auth_password(headers.get("Authorization"))
    if pw is not None and verify_password(pw, settings):
        return True
    return False


def set_cookie_header(token):
    return f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL}"


def clear_cookie_header():
    return f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
