"""BIOS verification.

The authoritative BIOS list is the one Batocera ships in /usr/bin/batocera-systems.
We extract its `systems` dictionary with ast (no exec), then check each file under
the BIOS folder by MD5. A small bundled fallback keeps the feature alive off-device.
"""
import ast
import json
import re
import shutil
import ssl
import urllib.request
from pathlib import Path

from .util import confine, md5_file

BATOCERA_SYSTEMS_SCRIPT = "/usr/bin/batocera-systems"
MAX_BIOS_DOWNLOAD = 64 * 1024 * 1024

# Minimal fallback so the panel still works on a dev machine. Hashes are the
# commonly documented ones; the on-device list always wins when present.
FALLBACK_DB = {
    "atari5200": {"name": "Atari 5200", "biosFiles": [
        {"md5": "281f20ea4320404ec820fb7ec0693b38", "file": "bios/5200.rom"}]},
    "atari7800": {"name": "Atari 7800", "biosFiles": [
        {"md5": "0763f1ffb006ddbe32e52d497ee848ae", "file": "bios/7800 BIOS (U).rom"}]},
    "lynx": {"name": "Atari Lynx", "biosFiles": [
        {"md5": "fcd403db69f54290b51035d82f835e7b", "file": "bios/lynxboot.img"}]},
    "gba": {"name": "Game Boy Advance", "biosFiles": [
        {"md5": "a860e8c0b6d573d191e4ec7db1b1e4f6", "file": "bios/gba_bios.bin"}]},
    "psx": {"name": "PlayStation", "biosFiles": [
        {"md5": "924e392ed05558ffdb115408c263dccf", "file": "bios/scph1001.bin"},
        {"md5": "8dd7d5296a650fac7319bce665a6a53c", "file": "bios/scph5500.bin"},
        {"md5": "490f666e1afb15b7362b406ed1cea246", "file": "bios/scph5501.bin"},
        {"md5": "32736f17079d0b2b7024407c39bd3050", "file": "bios/scph5502.bin"}]},
    "segacd": {"name": "Sega CD", "biosFiles": [
        {"md5": "e66fa1dc5820d254611fdcdba0662372", "file": "bios/bios_CD_E.bin"},
        {"md5": "854b9150240a198070150e4566ae1290", "file": "bios/bios_CD_U.bin"},
        {"md5": "278a9397d192149e84e820ac621a8edd", "file": "bios/bios_CD_J.bin"}]},
    "saturn": {"name": "Sega Saturn", "biosFiles": [
        {"md5": "af5828fdff51384f99b3c4926be27762", "file": "bios/saturn_bios.bin"}]},
    "dreamcast": {"name": "Dreamcast", "biosFiles": [
        {"md5": "e10c53c2f8b90bab96ead2d368858623", "file": "bios/dc_boot.bin"},
        {"md5": "0a93f7940c455905bea6e392dfde92a4", "file": "bios/dc_flash.bin"}]},
    "neogeo": {"name": "Neo Geo", "biosFiles": [
        {"md5": "", "file": "bios/neogeo.zip"}]},
    "pcengine": {"name": "PC Engine CD", "biosFiles": [
        {"md5": "38179df8f4ac870017db21ebcbf53114", "file": "bios/syscard3.pce"}]},
    "fds": {"name": "Famicom Disk System", "biosFiles": [
        {"md5": "ca30b50f880eb660a320674ed365ef7a", "file": "bios/disksys.rom"}]},
}

_DB_CACHE = {"source": None, "data": None}


def _extract_dict_literal(text, name):
    """Find `name = {` in text and return the balanced dict source."""
    m = re.search(rf"^\s*{re.escape(name)}\s*=\s*\{{", text, re.M)
    if not m:
        return None
    start = m.end() - 1
    depth = 0
    in_str = None
    esc = False
    i = start
    while i < len(text):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == in_str:
                in_str = None
        else:
            if ch in ("'", '"'):
                in_str = ch
            elif ch == "#":
                nl = text.find("\n", i)
                i = len(text) if nl == -1 else nl
                continue
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        i += 1
    return None


def load_bios_db(script_path=BATOCERA_SYSTEMS_SCRIPT, force=False):
    """Return (db, source). db = {slug: {"name", "biosFiles": [{"md5","file"}]}}"""
    if not force and _DB_CACHE["data"] is not None:
        return _DB_CACHE["data"], _DB_CACHE["source"]
    db, source = None, "fallback"
    p = Path(script_path)
    if p.exists():
        text = p.read_text(encoding="utf-8", errors="replace")
        literal = _extract_dict_literal(text, "systems")
        if literal:
            try:
                parsed = ast.literal_eval(literal)
                if isinstance(parsed, dict) and parsed:
                    db, source = parsed, str(p)
            except (ValueError, SyntaxError):
                db = None
    if db is None:
        db = FALLBACK_DB
    _DB_CACHE.update({"data": db, "source": source})
    return db, source


def _skip_file(settings):
    return Path(settings["bios_dir"]) / ".portal_bios_skipped.json"


def load_skipped(settings):
    p = _skip_file(settings)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return set(data) if isinstance(data, list) else set()
        except (OSError, ValueError):
            return set()
    return set()


def save_skipped(settings, skipped):
    p = _skip_file(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sorted(skipped), indent=2), encoding="utf-8")


def set_skipped(settings, key, skipped=True):
    s = load_skipped(settings)
    if skipped:
        s.add(key)
    else:
        s.discard(key)
    save_skipped(settings, s)
    return sorted(s)


def _resolve_bios_path(settings, rel_file):
    """DB entries look like 'bios/foo.bin' relative to /userdata."""
    rel = rel_file
    if rel.startswith("bios/"):
        rel = rel[len("bios/"):]
    return Path(settings["bios_dir"]) / rel


def check_entry(settings, entry):
    rel = entry.get("file", "")
    expected = (entry.get("md5") or "").lower().strip()
    expected_list = [m.strip() for m in expected.split(",") if m.strip()] if expected else []
    path = _resolve_bios_path(settings, rel)
    if not path.exists():
        return {"file": rel, "status": "missing", "path": str(path), "md5": None,
                "expected": expected_list, "optional": not expected_list}
    if not expected_list:
        return {"file": rel, "status": "ok", "path": str(path), "md5": None,
                "expected": [], "optional": True}
    try:
        actual = md5_file(path)
    except OSError:
        return {"file": rel, "status": "unreadable", "path": str(path), "md5": None,
                "expected": expected_list, "optional": False}
    return {"file": rel, "status": "ok" if actual in expected_list else "mismatch",
            "path": str(path), "md5": actual, "expected": expected_list, "optional": False}


def check_all(settings, only_slugs=None):
    """Check every system in the DB (or only the given slugs)."""
    db, source = load_bios_db()
    skipped = load_skipped(settings)
    results = []
    for slug, info in sorted(db.items()):
        if only_slugs is not None and slug not in only_slugs:
            continue
        files = []
        for entry in info.get("biosFiles", []):
            r = check_entry(settings, entry)
            r["key"] = f"{slug}:{r['file']}"
            r["skipped"] = r["key"] in skipped
            files.append(r)
        missing = [f for f in files if f["status"] == "missing" and not f["skipped"]]
        bad = [f for f in files if f["status"] in ("mismatch", "unreadable") and not f["skipped"]]
        results.append({"slug": slug, "name": info.get("name", slug), "files": files,
                        "total": len(files), "missing": len(missing), "mismatch": len(bad),
                        "complete": not missing and not bad})
    return {"source": source, "systems": results,
            "summary": {"systems": len(results),
                        "complete": sum(1 for r in results if r["complete"]),
                        "missing_files": sum(r["missing"] for r in results),
                        "mismatched_files": sum(r["mismatch"] for r in results)}}


def missing_for_installed(settings, installed_slugs):
    """Missing BIOS for systems that actually have a ROM folder."""
    data = check_all(settings, only_slugs=set(installed_slugs))
    data["systems"] = [s for s in data["systems"] if not s["complete"]]
    return data


def save_uploaded_bios(settings, rel_file, data):
    """Store an uploaded BIOS at the path the DB expects; verify md5 if known."""
    if not rel_file or ".." in rel_file.split("/"):
        return False, {"error": "Invalid BIOS path"}
    dest = confine(settings["bios_dir"], rel_file[5:] if rel_file.startswith("bios/") else rel_file)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    db, _ = load_bios_db()
    expected = []
    for info in db.values():
        for entry in info.get("biosFiles", []):
            if entry.get("file") == rel_file and entry.get("md5"):
                expected = [m.strip().lower() for m in entry["md5"].split(",")]
    actual = md5_file(dest)
    verified = (actual in expected) if expected else None
    return True, {"path": str(dest), "md5": actual, "verified": verified, "expected": expected}


def download_bios(settings, rel_file, url, timeout=30):
    """Fetch a BIOS from a user-supplied URL and verify it against the DB."""
    if not url.lower().startswith(("http://", "https://")):
        return False, {"error": "URL must start with http:// or https://"}
    req = urllib.request.Request(url, headers={"User-Agent": "BatoceraPortal"})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            length = r.headers.get("Content-Length")
            if length and int(length) > MAX_BIOS_DOWNLOAD:
                return False, {"error": "File is larger than the 64 MB limit"}
            data = r.read(MAX_BIOS_DOWNLOAD + 1)
    except Exception as e:  # network errors of any kind
        return False, {"error": f"Download failed: {e}"}
    if len(data) > MAX_BIOS_DOWNLOAD:
        return False, {"error": "File is larger than the 64 MB limit"}
    ok, info = save_uploaded_bios(settings, rel_file, data)
    if ok and info.get("verified") is False:
        Path(info["path"]).unlink(missing_ok=True)
        return False, {"error": "Downloaded file did not match the expected MD5; discarded",
                       "md5": info["md5"], "expected": info["expected"]}
    return ok, info


def bios_folder_listing(settings):
    root = Path(settings["bios_dir"])
    if not root.is_dir():
        return {"exists": False, "files": [], "free": None}
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            try:
                files.append({"rel": str(p.relative_to(root)), "size": p.stat().st_size})
            except OSError:
                pass
    try:
        free = shutil.disk_usage(root).free
    except OSError:
        free = None
    return {"exists": True, "files": files, "free": free}
