# Batocera Portal

**Version 1.0.0 · Author: Dan Lee · MIT licence**

A self-contained web admin panel for a [Batocera](https://batocera.org) machine. Install it on
the Batocera box itself, then open it from any phone, tablet or PC on your home network to manage
custom systems, ROMs, BIOS files, artwork scraping, themes and the service itself, without SSH
and without hand-editing XML.

It is written in **pure Python (standard library only)** plus one HTML page with vanilla
JavaScript. Nothing to compile, no pip packages, no Node, no Docker.

---

## Contents

- [What it does](#what-it-does)
- [Install](#install)
- [Update](#update)
- [Use](#use)
- [How it works](#how-it-works)
- [REST API](#rest-api)
- [Configuration](#configuration)
- [Tests](#tests)
- [Project layout](#project-layout)
- [Security](#security)
- [Changes in this version](#changes-in-this-version)
- [Versioning](#versioning)

---

## What it does

| Panel | Purpose |
|---|---|
| **Dashboard** | Live CPU, GPU, RAM, storage, fans, battery, uptime, EmulationStation status, random game, most played, RetroAchievements, Batocera releases |
| **Systems** | List, edit, view XML and delete the custom systems the portal created |
| **Add / Edit System** | Form that writes a correct `es_systems_<slug>.cfg`; prefill from any built-in Batocera system; XML preview and dry run |
| **ROMs & BIOS** | ROM folder inventory grouped by hardware type; file browser; edit gamelist metadata, rename, manage media. BIOS verification by MD5 with upload, URL download and skip list |
| **Scraper** | ScreenScraper.fr and TheGamesDB; single game with preview, or batch jobs with progress |
| **Themes** | Installed themes, active theme, system logo upload |
| **Settings** | Paths, port, RetroAchievements, autostart in `custom.sh`, restart/stop, reboot/shutdown |

---

## Install

Everything happens on the Batocera machine over SSH. Only Python 3 is needed and Batocera
already ships it.

```bash
ssh root@BATOCERA            # password is "linux" by default
git clone https://github.com/yiddifliddo/BatoceraPortal /userdata/system/batocera_portal
cd /userdata/system/batocera_portal
./install.sh
```

Batocera does not ship `git` by default. Without it, download the repository as a zip on
another computer, copy it to `/userdata/system/batocera_portal` (over SMB, the share is called
`system`), then run `./install.sh` over SSH.

The installer:

1. Checks Python 3 and whether Pillow is available (optional, only for placeholder logos).
2. Copies the files to `/userdata/system/batocera_portal` if they are not already there.
3. Asks whether to start the portal at boot. Yes adds a marked block to
   `/userdata/system/custom.sh`, which Batocera runs at every boot.
4. Starts the server straight away.

Then open **http://BATOCERA:5000** (or the IP address shown by the installer).

### Installer options

| Variable | Default | Purpose |
|---|---|---|
| `BP_PORT` | `5000` | Web port |
| `BP_BASE_DIR` | `/userdata/system` | Batocera system folder |
| `BP_CUSTOM_SH` | `$BP_BASE_DIR/custom.sh` | Boot script to edit |
| `BP_PYTHON` | `python3` | Interpreter |
| `BP_AUTOSTART` | *(asks)* | `y` or `n` for unattended installs |
| `BP_NO_START` | `0` | `1` installs without starting the server |
| `NO_COLOR` | — | Plain output |

Example: `BP_PORT=8080 BP_AUTOSTART=y ./install.sh`

### Manual start

```bash
python3 /userdata/system/batocera_portal/app.py --port 5000
```

The Settings panel notices it is running in manual mode and offers a one-click autostart.

---

## Update

```bash
cd /userdata/system/batocera_portal
git pull
./install.sh        # detects the files are in place and just restarts the service
```

Or from inside the portal: Settings → **Restart portal** after replacing the files.

---

## Use

- **Create a system.** Add / Edit System → pick a reference system to prefill extensions,
  emulator, core and theme → adjust the name and slug → **Preview XML** or **Dry run** → **Save**.
  The sidebar then shows a **Restart EmulationStation** button; press it so the new system appears.
- **Fill in artwork.** Scraper → Credentials tab → enter your ScreenScraper account (and
  optionally a TheGamesDB key) → Single game or Batch.
- **Check BIOS.** ROMs & BIOS → BIOS check. Missing files can be uploaded from your browser or
  downloaded from a URL you supply; downloads are verified by MD5 and discarded on mismatch.
- **Keep it running.** Settings → turn on *Start automatically with Batocera*.

---

## How it works

Deliberately simple: one Python process, a small package of modules, one HTML page.

```
Browser ──HTTP/JSON──▶ app.py ▶ portal/server.py (router)
                                  ├── metrics.py   /proc, /sys, nvidia-smi
                                  ├── systems.py   es_systems_<slug>.cfg + built-in catalogue
                                  ├── roms.py      ROM folders, gamelist.xml, stats, media
                                  ├── bios.py      MD5 checks against /usr/bin/batocera-systems
                                  ├── scraper.py   ScreenScraper / TheGamesDB + batch worker
                                  ├── themes.py    theme list, active theme, logo upload
                                  ├── service.py   custom.sh autostart, ES restart, power
                                  ├── retro.py     RetroAchievements + release news
                                  └── config.py    settings.json
static/index.html + app.css + app.js   the whole UI, no build step
```

- **Server.** `ThreadingHTTPServer` from the standard library with a regex router. Every
  handler returns a dict that becomes JSON. Unexpected exceptions become a JSON `500` with the
  traceback on the console, never an empty reply. Path parameters are confined to their base
  folder; anything that escapes is a `400`.
- **Reference systems** come from the real `/usr/share/emulationstation/es_systems.cfg` on the
  machine, so the list always matches your Batocera version.
- **BIOS list** is parsed (with `ast`, never executed) from `/usr/bin/batocera-systems`, the
  same file Batocera's own BIOS checker uses. A small bundled list is used off-device.
- **Metrics** are read directly from `/proc/stat`, `/proc/meminfo`, `/sys/class/thermal`,
  `/sys/class/hwmon`, `/sys/class/drm` and `/sys/class/power_supply`. No agent, no daemon.
- **Autostart** is a block between `# [batocera-portal]` and `# [/batocera-portal]` markers in
  `custom.sh`, so it can be replaced or removed without touching your other lines.
- **EmulationStation restart** uses `batocera-es-swissknife --restart`, the supported method.
- **Scraper batch jobs** run on one background thread; the UI polls `/api/scraper/jobs`.
  Images are saved with EmulationStation's naming (`images/<rom>-image.png`, `-box`, `-marquee`…)
  and the matching `gamelist.xml` tags are written, so they appear immediately.
- **Settings** live in `/userdata/system/batocera_portal_settings.json`. Scraper credentials live
  in `batocera.conf` under the same keys Batocera's scraper reads.
- **State in memory** is limited to a 60 s ROM scan cache, a 5 min catalogue cache, a 10 min
  RetroAchievements cache and the batch job list.

---

## REST API

Every endpoint returns JSON with `"ok": true` or `"ok": false, "error": "…"`.

| Group | Endpoints |
|---|---|
| **Info** | `GET /api/info` · `GET /api/dashboard` · `GET /api/fans` · `GET /api/news` · `GET /api/stats` · `GET /api/random-game` |
| **Settings** | `GET /api/settings` · `POST /api/settings` |
| **Service** | `GET /api/service/status` · `POST /api/service/autostart` `{enabled}` · `GET /api/service/custom-sh` · `POST /api/service/restart` · `POST /api/service/stop` · `POST /api/service/power` `{action: reboot\|shutdown}` |
| **EmulationStation** | `GET /api/es/status` · `POST /api/es/restart` |
| **Systems** | `GET /api/systems` · `GET /api/systems/catalogue` · `GET /api/systems/<slug>` · `POST /api/systems/preview` · `POST /api/systems` · `PUT /api/systems/<slug>` · `DELETE /api/systems/<slug>` |
| **Themes** | `GET /api/themes` · `GET /api/themes/logo/<slug>` · `POST /api/themes/logo` (multipart) |
| **ROMs** | `GET /api/roms` · `GET /api/roms/<slug>?path=` · `GET /api/roms/<slug>/image?rom=` · `GET /api/roms/<slug>/media?rom=` · `GET /api/roms/<slug>/file?path=` · `POST /api/roms/<slug>/rename` · `POST /api/roms/<slug>/meta` · `POST /api/roms/<slug>/media` (multipart) · `DELETE /api/roms/<slug>/media?path=` |
| **BIOS** | `GET /api/bios` · `GET /api/bios/missing` · `POST /api/bios/skip` · `POST /api/bios/upload` (multipart) · `POST /api/bios/download` `{file, url}` |
| **Scraper** | `GET/POST /api/scraper/config` · `POST /api/scraper/search` · `POST /api/scraper/apply` · `GET/POST /api/scraper/jobs` · `DELETE /api/scraper/jobs/<id>` |
| **RetroAchievements** | `GET /api/retroachievements` · `POST /api/retroachievements/test` |

Example:

```bash
curl -s http://BATOCERA:5000/api/dashboard | python3 -m json.tool
curl -s -X POST http://BATOCERA:5000/api/systems/preview -H 'Content-Type: application/json' \
  -d '{"fullname":"Mega Drive Hacks","name":"md-hacks","rompath":"/userdata/roms/md-hacks","extensions":".md .zip","emulator":"libretro","core":"genesisplusgx"}'
```

---

## Configuration

Defaults, all editable in Settings:

| Key | Default |
|---|---|
| `es_cfg_dir` | `/userdata/system/configs/emulationstation` |
| `roms_base` | `/userdata/roms` |
| `bios_dir` | `/userdata/bios` |
| `themes_user` / `themes_sys` | `/userdata/themes` / `/usr/share/emulationstation/themes` |
| `batocera_conf` | `/userdata/system/batocera.conf` |
| `custom_sh` | `/userdata/system/custom.sh` |
| `configgen_path` | auto-detected `emulatorlauncher.py` |
| `server_port` | `5000` |
| `ra_user` / `ra_api_key` | empty (RetroAchievements is optional) |

Environment variables for development: `BP_SETTINGS` (settings file path) and `BP_BASE_DIR`
(replaces `/userdata`).

---

## Tests

```bash
pip install pytest
python -m pytest
# 77 passed
```

Tests run anywhere; they build a fake `/userdata` tree in a temporary folder and spin up the
real HTTP server on a random port for the API tests.

---

## Project layout

```
BatoceraPortal/
├── app.py                 entry point (python3 app.py --port 5000)
├── portal/                backend package (see "How it works")
├── static/
│   ├── index.html         the single page
│   ├── app.css
│   ├── app.js
│   └── favicon.svg
├── tests/                 pytest suite
├── install.sh             installer
├── README.md · CHANGELOG.md · LICENSE
```

---

## Security

This panel has **no authentication**. Anyone who can reach the port can create and delete
configurations, upload files, restart EmulationStation and reboot the machine, and Batocera runs
everything as root.

- Keep it on your home LAN. Do not port-forward it.
- For remote access use a VPN such as Tailscale or WireGuard.
- If your network is not trusted, leave autostart off and start it only when needed.

What it does defend against: every path coming from the browser is confined to its configured
base folder, slugs are restricted to `[a-z0-9_-]`, `batocera.conf` values are sanitised, request
bodies are capped at 512 MB and BIOS downloads at 64 MB and verified by MD5.

---

## Changes in this version

**1.0.0 (2026-10-25)** – first release. Everything listed under *What it does* is new. See
`CHANGELOG.md` for the full list.

Design decisions compared with similar tools:

- Backend split into modules instead of a single file, so each area can be tested and extended.
- Reference systems and BIOS hashes are read from Batocera itself rather than bundled copies
  that go stale.
- No embedded third-party API credentials; you supply your own ScreenScraper / TheGamesDB keys.
- A regex router replaces a long if/elif chain; errors are always JSON.

---

## Versioning

The version number is `1.0.0`, defined once in `portal/__init__.py`. Every code change bumps it
(patch for fixes, minor for features, major for breaking changes) and gets a CHANGELOG entry.
