"""Settings handling: defaults, load and save.

All filesystem roots are kept in the settings dict so that every module can be
pointed at a temporary directory in tests.
"""
import json
import os
import shutil
from pathlib import Path

_DEFAULT_SETTINGS_FILE = "/userdata/system/batocera_portal_settings.json"


def settings_file():
    """Settings path, overridable with BP_SETTINGS for tests and dev."""
    return Path(os.environ.get("BP_SETTINGS", _DEFAULT_SETTINGS_FILE))


def detect_configgen_path():
    """Locate Batocera's emulatorlauncher, used in the <command> of es_systems."""
    candidates = [
        "/usr/lib/python3.12/site-packages/configgen/emulatorlauncher.py",
        "/usr/lib/python3.11/site-packages/configgen/emulatorlauncher.py",
        "/usr/lib/python3.13/site-packages/configgen/emulatorlauncher.py",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    for p in Path("/usr/lib").glob("python3*/site-packages/configgen/emulatorlauncher.py"):
        return str(p)
    return candidates[0]


def default_settings():
    base = os.environ.get("BP_BASE_DIR", "/userdata")
    return {
        "es_cfg_dir":     f"{base}/system/configs/emulationstation",
        "es_builtin_cfg": "/usr/share/emulationstation/es_systems.cfg",
        "roms_base":      f"{base}/roms",
        "bios_dir":       f"{base}/bios",
        "themes_user":    f"{base}/themes",
        "themes_sys":     "/usr/share/emulationstation/themes",
        "batocera_conf":  f"{base}/system/batocera.conf",
        "custom_sh":      f"{base}/system/custom.sh",
        "configgen_path": detect_configgen_path(),
        "app_path":       f"{base}/system/batocera_portal/app.py",
        "server_port":    5000,
        "ra_user":        "",
        "ra_api_key":     "",
        "password_hash":  "",
        "password_salt":  "",
    }


# Keys the UI may change through POST /api/settings.
EDITABLE_KEYS = (
    "es_cfg_dir", "roms_base", "bios_dir", "themes_user", "themes_sys",
    "batocera_conf", "custom_sh", "configgen_path", "server_port",
    "ra_user", "ra_api_key",
)


def load_settings():
    s = default_settings()
    p = settings_file()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                s.update({k: v for k, v in data.items() if k in s})
        except (OSError, ValueError):
            pass
    try:
        s["server_port"] = int(s["server_port"])
    except (TypeError, ValueError):
        s["server_port"] = 5000
    return s


# Keys that must never be reported back to the browser.
SECRET_KEYS = ("password_hash", "password_salt")


def public_settings(settings):
    out = {k: v for k, v in settings.items() if k not in SECRET_KEYS}
    out["ra_api_key"] = "********" if settings.get("ra_api_key") else ""
    out["password_is_default"] = not settings.get("password_hash")
    return out


def save_settings(updates, allow=()):
    """Merge editable keys into the settings file and return the new settings.

    `allow` names extra keys this particular caller may write (used for the
    password hash, which the generic settings endpoint must not touch).
    """
    current = load_settings()
    for k, v in (updates or {}).items():
        if k in EDITABLE_KEYS or k in allow:
            current[k] = v
    p = settings_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
    shutil.move(str(tmp), str(p))
    return current
