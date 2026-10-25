"""HTTP server: a small regex router on top of http.server, JSON helpers,
static file serving and every API endpoint."""
import json
import mimetypes
import os
import re
import sys
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import APP_NAME, __version__
from . import bios, metrics, retro, roms, scraper, service, systems, themes
from .config import load_settings, save_settings
from .util import confine, is_safe_slug, parse_multipart

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
MAX_BODY = 512 * 1024 * 1024
ROUTES = []


def route(method, pattern):
    rx = re.compile("^" + pattern + "$")

    def deco(fn):
        ROUTES.append((method, rx, fn))
        return fn
    return deco


class Request:
    def __init__(self, handler):
        self.h = handler
        parsed = urllib.parse.urlparse(handler.path)
        self.path = parsed.path.rstrip("/") or "/"
        self.query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        self.settings = load_settings()
        self._body = None

    def body(self):
        if self._body is None:
            try:
                n = int(self.h.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n <= 0 or n > MAX_BODY:
                self._body = b""
            else:
                self._body = self.h.rfile.read(n)
        return self._body

    def json(self):
        raw = self.body()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            raise ApiError("Body is not valid JSON")
        return data if isinstance(data, dict) else {}

    def multipart(self):
        return parse_multipart(self.h.headers.get("Content-Type", ""), self.body())


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def ok(**data):
    data.setdefault("ok", True)
    return data


def fail(message, status=400, **extra):
    return {"ok": False, "error": message, **extra}, status


# ------------------------------------------------------------------ static --
@route("GET", "/")
def index(req):
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("{{app_version}}", __version__).replace("{{app_name}}", APP_NAME)
    return ("html", html)


@route("GET", r"/static/(?P<name>[A-Za-z0-9_./-]+)")
def static_file(req, name):
    p = confine(STATIC_DIR, name)
    if not p.is_file():
        raise ApiError("Not found", 404)
    return ("file", p)


@route("GET", "/favicon.ico")
def favicon(req):
    return ("file", STATIC_DIR / "favicon.svg")


# ------------------------------------------------------------------ system ---
@route("GET", "/api/info")
def api_info(req):
    s = req.settings
    return ok(app=APP_NAME, version=__version__, author="Dan Lee",
              active_theme=themes.detect_active_theme(s), has_pil=themes.HAS_PIL,
              hardware_types=systems.HARDWARE_TYPES, ext_presets=systems.EXT_PRESETS,
              custom_systems=len(systems.list_custom_systems(s)),
              rom_systems=len(roms.rom_systems_cached(s)),
              batocera_version=metrics.batocera_version(), hostname=metrics.hostname(),
              roms_base=s["roms_base"])


@route("GET", "/api/dashboard")
def api_dashboard(req):
    return ok(**metrics.dashboard(service.es_status))


@route("GET", "/api/fans")
def api_fans(req):
    return ok(fans=metrics.fans(), cpu_temp=metrics.cpu_temp()[0])


@route("GET", "/api/news")
def api_news(req):
    return ok(items=retro.batocera_news(force="force" in req.query))


@route("GET", "/api/settings")
def api_get_settings(req):
    s = dict(req.settings)
    s["ra_api_key"] = "********" if s.get("ra_api_key") else ""
    return ok(settings=s)


@route("POST", "/api/settings")
def api_save_settings(req):
    data = req.json()
    if str(data.get("ra_api_key", "")).startswith("********"):
        data.pop("ra_api_key")
    if "server_port" in data:
        try:
            port = int(data["server_port"])
            if not 1 <= port <= 65535:
                raise ValueError
            data["server_port"] = port
        except (TypeError, ValueError):
            return fail("Port must be a number between 1 and 65535")
    s = save_settings(data)
    systems.invalidate_catalogue()
    roms.invalidate_rom_cache()
    s["ra_api_key"] = "********" if s.get("ra_api_key") else ""
    return ok(settings=s)


# ------------------------------------------------------------------ service --
@route("GET", "/api/service/status")
def api_service_status(req):
    return ok(process=service.process_status(req.settings),
              autostart=service.autostart_status(req.settings),
              suggested_cmd=service.service_cmd(req.settings), es=service.es_status())


@route("POST", "/api/service/autostart")
def api_service_autostart(req):
    data = req.json()
    if data.get("enabled"):
        return ok(autostart=service.install_autostart(req.settings))
    removed = service.remove_autostart(req.settings)
    return ok(removed=removed, autostart=service.autostart_status(req.settings))


@route("GET", "/api/service/custom-sh")
def api_custom_sh(req):
    p = Path(req.settings["custom_sh"])
    return ok(path=str(p), exists=p.exists(),
              content=p.read_text(encoding="utf-8", errors="replace") if p.exists() else "")


@route("POST", "/api/service/restart")
def api_service_restart(req):
    started = service.restart_self(req.settings)
    if started:
        threading.Timer(1.0, lambda: os._exit(0)).start()
    return ok(restarting=started)


@route("POST", "/api/service/stop")
def api_service_stop(req):
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return ok(stopping=True)


@route("POST", "/api/service/power")
def api_power(req):
    action = req.json().get("action")
    success, info = service.reboot_or_shutdown(action)
    return ok(**info) if success else fail(info["error"])


@route("GET", "/api/es/status")
def api_es_status(req):
    return ok(**service.es_status())


@route("POST", "/api/es/restart")
def api_es_restart(req):
    success, info = service.restart_emulationstation()
    return ok(**info) if success else fail(info["error"], 500)


# ------------------------------------------------------------------ systems --
@route("GET", "/api/systems")
def api_systems(req):
    return ok(systems=systems.list_custom_systems(req.settings))


@route("GET", "/api/systems/catalogue")
def api_catalogue(req):
    cat = systems.load_catalogue(req.settings, force="force" in req.query)
    return ok(count=len(cat), systems=cat, source=req.settings["es_builtin_cfg"])


@route("GET", r"/api/systems/(?P<slug>[^/]+)")
def api_system_detail(req, slug):
    s = systems.get_custom_system(req.settings, slug)
    if not s:
        return fail("System not found", 404)
    return ok(system=s)


@route("POST", "/api/systems/preview")
def api_system_preview(req):
    d = req.json()
    errors = systems.validate_payload(d)
    return ok(xml=systems.build_xml(d, req.settings), errors=errors)


@route("POST", "/api/systems")
def api_system_create(req):
    d = req.json()
    success, info = systems.write_custom_system(req.settings, d, dry_run=bool(d.get("dry_run")))
    if success and not info.get("dry_run"):
        service.mark_es_restart_pending()
        roms.invalidate_rom_cache()
    return ok(**info) if success else fail("Validation failed", errors=info["errors"])


@route("PUT", r"/api/systems/(?P<slug>[^/]+)")
def api_system_update(req, slug):
    d = req.json()
    success, info = systems.write_custom_system(req.settings, d, old_slug=slug,
                                                dry_run=bool(d.get("dry_run")))
    if success and not info.get("dry_run"):
        service.mark_es_restart_pending()
        roms.invalidate_rom_cache()
    return ok(**info) if success else fail("Validation failed", errors=info["errors"])


@route("DELETE", r"/api/systems/(?P<slug>[^/]+)")
def api_system_delete(req, slug):
    success, info = systems.delete_custom_system(req.settings, slug)
    if success:
        service.mark_es_restart_pending()
        roms.invalidate_rom_cache()
    return ok(**info) if success else fail(info["error"], 404)


# ------------------------------------------------------------------ themes ---
@route("GET", "/api/themes")
def api_themes(req):
    return ok(active=themes.detect_active_theme(req.settings), themes=themes.list_themes(req.settings))


@route("GET", r"/api/themes/logo/(?P<slug>[^/]+)")
def api_theme_logo(req, slug):
    p = themes.find_system_logo(req.settings, slug, req.query.get("theme"))
    if not p:
        raise ApiError("No logo", 404)
    return ("file", Path(p))


@route("POST", "/api/themes/logo")
def api_upload_logo(req):
    form = req.multipart()
    slug = form["fields"].get("system", "")
    theme = form["fields"].get("theme") or None
    if form["files"]:
        data = form["files"][0]["data"]
    elif form["fields"].get("placeholder"):
        data = themes.make_placeholder_png(form["fields"].get("label") or slug)
        if data is None:
            return fail("Pillow is not installed, so placeholder logos cannot be generated")
    else:
        return fail("No file uploaded")
    success, info = themes.save_system_logo(req.settings, slug, data, theme)
    return ok(**info) if success else fail(info["error"])


# ------------------------------------------------------------------ roms -----
@route("GET", "/api/roms")
def api_roms(req):
    return ok(systems=roms.rom_systems_cached(req.settings, force="force" in req.query))


@route("GET", r"/api/roms/(?P<slug>[^/]+)")
def api_rom_folder(req, slug):
    try:
        data = roms.list_rom_folder(req.settings, slug, req.query.get("path", ""))
    except ValueError:
        return fail("Invalid path")
    if data is None:
        return fail("Folder not found", 404)
    return ok(**data)


@route("GET", r"/api/roms/(?P<slug>[^/]+)/image")
def api_rom_image(req, slug):
    rel = req.query.get("rom", "")
    try:
        sdir = roms.rom_dir(req.settings, slug)
        confine(sdir, rel)
    except ValueError:
        raise ApiError("Invalid path", 400)
    games = roms.parse_gamelist(sdir / "gamelist.xml")
    p = roms.find_image(sdir, rel, games.get(rel))
    if not p:
        raise ApiError("No image", 404)
    return ("file", Path(p))


@route("GET", r"/api/roms/(?P<slug>[^/]+)/media")
def api_rom_media(req, slug):
    try:
        return ok(**roms.image_info(req.settings, slug, req.query.get("rom", "")))
    except ValueError:
        return fail("Invalid path")


@route("GET", r"/api/roms/(?P<slug>[^/]+)/file")
def api_rom_media_file(req, slug):
    try:
        p = confine(roms.rom_dir(req.settings, slug), req.query.get("path", ""))
    except ValueError:
        raise ApiError("Invalid path", 400)
    if p.parent.name not in ("images", "videos", "manuals") or not p.is_file():
        raise ApiError("Not found", 404)
    return ("file", p)


@route("POST", r"/api/roms/(?P<slug>[^/]+)/rename")
def api_rom_rename(req, slug):
    d = req.json()
    try:
        success, info = roms.rename_rom(req.settings, slug, d.get("rom", ""), d.get("new_name", ""))
    except ValueError:
        return fail("Invalid path")
    return ok(**info) if success else fail(info["error"])


@route("POST", r"/api/roms/(?P<slug>[^/]+)/meta")
def api_rom_meta(req, slug):
    d = req.json()
    try:
        success, info = roms.update_game_meta(req.settings, slug, d.get("rom", ""), d.get("meta", {}))
    except ValueError:
        return fail("Invalid path")
    return ok(**info) if success else fail(info["error"])


@route("POST", r"/api/roms/(?P<slug>[^/]+)/media")
def api_rom_media_upload(req, slug):
    form = req.multipart()
    if not form["files"]:
        return fail("No file uploaded")
    f = form["files"][0]
    ext = Path(f["filename"]).suffix or ".png"
    if ext.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".pdf"):
        return fail("Unsupported file type")
    try:
        success, info = roms.save_media(req.settings, slug, form["fields"].get("rom", ""),
                                        form["fields"].get("type", "image"), f["data"], ext)
    except ValueError:
        return fail("Invalid path")
    return ok(**info) if success else fail(info["error"])


@route("DELETE", r"/api/roms/(?P<slug>[^/]+)/media")
def api_rom_media_delete(req, slug):
    try:
        success, info = roms.delete_media(req.settings, slug, req.query.get("path", ""))
    except ValueError:
        return fail("Invalid path")
    return ok(**info) if success else fail(info["error"])


@route("GET", "/api/stats")
def api_stats(req):
    return ok(**roms.play_stats(req.settings))


@route("GET", "/api/random-game")
def api_random(req):
    return ok(game=roms.random_game(req.settings))


# ------------------------------------------------------------------ bios -----
@route("GET", "/api/bios")
def api_bios_all(req):
    return ok(**bios.check_all(req.settings), folder=bios.bios_folder_listing(req.settings))


@route("GET", "/api/bios/missing")
def api_bios_missing(req):
    installed = [s["slug"] for s in roms.rom_systems_cached(req.settings)]
    return ok(**bios.missing_for_installed(req.settings, installed))


@route("POST", "/api/bios/skip")
def api_bios_skip(req):
    d = req.json()
    key = str(d.get("key", ""))
    if ":" not in key:
        return fail("Invalid key")
    return ok(skipped=bios.set_skipped(req.settings, key, bool(d.get("skipped", True))))


@route("POST", "/api/bios/upload")
def api_bios_upload(req):
    form = req.multipart()
    if not form["files"]:
        return fail("No file uploaded")
    rel = form["fields"].get("file") or f"bios/{form['files'][0]['filename']}"
    try:
        success, info = bios.save_uploaded_bios(req.settings, rel, form["files"][0]["data"])
    except ValueError:
        return fail("Invalid BIOS path")
    return ok(**info) if success else fail(info["error"])


@route("POST", "/api/bios/download")
def api_bios_download(req):
    d = req.json()
    try:
        success, info = bios.download_bios(req.settings, str(d.get("file", "")), str(d.get("url", "")))
    except ValueError:
        return fail("Invalid BIOS path")
    return ok(**info) if success else fail(info["error"], **{k: v for k, v in info.items() if k != "error"})


# ------------------------------------------------------------------ scraper --
@route("GET", "/api/scraper/config")
def api_scraper_config(req):
    return ok(config=scraper.get_config(req.settings), ss_systems=sorted(scraper.SS_SYSTEMS),
              tgdb_systems=sorted(scraper.TGDB_PLATFORMS))


@route("POST", "/api/scraper/config")
def api_scraper_save(req):
    success, info = scraper.save_config(req.settings, req.json())
    return ok(config=info) if success else fail(info["error"])


@route("POST", "/api/scraper/search")
def api_scraper_search(req):
    d = req.json()
    try:
        result, info = scraper.search(req.settings, d.get("system", ""), d.get("rom", ""), d.get("source"))
    except ValueError:
        return fail("Invalid path")
    if result is None:
        return fail(info.get("error", "Not found"), 404)
    return ok(result=result, **info)


@route("POST", "/api/scraper/apply")
def api_scraper_apply(req):
    d = req.json()
    result = d.get("result") or {}
    types = d.get("types") or ["image", "box", "marquee"]
    try:
        out = scraper.apply_result(req.settings, d.get("system", ""), d.get("rom", ""), result,
                                   types, bool(d.get("overwrite")), d.get("write_meta", True))
    except ValueError:
        return fail("Invalid path")
    return ok(**out)


@route("GET", "/api/scraper/jobs")
def api_scraper_jobs(req):
    return ok(jobs=scraper.get_jobs())


@route("POST", "/api/scraper/jobs")
def api_scraper_start(req):
    d = req.json()
    systems_list = [s for s in (d.get("systems") or []) if is_safe_slug(str(s))]
    if not systems_list:
        return fail("Pick at least one system")
    job_id = scraper.start_batch(req.settings, systems_list, d.get("source") or "screenscraper",
                                 d.get("types") or ["image", "box", "marquee"],
                                 bool(d.get("overwrite")), d.get("skip_existing", True))
    return ok(job_id=job_id)


@route("DELETE", r"/api/scraper/jobs/(?P<job_id>[a-f0-9]+)")
def api_scraper_cancel(req, job_id):
    return ok(cancelled=scraper.cancel_job(job_id))


# ------------------------------------------------------------------ retro ----
@route("GET", "/api/retroachievements")
def api_ra(req):
    return ok(**retro.ra_profile(req.settings, force="force" in req.query))


@route("POST", "/api/retroachievements/test")
def api_ra_test(req):
    d = req.json()
    key = d.get("api_key") or ""
    if key.startswith("********"):
        key = req.settings.get("ra_api_key", "")
    success, info = retro.ra_test(d.get("user") or req.settings.get("ra_user", ""), key)
    return ok(**info) if success else fail(info["error"])


# ------------------------------------------------------------------ handler --
class PortalHandler(BaseHTTPRequestHandler):
    server_version = f"BatoceraPortal/{__version__}"

    def log_request(self, code="-", size="-"):
        try:
            if int(code) >= 400:
                super().log_request(code, size)
        except (TypeError, ValueError):
            super().log_request(code, size)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path):
        path = Path(path)
        if not path.is_file():
            return self._send_json({"ok": False, "error": "Not found"}, 404)
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if path.suffix == ".svg":
            ctype = "image/svg+xml"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache" if path.parent == STATIC_DIR else "max-age=300")
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method):
        try:
            req = Request(self)
            for m, rx, fn in ROUTES:
                if m != method:
                    continue
                match = rx.match(req.path)
                if not match:
                    continue
                kwargs = {k: urllib.parse.unquote(v) for k, v in match.groupdict().items()}
                result = fn(req, **kwargs)
                if isinstance(result, tuple) and len(result) == 2 and result[0] in ("html", "file"):
                    return self._send_html(result[1]) if result[0] == "html" else self._send_file(result[1])
                if isinstance(result, tuple):
                    data, status = result
                    return self._send_json(data, status)
                return self._send_json(result)
            self._send_json({"ok": False, "error": f"No route for {method} {req.path}"}, 404)
        except ApiError as e:
            self._send_json({"ok": False, "error": str(e)}, e.status)
        except ValueError as e:
            self._send_json({"ok": False, "error": f"Invalid request: {e}"}, 400)
        except Exception as e:
            traceback.print_exc()
            try:
                self._send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
            except OSError:
                pass

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")


def serve(host="0.0.0.0", port=5000):
    httpd = ThreadingHTTPServer((host, port), PortalHandler)
    httpd.daemon_threads = True
    return httpd
