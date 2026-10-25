import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SAMPLE_ES_SYSTEMS = """<?xml version="1.0"?>
<systemList>
  <system>
    <name>megadrive</name>
    <fullname>Sega Mega Drive</fullname>
    <manufacturer>Sega</manufacturer>
    <release>1988</release>
    <hardware>console</hardware>
    <path>/userdata/roms/megadrive</path>
    <extension>.md .bin .zip .7z</extension>
    <command>python3 /usr/lib/python3.12/site-packages/configgen/emulatorlauncher.py %CONTROLLERSCONFIG% -system %SYSTEM% -rom %ROM%</command>
    <platform>megadrive</platform>
    <theme>megadrive</theme>
    <emulators>
      <emulator name="libretro">
        <cores><core default="true">genesisplusgx</core><core>picodrive</core></cores>
      </emulator>
    </emulators>
  </system>
  <system>
    <name>gba</name>
    <fullname>Game Boy Advance</fullname>
    <manufacturer>Nintendo</manufacturer>
    <hardware>portable</hardware>
    <path>/userdata/roms/gba</path>
    <extension>.gba .zip</extension>
    <command>x</command>
    <platform>gba</platform>
    <theme>gba</theme>
  </system>
</systemList>
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A fake Batocera tree with settings pointing into it."""
    base = tmp_path / "userdata"
    (base / "system" / "configs" / "emulationstation").mkdir(parents=True)
    (base / "roms").mkdir()
    (base / "bios").mkdir()
    (base / "themes").mkdir()
    builtin = tmp_path / "es_systems.cfg"
    builtin.write_text(SAMPLE_ES_SYSTEMS, encoding="utf-8")
    monkeypatch.setenv("BP_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setenv("BP_BASE_DIR", str(base))
    from portal import config, systems, roms, bios
    systems.invalidate_catalogue()
    roms.invalidate_rom_cache()
    bios._DB_CACHE.update({"data": None, "source": None})
    s = config.load_settings()
    s["es_builtin_cfg"] = str(builtin)
    s["app_path"] = str(tmp_path / "app.py")
    return {"settings": s, "base": base, "tmp": tmp_path}
