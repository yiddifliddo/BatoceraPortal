# Changelog

All notable changes to Batocera Portal are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project uses [Semantic Versioning](https://semver.org/).

The current version lives in one place: `portal/__init__.py` (`__version__`).
Every change that produces code bumps it.

## [1.0.0] - 2026-10-25

First release. Author: Dan Lee.

### Added
- **Dashboard**: live CPU usage and temperature, GPU (AMD/Intel via DRM sysfs, NVIDIA via
  nvidia-smi), memory, storage, fans, battery, load average, uptime, EmulationStation status
  and PID, random game card, most-played list, RetroAchievements profile and Batocera release
  news. Auto refresh every 5 seconds (toggleable).
- **Custom systems manager**: create, edit, rename, delete `es_systems_<slug>.cfg` files from a
  form; prefill from any system Batocera already knows; XML preview; dry run; optional ROM
  folder creation; optional emulator/core lines in `batocera.conf`; stale lines removed on
  rename or delete; "restart EmulationStation" reminder when a config changed.
- **ROM folder monitor**: counts, sizes and extensions per system, grouped by hardware type with
  filter chips and search; file browser with gamelist metadata; edit metadata, rename ROMs,
  upload or delete media per game.
- **BIOS check**: reads the BIOS list straight from Batocera's own `/usr/bin/batocera-systems`
  (bundled fallback list off-device); MD5 verification; upload; download from a URL with MD5
  verification; skip list; "only systems with a ROM folder" filter.
- **Scraper**: ScreenScraper.fr and TheGamesDB; single game with preview and media selection;
  batch jobs across systems with a background worker, progress, error log and cancel;
  credentials stored in `batocera.conf` under the same keys Batocera's scraper uses.
- **Themes**: list user and system themes, show the active one, upload a system logo (PNG/JPEG/
  SVG) into `<theme>/<slug>/art/`, optional Pillow-generated placeholder.
- **Service**: autostart block in `custom.sh` (install/remove/replace, user lines preserved),
  manual-mode warning, restart/stop the portal, restart EmulationStation via
  `batocera-es-swissknife`, reboot and shutdown with confirmation.
- **Settings**: all paths editable, server port, RetroAchievements credentials with a test button.
- **Installer** `install.sh` with unattended options (`BP_PORT`, `BP_AUTOSTART`, `BP_NO_START`…).
- **Tests**: 77 pytest tests covering every backend module and the HTTP API end to end.

### Security notes
- No authentication. Intended for a trusted home network only.
- Every file path from the client is confined to its configured base folder.
- Request bodies are capped at 512 MB, BIOS downloads at 64 MB.
