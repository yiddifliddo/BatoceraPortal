"""Theme listing, active theme detection and system logo uploads."""
import io
import re
from pathlib import Path

from .util import confine, is_safe_slug

try:
    from PIL import Image, ImageDraw  # optional
    HAS_PIL = True
except Exception:  # pragma: no cover - depends on host
    HAS_PIL = False

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


def detect_active_theme(settings):
    """ES stores the theme in es_settings.cfg; batocera.conf may override."""
    es_settings = Path(settings["es_cfg_dir"]) / "es_settings.cfg"
    if es_settings.exists():
        m = re.search(r'name="ThemeSet"\s+value="([^"]+)"',
                      es_settings.read_text(encoding="utf-8", errors="replace"))
        if m:
            return m.group(1)
    conf = Path(settings["batocera_conf"])
    if conf.exists():
        for line in conf.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("global.theme="):
                return line.split("=", 1)[1].strip()
    return "es-theme-carbon"


def list_themes(settings):
    out = []
    seen = set()
    for key, origin in (("themes_user", "user"), ("themes_sys", "system")):
        root = Path(settings.get(key, ""))
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir()):
            if d.is_dir() and not d.name.startswith(".") and d.name not in seen:
                seen.add(d.name)
                out.append({"name": d.name, "path": str(d), "origin": origin,
                            "has_theme_xml": (d / "theme.xml").exists()})
    return out


def theme_dir(settings, theme):
    for key in ("themes_user", "themes_sys"):
        root = Path(settings.get(key, ""))
        if root.is_dir():
            try:
                candidate = confine(root, theme)
            except ValueError:
                continue
            if candidate.is_dir():
                return candidate
    return None


def find_system_logo(settings, slug, theme=None):
    """Look for a logo in the places Batocera themes usually keep them."""
    theme = theme or detect_active_theme(settings)
    tdir = theme_dir(settings, theme)
    if not tdir or not is_safe_slug(slug):
        return None
    candidates = [
        tdir / slug / "art" / "logo.png",
        tdir / slug / "art" / "logo.svg",
        tdir / "art" / "logos" / f"{slug}.png",
        tdir / "art" / "logos" / f"{slug}.svg",
        tdir / "_inc" / "systems" / slug / "logo.svg",
        tdir / "_inc" / "systems" / slug / "logo.png",
        tdir / "_inc" / "systems" / "logos" / f"{slug}.svg",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def validate_image_bytes(data):
    if data.startswith(_PNG_MAGIC):
        return "png"
    if data.startswith(_JPEG_MAGIC):
        return "jpg"
    if data.lstrip()[:5].lower() in (b"<svg ", b"<?xml"):
        return "svg"
    return None


def save_system_logo(settings, slug, data, theme=None):
    """Write the logo to <theme>/<slug>/art/logo.<ext>. Returns (ok, info)."""
    if not is_safe_slug(slug):
        return False, {"error": "Invalid system slug"}
    kind = validate_image_bytes(data)
    if not kind:
        return False, {"error": "Only PNG, JPEG or SVG files are accepted"}
    theme = theme or detect_active_theme(settings)
    user_root = Path(settings["themes_user"])
    tdir = theme_dir(settings, theme)
    if tdir is None:
        return False, {"error": f"Theme '{theme}' not found"}
    if user_root not in tdir.parents and tdir != user_root:
        return False, {"error": "Logos can only be written into themes under the user theme folder"}
    dest_dir = confine(tdir, slug, "art")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"logo.{kind}"
    dest.write_bytes(data)
    return True, {"path": str(dest), "theme": theme}


def make_placeholder_png(text):
    """A plain placeholder logo; only works when Pillow is available."""
    if not HAS_PIL:
        return None
    img = Image.new("RGBA", (400, 160), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((4, 4, 396, 156), radius=18, fill=(40, 44, 60, 255))
    draw.text((24, 60), (text or "SYSTEM")[:24].upper(), fill=(240, 240, 240, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
