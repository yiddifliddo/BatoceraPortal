"""ROM inventory, gamelist.xml access, play statistics and random game picks."""
import os
import random
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from xml.dom import minidom

from .systems import list_custom_systems, load_catalogue
from .util import confine, human_size, is_safe_component, is_safe_slug

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
IGNORED_FILES = {"gamelist.xml", "gamelist.xml.bak", "_info.txt", "readme.txt", ".DS_Store",
                 "Thumbs.db"}
IGNORED_DIRS = {"images", "videos", "manuals", "media", "downloaded_images", "boxart",
                "marquees", "screenshots", "wheel", "fanart", "thumbnails", "music", "mix"}

_ROM_CACHE = {"ts": 0.0, "key": None, "data": None}
ROM_TTL = 60

# EmulationStation media naming: images/<rom>-<suffix>.<ext>
MEDIA_SUFFIX = {
    "image": "image", "thumbnail": "thumb", "marquee": "marquee", "box": "box",
    "box3d": "box3d", "wheel": "wheel", "fanart": "fanart", "screenshot": "image",
    "titleshot": "titleshot", "mix": "mix", "cartridge": "cartridge", "map": "map",
    "manual": "manual", "video": "video", "bezel": "bezel", "boxback": "boxback",
}
GAMELIST_TAG_FOR_MEDIA = {
    "image": "image", "screenshot": "image", "thumbnail": "thumbnail", "marquee": "marquee",
    "box": "thumbnail", "box3d": "boxart", "wheel": "wheel", "fanart": "fanart",
    "titleshot": "titleshot", "mix": "image", "cartridge": "cartridge", "map": "map",
    "manual": "manual", "video": "video", "bezel": "bezel", "boxback": "boxback",
}


def media_path(system_dir, rom_stem, media_type, ext=".png"):
    suffix = MEDIA_SUFFIX.get(media_type, media_type)
    folder = "videos" if media_type == "video" else ("manuals" if media_type == "manual" else "images")
    return Path(system_dir) / folder / f"{rom_stem}-{suffix}{ext}"


def _ext_set(extensions):
    exts = set()
    for e in (extensions or "").replace(",", " ").split():
        e = e.strip().lower()
        if not e:
            continue
        if e == "*":
            return {"*"}
        exts.add(e if e.startswith(".") else "." + e)
    return exts


def known_systems(settings):
    """Slug -> system dict from the built-in catalogue plus custom systems."""
    out = dict(load_catalogue(settings))
    for s in list_custom_systems(settings):
        if s["name"]:
            out[s["name"]] = s
    return out


def rom_dir(settings, slug):
    if not is_safe_slug(slug):
        raise ValueError("Invalid system slug")
    return confine(settings["roms_base"], slug)


def parse_gamelist(path):
    """Return {rom_relpath: {field: value}} for a gamelist.xml."""
    games = {}
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError):
        return games
    for g in tree.getroot().findall("game"):
        p = g.findtext("path") or ""
        rel = p[2:] if p.startswith("./") else p
        if not rel:
            continue
        entry = {child.tag: (child.text or "").strip() for child in g}
        games[rel] = entry
    return games


def _count_roms(system_dir, exts, limit_files=None):
    count = 0
    size = 0
    subdirs = 0
    found_exts = {}
    for root, dirs, files in os.walk(system_dir):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
        if root != str(system_dir):
            subdirs += 1
        for f in files:
            if f in IGNORED_FILES or f.startswith("."):
                continue
            ext = os.path.splitext(f)[1].lower()
            if "*" in exts or ext in exts:
                count += 1
                found_exts[ext] = found_exts.get(ext, 0) + 1
                try:
                    size += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    return count, size, subdirs, found_exts


def scan_rom_systems(settings):
    base = Path(settings["roms_base"])
    if not base.is_dir():
        return []
    systems = known_systems(settings)
    out = []
    for d in sorted(base.iterdir()):
        if not d.is_dir() or d.name.startswith(".") or d.name in IGNORED_DIRS:
            continue
        meta = systems.get(d.name, {})
        exts = _ext_set(meta.get("extensions")) or {"*"}
        count, size, subdirs, found = _count_roms(d, exts)
        gl = d / "gamelist.xml"
        games = parse_gamelist(gl) if gl.exists() else {}
        out.append({
            "slug": d.name,
            "fullname": meta.get("fullname") or d.name,
            "manufacturer": meta.get("manufacturer", ""),
            "hardware": meta.get("hardware", "") or "other",
            "release": meta.get("release", ""),
            "known": d.name in systems,
            "custom": bool(meta.get("file")),
            "rom_count": count,
            "size": size,
            "size_h": human_size(size),
            "subdirs": subdirs,
            "extensions": sorted(found.keys()),
            "gamelist_entries": len(games),
            "has_gamelist": gl.exists(),
        })
    return out


def rom_systems_cached(settings, force=False):
    now = time.time()
    key = settings["roms_base"]
    c = _ROM_CACHE
    if not force and c["data"] is not None and c["key"] == key and now - c["ts"] < ROM_TTL:
        return c["data"]
    data = scan_rom_systems(settings)
    c.update({"ts": now, "key": key, "data": data})
    return data


def invalidate_rom_cache():
    _ROM_CACHE["data"] = None


def list_rom_folder(settings, slug, subpath=""):
    """Files and folders for one system, merged with gamelist metadata."""
    sdir = rom_dir(settings, slug)
    folder = confine(sdir, subpath) if subpath else sdir
    if not folder.is_dir():
        return None
    meta = known_systems(settings).get(slug, {})
    exts = _ext_set(meta.get("extensions")) or {"*"}
    games = parse_gamelist(sdir / "gamelist.xml")
    entries = []
    for p in sorted(folder.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if p.name.startswith(".") or p.name in IGNORED_FILES:
            continue
        rel = str(p.relative_to(sdir))
        if p.is_dir():
            if p.name in IGNORED_DIRS:
                continue
            entries.append({"name": p.name, "rel": rel, "is_dir": True})
            continue
        ext = p.suffix.lower()
        if "*" not in exts and ext not in exts:
            continue
        g = games.get(rel, {})
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        entries.append({
            "name": p.name, "rel": rel, "is_dir": False, "size": size, "size_h": human_size(size),
            "title": g.get("name", ""), "desc": g.get("desc", ""), "genre": g.get("genre", ""),
            "developer": g.get("developer", ""), "publisher": g.get("publisher", ""),
            "players": g.get("players", ""), "rating": g.get("rating", ""),
            "releasedate": g.get("releasedate", ""), "playcount": g.get("playcount", ""),
            "lastplayed": g.get("lastplayed", ""), "gametime": g.get("gametime", ""),
            "image": g.get("image", ""), "has_image": bool(find_image(sdir, rel, g)),
            "favorite": g.get("favorite", "") == "true", "hidden": g.get("hidden", "") == "true",
        })
    return {"slug": slug, "subpath": subpath, "entries": entries, "fullname": meta.get("fullname", slug)}


def find_image(system_dir, rom_rel, game_meta=None):
    system_dir = Path(system_dir)
    if game_meta and game_meta.get("image"):
        img = game_meta["image"]
        candidate = system_dir / (img[2:] if img.startswith("./") else img)
        if candidate.exists():
            return str(candidate)
    stem = Path(rom_rel).stem
    for suffix in ("image", "box", "mix", "thumb", "wheel", "marquee", "fanart"):
        for ext in IMAGE_EXTS:
            c = system_dir / "images" / f"{stem}-{suffix}{ext}"
            if c.exists():
                return str(c)
    return None


def image_info(settings, slug, rom_rel):
    sdir = rom_dir(settings, slug)
    rel = str(confine(sdir, rom_rel).relative_to(sdir))
    games = parse_gamelist(sdir / "gamelist.xml")
    out = []
    stem = Path(rel).stem
    for media_type, suffix in MEDIA_SUFFIX.items():
        if media_type in ("screenshot", "mix"):
            continue
        folder = "videos" if media_type == "video" else ("manuals" if media_type == "manual" else "images")
        for p in (sdir / folder).glob(f"{stem}-{suffix}.*"):
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            out.append({"type": media_type, "path": str(p), "rel": str(p.relative_to(sdir)),
                        "size": size, "size_h": human_size(size)})
    return {"rom": rel, "gamelist": games.get(rel, {}), "media": out,
            "primary": find_image(sdir, rel, games.get(rel))}


def _parse_es_date(value):
    if not value:
        return None
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(value[:15], fmt)
        except ValueError:
            continue
    return None


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def play_stats(settings, top=10):
    base = Path(settings["roms_base"])
    plays = 0
    seconds = 0
    games = []
    last = None
    if base.is_dir():
        for d in base.iterdir():
            gl = d / "gamelist.xml"
            if not d.is_dir() or not gl.exists():
                continue
            for rel, g in parse_gamelist(gl).items():
                pc = _int(g.get("playcount"))
                gt = _int(g.get("gametime"))
                lp = _parse_es_date(g.get("lastplayed"))
                if pc or gt:
                    plays += pc
                    seconds += gt
                    games.append({"system": d.name, "rom": rel, "title": g.get("name") or Path(rel).stem,
                                  "playcount": pc, "gametime": gt,
                                  "gametime_h": f"{gt // 3600}h {(gt % 3600) // 60}m",
                                  "lastplayed": lp.isoformat() if lp else None})
                if lp and (last is None or lp > last["dt"]):
                    last = {"dt": lp, "system": d.name, "title": g.get("name") or Path(rel).stem}
    games.sort(key=lambda x: (x["gametime"], x["playcount"]), reverse=True)
    return {"total_plays": plays, "total_seconds": seconds,
            "total_hours": round(seconds / 3600, 1), "top": games[:top],
            "last_played": {"system": last["system"], "title": last["title"],
                            "when": last["dt"].isoformat()} if last else None}


def random_game(settings, attempts=40):
    systems = [s for s in rom_systems_cached(settings) if s["rom_count"] > 0]
    if not systems:
        return None
    for _ in range(attempts):
        system = random.choice(systems)
        sdir = Path(settings["roms_base"]) / system["slug"]
        games = parse_gamelist(sdir / "gamelist.xml")
        candidates = [(rel, g) for rel, g in games.items()
                      if g.get("hidden") != "true" and (sdir / rel).exists()]
        if not candidates:
            continue
        rel, g = random.choice(candidates)
        return {
            "system": system["slug"], "system_name": system["fullname"], "rom": rel,
            "title": g.get("name") or Path(rel).stem, "desc": g.get("desc", ""),
            "genre": g.get("genre", ""), "developer": g.get("developer", ""),
            "publisher": g.get("publisher", ""), "players": g.get("players", ""),
            "rating": g.get("rating", ""), "releasedate": g.get("releasedate", ""),
            "image": f"/api/roms/{system['slug']}/image?rom={rel}" if find_image(sdir, rel, g) else None,
        }
    return None


def rename_rom(settings, slug, rom_rel, new_name):
    sdir = rom_dir(settings, slug)
    src = confine(sdir, rom_rel)
    if not src.is_file():
        return False, {"error": "ROM not found"}
    if not is_safe_component(new_name):
        return False, {"error": "Invalid new file name"}
    dst = src.with_name(new_name)
    if dst.exists():
        return False, {"error": "A file with that name already exists"}
    src.rename(dst)
    old_rel = str(src.relative_to(sdir))
    new_rel = str(dst.relative_to(sdir))
    _rewrite_gamelist_path(sdir, old_rel, new_rel)
    invalidate_rom_cache()
    return True, {"old": old_rel, "new": new_rel}


def _write_gamelist(gl_path, root):
    rough = ET.tostring(root, encoding="unicode")
    pretty = minidom.parseString(rough).toprettyxml(indent="\t")
    lines = [l for l in pretty.split("\n") if l.strip()]
    if lines and lines[0].startswith("<?xml"):
        lines = lines[1:]
    gl_path.write_text('<?xml version="1.0"?>\n' + "\n".join(lines) + "\n", encoding="utf-8")


def _load_or_create_gamelist(sdir):
    gl_path = Path(sdir) / "gamelist.xml"
    if gl_path.exists():
        try:
            tree = ET.parse(gl_path)
            root = tree.getroot()
            # strip indentation whitespace so re-prettifying stays clean
            for el in root.iter():
                if el.text is not None and not el.text.strip():
                    el.text = None
                if el.tail is not None and not el.tail.strip():
                    el.tail = None
            return gl_path, root
        except ET.ParseError:
            gl_path.rename(gl_path.with_suffix(".xml.broken"))
    return gl_path, ET.Element("gameList")


def _find_game(root, rel):
    for g in root.findall("game"):
        p = g.findtext("path") or ""
        if p == f"./{rel}" or p == rel:
            return g
    return None


def _rewrite_gamelist_path(sdir, old_rel, new_rel):
    gl_path = Path(sdir) / "gamelist.xml"
    if not gl_path.exists():
        return
    gl_path, root = _load_or_create_gamelist(sdir)
    g = _find_game(root, old_rel)
    if g is None:
        return
    g.find("path").text = f"./{new_rel}"
    _write_gamelist(gl_path, root)


EDITABLE_META = ("name", "desc", "genre", "developer", "publisher", "players", "rating",
                 "releasedate", "favorite", "hidden", "image", "thumbnail", "marquee", "video",
                 "fanart", "wheel", "boxart", "titleshot", "manual", "lang", "region")


def update_game_meta(settings, slug, rom_rel, meta):
    sdir = rom_dir(settings, slug)
    rom = confine(sdir, rom_rel)
    if not rom.is_file():
        return False, {"error": "ROM not found"}
    rel = str(rom.relative_to(sdir))
    gl_path, root = _load_or_create_gamelist(sdir)
    g = _find_game(root, rel)
    if g is None:
        g = ET.SubElement(root, "game")
        ET.SubElement(g, "path").text = f"./{rel}"
    for key, value in (meta or {}).items():
        if key not in EDITABLE_META:
            continue
        el = g.find(key)
        value = "" if value is None else str(value).strip()
        if value:
            if el is None:
                el = ET.SubElement(g, key)
            el.text = value
        elif el is not None:
            g.remove(el)
    _write_gamelist(gl_path, root)
    invalidate_rom_cache()
    return True, {"rom": rel}


def save_media(settings, slug, rom_rel, media_type, data, ext):
    sdir = rom_dir(settings, slug)
    rom = confine(sdir, rom_rel)
    if not rom.is_file():
        return False, {"error": "ROM not found"}
    if media_type not in MEDIA_SUFFIX:
        return False, {"error": "Unknown media type"}
    ext = ext.lower() if ext.startswith(".") else "." + ext.lower()
    dest = media_path(sdir, rom.stem, media_type, ext)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    tag = GAMELIST_TAG_FOR_MEDIA.get(media_type)
    if tag:
        update_game_meta(settings, slug, rom_rel, {tag: f"./{dest.relative_to(sdir)}"})
    return True, {"path": str(dest), "rel": str(dest.relative_to(sdir))}


def delete_media(settings, slug, rel_media):
    sdir = rom_dir(settings, slug)
    p = confine(sdir, rel_media)
    if p.parent.name not in ("images", "videos", "manuals") or not p.is_file():
        return False, {"error": "Not a media file"}
    p.unlink()
    invalidate_rom_cache()
    return True, {"deleted": str(p.relative_to(sdir))}
