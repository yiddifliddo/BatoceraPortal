"""Artwork and metadata scraper: ScreenScraper.fr and TheGamesDB.

Credentials live in batocera.conf under the same keys Batocera uses, so the
built-in scraper and this one share them.
"""
import json
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .roms import (GAMELIST_TAG_FOR_MEDIA, IGNORED_DIRS, IGNORED_FILES, _ext_set, known_systems,
                   media_path, parse_gamelist, rom_dir, update_game_meta, invalidate_rom_cache)
from .util import crc32_file, md5_file

SS_API = "https://api.screenscraper.fr/api2"
SS_SOFTNAME = "batocera_portal"
TGDB_API = "https://api.thegamesdb.net/v1"
USER_AGENT = "BatoceraPortal/1.0"

CONF_KEYS = {
    "ss_user": "global.scraper.screenscraper.user",
    "ss_pass": "global.scraper.screenscraper.password",
    "ss_devid": "global.scraper.screenscraper.devid",
    "ss_devpassword": "global.scraper.screenscraper.devpassword",
    "tgdb_key": "global.scraper.thegamesdb.apikey",
    "default_source": "global.scraper.portal.source",
    "region": "global.scraper.portal.region",
    "language": "global.scraper.portal.language",
}

# ScreenScraper system ids for the usual Batocera folders.
SS_SYSTEMS = {
    "3do": 29, "amiga": 64, "amstradcpc": 65, "apple2": 86, "arcade": 75, "atari2600": 26,
    "atari5200": 40, "atari7800": 41, "atarist": 42, "atomiswave": 53, "c64": 66,
    "colecovision": 48, "dreamcast": 23, "fba": 75, "fbneo": 75, "fds": 106, "gamegear": 21,
    "gb": 9, "gba": 12, "gbc": 10, "gc": 13, "intellivision": 115, "jaguar": 27, "lynx": 28,
    "mame": 75, "mastersystem": 2, "megadrive": 1, "msx": 113, "msx2": 116, "n64": 14,
    "naomi": 56, "nds": 15, "neogeo": 142, "neogeocd": 70, "nes": 3, "ngp": 25, "ngpc": 82,
    "pc": 135, "pcengine": 31, "pcenginecd": 114, "pcfx": 72, "ps2": 58, "psp": 61, "psx": 57,
    "saturn": 22, "scummvm": 123, "sega32x": 19, "segacd": 20, "sg1000": 109, "snes": 4,
    "supergrafx": 105, "vectrex": 102, "virtualboy": 11, "wii": 16, "wonderswan": 45,
    "wonderswancolor": 46, "x68000": 79, "zxspectrum": 76, "gamecube": 13, "ps3": 59,
    "switch": 225, "3ds": 17, "xbox": 32, "dos": 135, "ports": 135, "channelf": 80,
    "odyssey2": 104, "videopac": 104,
}
TGDB_PLATFORMS = {
    "nes": 7, "snes": 6, "n64": 3, "gb": 4, "gbc": 41, "gba": 5, "nds": 8, "gc": 2, "wii": 9,
    "megadrive": 18, "mastersystem": 35, "gamegear": 20, "segacd": 21, "sega32x": 33,
    "saturn": 17, "dreamcast": 16, "psx": 10, "ps2": 11, "psp": 13, "atari2600": 22,
    "atari5200": 26, "atari7800": 27, "lynx": 4924, "jaguar": 28, "neogeo": 24, "arcade": 23,
    "mame": 23, "fbneo": 23, "pcengine": 34, "3do": 25, "colecovision": 31,
    "intellivision": 32, "virtualboy": 4918, "wonderswan": 4925, "wonderswancolor": 4926,
    "ngp": 4922, "ngpc": 4923, "amiga": 4911, "c64": 40, "amstradcpc": 4914, "zxspectrum": 4913,
    "msx": 4929, "atarist": 4937, "pc": 1, "dos": 1,
}

_SS_BAD_ESCAPE = re.compile(rb'\\(?!(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))')

_jobs = {}
_jobs_lock = threading.Lock()
_worker = {"thread": None}
_worker_lock = threading.Lock()


# ---------------------------------------------------------------- config ----
def read_conf(path):
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip()
    return out


def get_config(settings):
    conf = read_conf(settings["batocera_conf"])
    cfg = {k: conf.get(v, "") for k, v in CONF_KEYS.items()}
    cfg["ss_pass"] = "********" if cfg["ss_pass"] else ""
    cfg["ss_devpassword"] = "********" if cfg["ss_devpassword"] else ""
    cfg["tgdb_key"] = ("*" * 8 + cfg["tgdb_key"][-4:]) if cfg["tgdb_key"] else ""
    cfg["default_source"] = cfg["default_source"] or "screenscraper"
    cfg["region"] = cfg["region"] or "wor"
    cfg["language"] = cfg["language"] or "en"
    cfg["has_ss_creds"] = bool(conf.get(CONF_KEYS["ss_user"]))
    cfg["has_tgdb_key"] = bool(conf.get(CONF_KEYS["tgdb_key"]))
    cfg["has_ss_dev"] = bool(conf.get(CONF_KEYS["ss_devid"]))
    return cfg


def save_config(settings, data):
    """Write the scraper keys into batocera.conf, replacing existing lines."""
    p = Path(settings["batocera_conf"])
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines() if p.exists() else []
    updates = {}
    for k, conf_key in CONF_KEYS.items():
        if k in data and data[k] is not None and not str(data[k]).startswith("********"):
            v = str(data[k]).strip()
            if "\n" in v or "\r" in v:
                return False, {"error": f"Invalid value for {k}"}
            updates[conf_key] = v
    out = []
    done = set()
    for line in lines:
        s = line.strip()
        key = s.lstrip("#").split("=", 1)[0].strip() if "=" in s else None
        if key in updates:
            if updates[key]:
                out.append(f"{key}={updates[key]}")
            done.add(key)
        else:
            out.append(line)
    for key, v in updates.items():
        if key not in done and v:
            out.append(f"{key}={v}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    return True, get_config(settings)


def resolve_creds(settings):
    conf = read_conf(settings["batocera_conf"])
    return {k: conf.get(v, "") for k, v in CONF_KEYS.items()}


# ---------------------------------------------------------------- http ------
def _get(url, timeout=25, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read()


def clean_rom_name(filename):
    name = Path(filename).stem
    name = re.sub(r"[\(\[].*?[\)\]]", "", name)
    name = re.sub(r"\b(v\d+(\.\d+)*|rev\s?\w+|disc\s?\d+|cd\s?\d+)\b", "", name, flags=re.I)
    name = name.replace("_", " ").replace(".", " ")
    return re.sub(r"\s+", " ", name).strip(" -")


# ---------------------------------------------------------------- screenscraper
def ss_parse_json(payload):
    try:
        return json.loads(payload.decode("utf-8", errors="replace"))
    except ValueError:
        fixed = _SS_BAD_ESCAPE.sub(rb"\\\\", payload)
        return json.loads(fixed.decode("utf-8", errors="replace"))


def _ss_pick_text(items, prefer_lang="en", prefer_region="wor"):
    if not items:
        return ""
    if isinstance(items, dict):
        return items.get("text", "")
    for key, want in (("langue", prefer_lang), ("region", prefer_region)):
        for it in items:
            if it.get(key) == want and it.get("text"):
                return it["text"]
    for it in items:
        if it.get("text"):
            return it["text"]
    return ""


def ss_search(rom_path, slug, creds, language="en", region="wor"):
    ss_id = SS_SYSTEMS.get(slug)
    params = {
        "devid": creds.get("ss_devid", ""), "devpassword": creds.get("ss_devpassword", ""),
        "softname": SS_SOFTNAME, "output": "json",
        "ssid": creds.get("ss_user", ""), "sspassword": creds.get("ss_pass", ""),
        "romtype": "rom", "romnom": Path(rom_path).name,
    }
    if ss_id:
        params["systemeid"] = ss_id
    p = Path(rom_path)
    if p.is_file() and p.stat().st_size < 128 * 1024 * 1024:
        params["md5"] = md5_file(p)
        params["crc"] = crc32_file(p)
        params["romtaille"] = p.stat().st_size
    url = f"{SS_API}/jeuInfos.php?{urllib.parse.urlencode(params)}"
    try:
        raw = _get(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, {"error": "Game not found on ScreenScraper"}
        if e.code in (401, 403):
            return None, {"error": "ScreenScraper rejected the credentials"}
        if e.code == 429:
            return None, {"error": "ScreenScraper quota reached, try later"}
        return None, {"error": f"ScreenScraper HTTP {e.code}"}
    except Exception as e:
        return None, {"error": f"ScreenScraper request failed: {e}"}
    try:
        data = ss_parse_json(raw)
    except ValueError:
        text = raw.decode("utf-8", errors="replace")[:200]
        return None, {"error": f"Unexpected ScreenScraper reply: {text}"}
    jeu = (data.get("response") or {}).get("jeu")
    if not jeu:
        return None, {"error": "Game not found on ScreenScraper"}
    ssuser = (data.get("response") or {}).get("ssuser") or {}
    quota = {"requests_today": ssuser.get("requeststoday"), "max_per_day": ssuser.get("maxrequestsperday")}
    return ss_build_result(jeu, language, region), {"quota": quota}


def ss_build_result(jeu, language="en", region="wor"):
    medias = jeu.get("medias") or []
    media_urls = {}
    for want, types in (("image", ("ss", "screenshot")), ("box", ("box-2D",)), ("box3d", ("box-3D",)),
                        ("wheel", ("wheel", "wheel-hd")), ("marquee", ("marquee", "screenmarquee")),
                        ("fanart", ("fanart",)), ("titleshot", ("sstitle",)), ("mix", ("mixrbv1", "mixrbv2")),
                        ("video", ("video-normalized", "video")), ("manual", ("manuel",))):
        chosen = None
        for t in types:
            same_region = [m for m in medias if m.get("type") == t and m.get("region") == region]
            any_region = [m for m in medias if m.get("type") == t]
            pick = same_region or any_region
            if pick:
                chosen = pick[0]
                break
        if chosen:
            media_urls[want] = {"url": chosen.get("url"), "format": chosen.get("format", "png")}
    genres = jeu.get("genres") or []
    genre_names = []
    for g in genres:
        genre_names.append(_ss_pick_text(g.get("noms"), language, region))
    date = _ss_pick_text(jeu.get("dates"), language, region)
    date_es = ""
    if date:
        m = re.match(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", date)
        if m:
            date_es = f"{m.group(1)}{m.group(2) or '01'}{m.group(3) or '01'}T000000"
    rating = ""
    note = (jeu.get("note") or {}).get("text") if isinstance(jeu.get("note"), dict) else None
    if note:
        try:
            rating = f"{float(note) / 20:.2f}"
        except ValueError:
            pass
    return {
        "source": "screenscraper", "id": jeu.get("id"),
        "name": _ss_pick_text(jeu.get("noms"), language, region),
        "desc": _ss_pick_text(jeu.get("synopsis"), language, region),
        "genre": ", ".join(g for g in genre_names if g),
        "developer": (jeu.get("developpeur") or {}).get("text", ""),
        "publisher": (jeu.get("editeur") or {}).get("text", ""),
        "players": (jeu.get("joueurs") or {}).get("text", ""),
        "rating": rating, "releasedate": date_es, "media": media_urls,
    }


# ---------------------------------------------------------------- thegamesdb --
def tgdb_search(rom_name, slug, api_key):
    params = {"apikey": api_key, "name": clean_rom_name(rom_name),
              "fields": "players,publishers,genres,overview,rating", "include": "boxart"}
    if slug in TGDB_PLATFORMS:
        params["filter[platform]"] = TGDB_PLATFORMS[slug]
    url = f"{TGDB_API}/Games/ByGameName?{urllib.parse.urlencode(params)}"
    try:
        data = json.loads(_get(url))
    except urllib.error.HTTPError as e:
        return None, {"error": f"TheGamesDB HTTP {e.code}"}
    except Exception as e:
        return None, {"error": f"TheGamesDB request failed: {e}"}
    games = (data.get("data") or {}).get("games") or []
    if not games:
        return None, {"error": "Game not found on TheGamesDB"}
    g = games[0]
    boxart = (data.get("include") or {}).get("boxart") or {}
    base = (boxart.get("base_url") or {}).get("original", "")
    media = {}
    for art in (boxart.get("data") or {}).get(str(g.get("id")), []):
        if art.get("type") == "boxart" and art.get("side") == "front" and "box" not in media:
            media["box"] = {"url": base + art["filename"], "format": art["filename"].rsplit(".", 1)[-1]}
        if art.get("type") == "screenshot" and "image" not in media:
            media["image"] = {"url": base + art["filename"], "format": art["filename"].rsplit(".", 1)[-1]}
        if art.get("type") == "fanart" and "fanart" not in media:
            media["fanart"] = {"url": base + art["filename"], "format": art["filename"].rsplit(".", 1)[-1]}
        if art.get("type") == "clearlogo" and "wheel" not in media:
            media["wheel"] = {"url": base + art["filename"], "format": art["filename"].rsplit(".", 1)[-1]}
    date = g.get("release_date") or ""
    date_es = date.replace("-", "") + "T000000" if re.match(r"\d{4}-\d{2}-\d{2}", date) else ""
    return {
        "source": "thegamesdb", "id": g.get("id"), "name": g.get("game_title", ""),
        "desc": g.get("overview", "") or "", "genre": "", "developer": "", "publisher": "",
        "players": str(g.get("players") or ""), "rating": "", "releasedate": date_es,
        "media": media,
    }, {"remaining": data.get("remaining_monthly_allowance")}


# ---------------------------------------------------------------- apply -------
def search(settings, slug, rom_rel, source=None):
    creds = resolve_creds(settings)
    source = source or creds.get("default_source") or "screenscraper"
    sdir = rom_dir(settings, slug)
    rom_path = sdir / rom_rel
    if source == "thegamesdb":
        if not creds.get("tgdb_key"):
            return None, {"error": "TheGamesDB API key is not set"}
        return tgdb_search(rom_path.name, slug, creds["tgdb_key"])
    if not creds.get("ss_user"):
        return None, {"error": "ScreenScraper username/password are not set"}
    return ss_search(str(rom_path), slug, creds,
                     creds.get("language") or "en", creds.get("region") or "wor")


def download_media(settings, slug, rom_rel, result, types, overwrite=False):
    sdir = rom_dir(settings, slug)
    rom = sdir / rom_rel
    saved = {}
    errors = {}
    for t in types:
        m = (result.get("media") or {}).get(t)
        if not m or not m.get("url"):
            continue
        ext = "." + (m.get("format") or "png").lower().lstrip(".")
        if ext == ".jpeg":
            ext = ".jpg"
        dest = media_path(sdir, rom.stem, t, ext)
        if dest.exists() and not overwrite:
            saved[t] = str(dest.relative_to(sdir))
            continue
        try:
            data = _get(m["url"], timeout=60)
            if len(data) < 64:
                raise ValueError("empty file")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            saved[t] = str(dest.relative_to(sdir))
        except Exception as e:
            errors[t] = str(e)
    return saved, errors


def apply_result(settings, slug, rom_rel, result, types, overwrite=False, write_meta=True):
    saved, errors = download_media(settings, slug, rom_rel, result, types, overwrite)
    meta = {}
    if write_meta:
        for k in ("name", "desc", "genre", "developer", "publisher", "players", "rating", "releasedate"):
            if result.get(k):
                meta[k] = result[k]
    for t, rel in saved.items():
        tag = GAMELIST_TAG_FOR_MEDIA.get(t)
        if tag:
            meta[tag] = f"./{rel}"
    if meta:
        update_game_meta(settings, slug, rom_rel, meta)
    invalidate_rom_cache()
    return {"saved": saved, "errors": errors, "meta": sorted(meta.keys())}


def list_roms_for_scrape(settings, slug):
    sdir = rom_dir(settings, slug)
    meta = known_systems(settings).get(slug, {})
    exts = _ext_set(meta.get("extensions")) or {"*"}
    roms = []
    for root, dirs, files in __import__("os").walk(sdir):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
        for f in sorted(files):
            if f in IGNORED_FILES or f.startswith("."):
                continue
            ext = Path(f).suffix.lower()
            if "*" in exts or ext in exts:
                roms.append(str(Path(root, f).relative_to(sdir)))
    return roms


# ---------------------------------------------------------------- batch -------
def start_batch(settings, systems, source, types, overwrite=False, skip_existing=True):
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "status": "pending", "systems": list(systems), "source": source,
           "types": list(types), "overwrite": overwrite, "skip_existing": skip_existing,
           "progress": 0, "current_system": None, "current_rom": None, "done": 0, "total": 0,
           "ok": 0, "fail": 0, "skip": 0, "errors": [], "started": time.time(), "finished": None,
           "cancel": False}
    with _jobs_lock:
        _jobs[job_id] = job
    _ensure_worker(settings)
    return job_id


def get_jobs():
    with _jobs_lock:
        return [{k: v for k, v in j.items() if k != "cancel"} for j in _jobs.values()]


def cancel_job(job_id):
    with _jobs_lock:
        j = _jobs.get(job_id)
        if not j:
            return False
        j["cancel"] = True
        if j["status"] == "pending":
            j["status"] = "cancelled"
        return True


def _ensure_worker(settings):
    with _worker_lock:
        t = _worker["thread"]
        if t and t.is_alive():
            return

        def loop():
            while True:
                job = None
                with _jobs_lock:
                    for j in _jobs.values():
                        if j["status"] == "pending":
                            j["status"] = "running"
                            job = j
                            break
                if job is None:
                    time.sleep(1)
                    continue
                try:
                    _run_job(settings, job)
                except Exception as e:  # keep the worker alive whatever happens
                    with _jobs_lock:
                        job["status"] = "failed"
                        job["errors"].append(str(e))
                        job["finished"] = time.time()

        _worker["thread"] = threading.Thread(target=loop, daemon=True, name="scraper-batch")
        _worker["thread"].start()


def _run_job(settings, job):
    plan = []
    for slug in job["systems"]:
        try:
            for rel in list_roms_for_scrape(settings, slug):
                plan.append((slug, rel))
        except ValueError:
            job["errors"].append(f"{slug}: invalid system")
    with _jobs_lock:
        job["total"] = len(plan)
    for idx, (slug, rel) in enumerate(plan, 1):
        if job["cancel"]:
            with _jobs_lock:
                job["status"] = "cancelled"
                job["finished"] = time.time()
            return
        with _jobs_lock:
            job["current_system"] = slug
            job["current_rom"] = rel
        sdir = rom_dir(settings, slug)
        games = parse_gamelist(sdir / "gamelist.xml")
        if job["skip_existing"] and games.get(rel, {}).get("image") and games.get(rel, {}).get("desc"):
            with _jobs_lock:
                job["skip"] += 1
                job["done"] = idx
                job["progress"] = min(99, int(idx / len(plan) * 100))
            continue
        result, info = search(settings, slug, rel, job["source"])
        if result is None:
            with _jobs_lock:
                job["fail"] += 1
                if len(job["errors"]) < 200:
                    job["errors"].append(f"{slug}/{rel}: {info.get('error')}")
        else:
            out = apply_result(settings, slug, rel, result, job["types"], job["overwrite"])
            with _jobs_lock:
                if out["errors"] and not out["saved"]:
                    job["fail"] += 1
                else:
                    job["ok"] += 1
        with _jobs_lock:
            job["done"] = idx
            job["progress"] = min(99, int(idx / len(plan) * 100))
        if job["source"] == "screenscraper":
            time.sleep(0.4)  # be polite to their quota
    with _jobs_lock:
        job["status"] = "completed"
        job["progress"] = 100
        job["finished"] = time.time()
        job["current_rom"] = None
