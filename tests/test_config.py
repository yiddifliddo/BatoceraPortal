import json

from portal import config


def test_defaults_follow_base_dir(env):
    s = env["settings"]
    assert s["roms_base"] == str(env["base"] / "roms")
    assert s["server_port"] == 5000


def test_save_only_editable_keys(env):
    s = config.save_settings({"roms_base": "/x", "app_path": "/evil", "bogus": 1})
    assert s["roms_base"] == "/x"
    assert s["app_path"] != "/evil"
    saved = json.loads(config.settings_file().read_text())
    assert saved["roms_base"] == "/x"
    assert "bogus" not in saved


def test_bad_port_falls_back(env):
    config.settings_file().write_text(json.dumps({"server_port": "abc"}))
    assert config.load_settings()["server_port"] == 5000


def test_corrupt_settings_file_ignored(env):
    config.settings_file().write_text("{not json")
    assert config.load_settings()["server_port"] == 5000
