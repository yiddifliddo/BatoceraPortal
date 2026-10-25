"""Shared helpers: safe paths, hashing, formatting, multipart parsing."""
import hashlib
import os
import re
import zlib
from email.parser import BytesParser
from email.policy import default as _email_policy
from pathlib import Path

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ +()\[\]!&',-]*$")
_SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_CONF_VALUE = re.compile(r"^[A-Za-z0-9._+-]+$")


def is_safe_slug(name):
    """System slugs become file names and conf keys: keep them strict."""
    return bool(name) and bool(_SAFE_SLUG.match(name))


def is_safe_component(name):
    """A single path component: no separators, no traversal."""
    if not name or name in (".", ".."):
        return False
    if "/" in name or "\\" in name or "\x00" in name:
        return False
    return bool(_SAFE_COMPONENT.match(name))


def confine(base, *parts):
    """Join parts under base and refuse anything that escapes it."""
    base_p = Path(base).resolve()
    target = (base_p.joinpath(*[str(p).lstrip("/") for p in parts])).resolve()
    if target != base_p and base_p not in target.parents:
        raise ValueError(f"Path escapes {base}")
    return target


def sanitize_conf_value(value):
    v = (value or "").strip()
    if not _CONF_VALUE.match(v):
        raise ValueError(f"Invalid value for batocera.conf: {v!r}")
    return v


def md5_file(path, chunk=1 << 20):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def crc32_file(path, chunk=1 << 20):
    c = 0
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            c = zlib.crc32(block, c)
    return f"{c & 0xFFFFFFFF:08x}"


def human_size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def read_text(path, default=""):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return default


def parse_multipart(content_type, body):
    """Parse a multipart/form-data body with the stdlib email parser.

    Returns {"fields": {name: str}, "files": [{"name", "filename", "data"}]}.
    """
    if not content_type or "multipart/form-data" not in content_type:
        raise ValueError("Expected multipart/form-data")
    raw = (b"Content-Type: " + content_type.encode("latin-1") +
           b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    msg = BytesParser(policy=_email_policy).parsebytes(raw)
    out = {"fields": {}, "files": []}
    if not msg.is_multipart():
        return out
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            out["files"].append({"name": name, "filename": os.path.basename(filename),
                                 "data": payload})
        elif name:
            out["fields"][name] = payload.decode("utf-8", errors="replace")
    return out
