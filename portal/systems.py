"""Custom EmulationStation systems: build, list, read, write and delete
es_systems_<slug>.cfg files, plus the reference catalogue read from
Batocera's own es_systems.cfg.
"""
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

from .util import confine, is_safe_slug, sanitize_conf_value

HARDWARE_TYPES = ["console", "portable", "computer", "arcade", "engine", "fantasy", "other"]

EXT_PRESETS = {
    "Common ROMs":        ".zip .7z .bin .rom",
    "Disc images":        ".cue .iso .chd .pbp .m3u",
    "Cartridge (NES/SNES)": ".nes .sfc .smc .zip .7z",
    "Mega Drive":         ".md .gen .bin .smd .zip .7z",
    "Game Boy family":    ".gb .gbc .gba .zip .7z",
    "Arcade":             ".zip .7z .chd",
    "Scripts / ports":    ".sh .AppImage",
    "Everything":         "*",
}

_CATALOGUE_CACHE = {"ts": 0.0, "path": None, "data": None}
CATALOGUE_TTL = 300


def prettify(elem):
    rough = ET.tostring(elem, encoding="unicode")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ")
    lines = [l for l in pretty.split("\n") if l.strip()]
    if lines and lines[0].startswith("<?xml"):
        lines = lines[1:]
    return "\n".join(lines)


def build_xml(d, settings):
    """Build the <systemList> document for one custom system."""
    root = ET.Element("systemList")
    sys_el = ET.SubElement(root, "system")

    def add(tag, val):
        if val is not None and str(val).strip():
            ET.SubElement(sys_el, tag).text = str(val).strip()

    add("fullname", d.get("fullname"))
    add("name", d.get("name"))
    add("manufacturer", d.get("manufacturer"))
    add("release", d.get("release"))
    add("hardware", d.get("hardware"))
    add("path", d.get("rompath"))
    add("extension", d.get("extensions"))
    command = (d.get("command") or "").strip()
    if not command:
        cg = settings.get("configgen_path", "")
        command = f"python3 {cg} %CONTROLLERSCONFIG% -system %SYSTEM% -rom %ROM%"
    ET.SubElement(sys_el, "command").text = command
    add("platform", d.get("platform"))
    add("theme", d.get("theme"))
    add("description", d.get("description"))

    emulator = (d.get("emulator") or "").strip()
    core = (d.get("core") or "").strip()
    if emulator:
        emuls = ET.SubElement(sys_el, "emulators")
        emu_el = ET.SubElement(emuls, "emulator", name=emulator)
        cores_el = ET.SubElement(emu_el, "cores")
        if core:
            c = ET.SubElement(cores_el, "core")
            c.text = core
            c.set("default", "true")
        for extra in (d.get("extra_cores") or "").split(","):
            extra = extra.strip()
            if extra and extra != core:
                ET.SubElement(cores_el, "core").text = extra
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + prettify(root) + "\n"


def _text(el, tag, default=""):
    child = el.find(tag)
    return (child.text or "").strip() if child is not None and child.text else default


def parse_system_element(sys_el):
    emulators = []
    emuls = sys_el.find("emulators")
    if emuls is not None:
        for emu in emuls.findall("emulator"):
            cores = []
            default_core = ""
            cores_el = emu.find("cores")
            if cores_el is not None:
                for c in cores_el.findall("core"):
                    name = (c.text or "").strip()
                    if not name:
                        continue
                    cores.append(name)
                    if c.get("default") == "true":
                        default_core = name
            emulators.append({"name": emu.get("name", ""), "cores": cores,
                              "default_core": default_core})
    return {
        "name":         _text(sys_el, "name"),
        "fullname":     _text(sys_el, "fullname"),
        "manufacturer": _text(sys_el, "manufacturer"),
        "release":      _text(sys_el, "release"),
        "hardware":     _text(sys_el, "hardware"),
        "path":         _text(sys_el, "path"),
        "extensions":   _text(sys_el, "extension"),
        "command":      _text(sys_el, "command"),
        "platform":     _text(sys_el, "platform"),
        "theme":        _text(sys_el, "theme"),
        "description":  _text(sys_el, "description"),
        "emulators":    emulators,
    }


def parse_systems_file(path):
    """Return a list of system dicts from any es_systems*.cfg."""
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError):
        return []
    root = tree.getroot()
    return [parse_system_element(s) for s in root.findall("system")]


def load_catalogue(settings, force=False):
    """Batocera's built-in systems, cached for CATALOGUE_TTL seconds."""
    path = settings.get("es_builtin_cfg", "")
    now = time.time()
    c = _CATALOGUE_CACHE
    if (not force and c["data"] is not None and c["path"] == path
            and now - c["ts"] < CATALOGUE_TTL):
        return c["data"]
    data = {}
    for s in parse_systems_file(path):
        if s["name"]:
            data[s["name"]] = s
    c.update({"ts": now, "path": path, "data": data})
    return data


def invalidate_catalogue():
    _CATALOGUE_CACHE["data"] = None


def cfg_path_for(settings, slug):
    return confine(settings["es_cfg_dir"], f"es_systems_{slug}.cfg")


def list_custom_systems(settings):
    out = []
    cfg_dir = Path(settings["es_cfg_dir"])
    if not cfg_dir.is_dir():
        return out
    for f in sorted(cfg_dir.glob("es_systems_*.cfg")):
        for s in parse_systems_file(f):
            s["file"] = str(f)
            s["slug_from_file"] = f.stem[len("es_systems_"):]
            try:
                st = f.stat()
                s["modified"] = int(st.st_mtime)
            except OSError:
                s["modified"] = 0
            rompath = s["path"]
            s["roms_dir_exists"] = bool(rompath) and os.path.isdir(rompath)
            out.append(s)
    return out


def get_custom_system(settings, slug):
    if not is_safe_slug(slug):
        return None
    p = cfg_path_for(settings, slug)
    if not p.exists():
        for s in list_custom_systems(settings):
            if s["name"] == slug:
                return s
        return None
    systems = parse_systems_file(p)
    if not systems:
        return None
    s = systems[0]
    s["file"] = str(p)
    s["xml"] = p.read_text(encoding="utf-8", errors="replace")
    return s


def validate_payload(d):
    errors = []
    slug = (d.get("name") or "").strip()
    if not (d.get("fullname") or "").strip():
        errors.append("Full name is required")
    if not slug:
        errors.append("Slug is required")
    elif not is_safe_slug(slug):
        errors.append("Slug may only contain lowercase letters, digits, '-' and '_'")
    if not (d.get("rompath") or "").strip():
        errors.append("ROM path is required")
    if not (d.get("extensions") or "").strip():
        errors.append("At least one extension is required")
    hw = (d.get("hardware") or "").strip()
    if hw and hw not in HARDWARE_TYPES:
        errors.append(f"Unknown hardware type: {hw}")
    return errors


def write_custom_system(settings, d, dry_run=False, old_slug=None):
    """Create or update a system. Returns (ok, result dict)."""
    errors = validate_payload(d)
    if old_slug is not None and not is_safe_slug(old_slug):
        errors.append("Original slug is invalid")
    if errors:
        return False, {"errors": errors}

    slug = d["name"].strip()
    log = []
    cfg_path = cfg_path_for(settings, slug)
    xml_str = build_xml(d, settings)

    if old_slug and old_slug != slug and cfg_path.exists():
        return False, {"errors": [f"A system named '{slug}' already exists"]}

    if dry_run:
        log.append(f"[dry run] Would write {cfg_path}")
        return True, {"log": log, "xml": xml_str, "cfg_path": str(cfg_path), "dry_run": True}

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(xml_str, encoding="utf-8")
    log.append(f"Wrote {cfg_path}")

    if old_slug and old_slug != slug:
        old_path = cfg_path_for(settings, old_slug)
        if old_path.exists():
            old_path.unlink()
            log.append(f"Removed old config {old_path}")
        removed = _remove_conf_lines(settings, old_slug)
        if removed:
            log.append(f"Removed {removed} stale line(s) for '{old_slug}' from batocera.conf")

    if d.get("create_roms_dir"):
        try:
            roms_dir = confine(settings["roms_base"], d["rompath"].strip()) \
                if not os.path.isabs(d["rompath"].strip()) else Path(d["rompath"].strip())
            if os.path.isabs(d["rompath"].strip()):
                confine(settings["roms_base"], os.path.relpath(roms_dir, settings["roms_base"]))
            roms_dir.mkdir(parents=True, exist_ok=True)
            log.append(f"ROM folder ready: {roms_dir}")
        except ValueError:
            log.append("ROM path is outside the ROM base folder; not created")
        except OSError as e:
            log.append(f"Could not create ROM folder: {e}")

    if d.get("batocera_conf_entry") and d.get("emulator"):
        try:
            emu = sanitize_conf_value(d.get("emulator"))
            lines = [f"\n# {d['fullname'].strip()} (Batocera Portal)\n", f"{slug}.emulator={emu}\n"]
            if (d.get("core") or "").strip():
                core = sanitize_conf_value(d.get("core"))
                lines.append(f"{slug}.core={core}\n")
            conf = Path(settings["batocera_conf"])
            conf.parent.mkdir(parents=True, exist_ok=True)
            with open(conf, "a", encoding="utf-8") as f:
                f.writelines(lines)
            log.append(f"Appended emulator settings to {conf}")
        except ValueError as e:
            log.append(str(e))
        except OSError as e:
            log.append(f"Could not update batocera.conf: {e}")

    log.append("Restart EmulationStation for the change to show up.")
    return True, {"log": log, "xml": xml_str, "cfg_path": str(cfg_path), "dry_run": False}


def _remove_conf_lines(settings, slug):
    """Drop <slug>.emulator= and <slug>.core= lines from batocera.conf."""
    conf = Path(settings["batocera_conf"])
    if not conf.exists():
        return 0
    kept = []
    removed = 0
    for line in conf.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith(f"{slug}.emulator=") or stripped.startswith(f"{slug}.core="):
            removed += 1
            continue
        kept.append(line)
    if removed:
        conf.write_text("".join(kept), encoding="utf-8")
    return removed


def delete_custom_system(settings, slug, remove_conf_entries=True):
    if not is_safe_slug(slug):
        return False, {"error": "Invalid slug"}
    p = cfg_path_for(settings, slug)
    if not p.exists():
        return False, {"error": "System not found"}
    log = []
    p.unlink()
    log.append(f"Deleted {p}")
    if remove_conf_entries:
        removed = _remove_conf_lines(settings, slug)
        if removed:
            log.append(f"Removed {removed} line(s) from batocera.conf")
    log.append("ROM files were left untouched.")
    return True, {"log": log}
