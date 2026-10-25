import xml.etree.ElementTree as ET

from portal import systems

PAYLOAD = {
    "fullname": "Mega Drive Hacks", "name": "md-hacks", "manufacturer": "Sega", "release": "1988",
    "hardware": "console", "rompath": "/userdata/roms/md-hacks", "extensions": ".md .bin",
    "platform": "megadrive", "theme": "megadrive", "emulator": "libretro", "core": "genesisplusgx",
    "extra_cores": "picodrive, genesisplusgx", "description": "Rom hacks",
}


def test_build_xml_structure(env):
    xml = systems.build_xml(PAYLOAD, env["settings"])
    root = ET.fromstring(xml)
    sys_el = root.find("system")
    assert sys_el.findtext("name") == "md-hacks"
    assert sys_el.findtext("path") == "/userdata/roms/md-hacks"
    assert "emulatorlauncher" in sys_el.findtext("command")
    cores = [c.text for c in sys_el.find("emulators/emulator/cores").findall("core")]
    assert cores == ["genesisplusgx", "picodrive"]  # default first, no duplicate
    default = sys_el.find("emulators/emulator/cores/core[@default='true']")
    assert default.text == "genesisplusgx"


def test_build_xml_custom_command_and_no_emulator(env):
    d = dict(PAYLOAD, command="bash %ROM%", emulator="", core="")
    root = ET.fromstring(systems.build_xml(d, env["settings"]))
    assert root.find("system").findtext("command") == "bash %ROM%"
    assert root.find("system/emulators") is None


def test_validate_payload():
    assert systems.validate_payload(PAYLOAD) == []
    errs = systems.validate_payload({"fullname": "", "name": "Bad Slug", "rompath": "", "extensions": ""})
    assert len(errs) == 4
    assert any("hardware" in e for e in systems.validate_payload(dict(PAYLOAD, hardware="toaster")))


def test_catalogue_from_builtin(env):
    cat = systems.load_catalogue(env["settings"], force=True)
    assert set(cat) == {"megadrive", "gba"}
    assert cat["megadrive"]["emulators"][0]["default_core"] == "genesisplusgx"
    assert cat["megadrive"]["emulators"][0]["cores"] == ["genesisplusgx", "picodrive"]


def test_catalogue_missing_file(env):
    s = dict(env["settings"], es_builtin_cfg="/nope/es_systems.cfg")
    assert systems.load_catalogue(s, force=True) == {}


def test_create_list_update_delete(env):
    s = env["settings"]
    ok, info = systems.write_custom_system(s, dict(PAYLOAD, batocera_conf_entry=True, create_roms_dir=False))
    assert ok, info
    cfg = env["base"] / "system/configs/emulationstation/es_systems_md-hacks.cfg"
    assert cfg.exists()
    conf = (env["base"] / "system/batocera.conf").read_text()
    assert "md-hacks.emulator=libretro" in conf and "md-hacks.core=genesisplusgx" in conf

    listed = systems.list_custom_systems(s)
    assert [x["name"] for x in listed] == ["md-hacks"]
    detail = systems.get_custom_system(s, "md-hacks")
    assert detail["fullname"] == "Mega Drive Hacks" and "<systemList>" in detail["xml"]

    ok, info = systems.write_custom_system(s, dict(PAYLOAD, name="md-hacks2"), old_slug="md-hacks")
    assert ok
    assert not cfg.exists()
    assert (cfg.parent / "es_systems_md-hacks2.cfg").exists()

    ok, info = systems.delete_custom_system(s, "md-hacks2")
    assert ok
    assert systems.list_custom_systems(s) == []
    assert "md-hacks.emulator" not in (env["base"] / "system/batocera.conf").read_text()


def test_rename_refuses_to_clobber(env):
    s = env["settings"]
    assert systems.write_custom_system(s, dict(PAYLOAD, name="a"))[0]
    assert systems.write_custom_system(s, dict(PAYLOAD, name="b"))[0]
    ok, info = systems.write_custom_system(s, dict(PAYLOAD, name="b"), old_slug="a")
    assert not ok and "already exists" in info["errors"][0]


def test_dry_run_writes_nothing(env):
    s = env["settings"]
    ok, info = systems.write_custom_system(s, PAYLOAD, dry_run=True)
    assert ok and info["dry_run"]
    assert not list((env["base"] / "system/configs/emulationstation").glob("*.cfg"))


def test_create_roms_dir_inside_base(env):
    s = env["settings"]
    d = dict(PAYLOAD, rompath=str(env["base"] / "roms" / "md-hacks"), create_roms_dir=True)
    ok, info = systems.write_custom_system(s, d)
    assert ok and (env["base"] / "roms" / "md-hacks").is_dir()


def test_create_roms_dir_outside_base_refused(env):
    s = env["settings"]
    d = dict(PAYLOAD, rompath=str(env["tmp"] / "elsewhere"), create_roms_dir=True)
    ok, info = systems.write_custom_system(s, d)
    assert ok and not (env["tmp"] / "elsewhere").exists()
    assert any("outside" in line for line in info["log"])


def test_delete_unknown(env):
    ok, info = systems.delete_custom_system(env["settings"], "nothing")
    assert not ok
    ok, info = systems.delete_custom_system(env["settings"], "../x")
    assert not ok
