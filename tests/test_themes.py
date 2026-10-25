from portal import themes

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 10


def test_active_theme_sources(env):
    s = env["settings"]
    assert themes.detect_active_theme(s) == "es-theme-carbon"
    (env["base"] / "system" / "batocera.conf").write_text("global.theme=mytheme\n")
    assert themes.detect_active_theme(s) == "mytheme"
    (env["base"] / "system/configs/emulationstation/es_settings.cfg").write_text(
        '<config><string name="ThemeSet" value="es-theme-alekfull" /></config>')
    assert themes.detect_active_theme(s) == "es-theme-alekfull"


def test_list_and_logo_upload(env):
    s = env["settings"]
    (env["base"] / "themes" / "mytheme").mkdir()
    (env["base"] / "themes" / "mytheme" / "theme.xml").write_text("<theme/>")
    lst = themes.list_themes(s)
    assert lst == [{"name": "mytheme", "path": str(env["base"] / "themes" / "mytheme"), "origin": "user", "has_theme_xml": True}]
    ok, info = themes.save_system_logo(s, "snes", PNG, theme="mytheme")
    assert ok and info["path"].endswith("mytheme/snes/art/logo.png")
    assert themes.find_system_logo(s, "snes", "mytheme") == info["path"]
    assert themes.find_system_logo(s, "nes", "mytheme") is None


def test_logo_validation(env):
    s = env["settings"]
    (env["base"] / "themes" / "t").mkdir()
    assert themes.save_system_logo(s, "snes", b"GIF89a", theme="t")[0] is False
    assert themes.save_system_logo(s, "../x", PNG, theme="t")[0] is False
    assert themes.save_system_logo(s, "snes", PNG, theme="missing")[0] is False
    assert themes.save_system_logo(s, "snes", b"<svg xmlns='x'></svg>", theme="t")[1]["path"].endswith("logo.svg")


def test_logo_only_into_user_themes(env, tmp_path):
    s = dict(env["settings"], themes_sys=str(tmp_path / "sys"))
    (tmp_path / "sys" / "carbon").mkdir(parents=True)
    ok, info = themes.save_system_logo(s, "snes", PNG, theme="carbon")
    assert not ok and "user theme" in info["error"]
