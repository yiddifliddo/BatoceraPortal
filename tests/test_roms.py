from portal import roms

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game><path>./Sonic.md</path><name>Sonic</name><desc>Fast.</desc><playcount>3</playcount><gametime>7200</gametime><lastplayed>20260101T120000</lastplayed><image>./images/Sonic-image.png</image></game>
  <game><path>./Hidden.md</path><name>Secret</name><hidden>true</hidden></game>
</gameList>
"""


def _make_md(env):
    d = env["base"] / "roms" / "megadrive"
    d.mkdir()
    (d / "Sonic.md").write_bytes(b"x" * 10)
    (d / "Hidden.md").write_bytes(b"y")
    (d / "notes.txt").write_text("ignored")
    (d / "images").mkdir()
    (d / "images" / "Sonic-image.png").write_bytes(b"\x89PNG")
    (d / "sub").mkdir()
    (d / "sub" / "Streets.zip").write_bytes(b"z")
    (d / "gamelist.xml").write_text(GAMELIST)
    return d


def test_scan_rom_systems(env):
    _make_md(env)
    (env["base"] / "roms" / "mystery").mkdir()
    (env["base"] / "roms" / "mystery" / "a.bin").write_bytes(b"1")
    out = roms.scan_rom_systems(env["settings"])
    by = {s["slug"]: s for s in out}
    md = by["megadrive"]
    assert md["rom_count"] == 3 and md["known"] and md["hardware"] == "console"
    assert md["gamelist_entries"] == 2 and md["subdirs"] == 1
    assert sorted(md["extensions"]) == [".md", ".zip"]
    assert by["mystery"]["known"] is False and by["mystery"]["rom_count"] == 1


def test_list_rom_folder_merges_gamelist(env):
    _make_md(env)
    out = roms.list_rom_folder(env["settings"], "megadrive")
    names = [e["name"] for e in out["entries"]]
    assert names == ["sub", "Hidden.md", "Sonic.md"]  # folders first, then sorted files
    sonic = next(e for e in out["entries"] if e["name"] == "Sonic.md")
    assert sonic["title"] == "Sonic" and sonic["has_image"] and sonic["playcount"] == "3"
    assert roms.list_rom_folder(env["settings"], "megadrive", "sub")["entries"][0]["name"] == "Streets.zip"
    assert roms.list_rom_folder(env["settings"], "megadrive", "nope") is None


def test_list_rom_folder_rejects_traversal(env):
    _make_md(env)
    import pytest
    with pytest.raises(ValueError):
        roms.list_rom_folder(env["settings"], "megadrive", "../")
    with pytest.raises(ValueError):
        roms.rom_dir(env["settings"], "../system")


def test_play_stats(env):
    _make_md(env)
    st = roms.play_stats(env["settings"])
    assert st["total_plays"] == 3 and st["total_hours"] == 2.0
    assert st["top"][0]["title"] == "Sonic"
    assert st["last_played"]["title"] == "Sonic"


def test_random_game_skips_hidden(env):
    _make_md(env)
    roms.invalidate_rom_cache()
    for _ in range(10):
        g = roms.random_game(env["settings"])
        assert g and g["title"] == "Sonic"
        assert g["image"].startswith("/api/roms/megadrive/image")


def test_rename_rom_updates_gamelist(env):
    d = _make_md(env)
    ok, info = roms.rename_rom(env["settings"], "megadrive", "Sonic.md", "Sonic (USA).md")
    assert ok and (d / "Sonic (USA).md").exists()
    assert "./Sonic (USA).md" in (d / "gamelist.xml").read_text()
    ok, info = roms.rename_rom(env["settings"], "megadrive", "Hidden.md", "Sonic (USA).md")
    assert not ok and "exists" in info["error"]
    ok, info = roms.rename_rom(env["settings"], "megadrive", "Hidden.md", "../x.md")
    assert not ok


def test_update_meta_creates_and_edits(env):
    d = _make_md(env)
    (d / "gamelist.xml").unlink()
    ok, _ = roms.update_game_meta(env["settings"], "megadrive", "Sonic.md", {"name": "Sonic 1", "rating": "0.9", "bogus": "no"})
    assert ok
    games = roms.parse_gamelist(d / "gamelist.xml")
    assert games["Sonic.md"]["name"] == "Sonic 1" and "bogus" not in games["Sonic.md"]
    ok, _ = roms.update_game_meta(env["settings"], "megadrive", "Sonic.md", {"rating": ""})
    assert "rating" not in roms.parse_gamelist(d / "gamelist.xml")["Sonic.md"]
    ok, info = roms.update_game_meta(env["settings"], "megadrive", "missing.md", {"name": "x"})
    assert not ok


def test_save_and_delete_media(env):
    d = _make_md(env)
    ok, info = roms.save_media(env["settings"], "megadrive", "Hidden.md", "box", b"\x89PNGdata", "png")
    assert ok and (d / "images" / "Hidden-box.png").exists()
    assert roms.parse_gamelist(d / "gamelist.xml")["Hidden.md"]["thumbnail"] == "./images/Hidden-box.png"
    media = roms.image_info(env["settings"], "megadrive", "Hidden.md")["media"]
    assert [m["type"] for m in media] == ["box"]
    ok, _ = roms.delete_media(env["settings"], "megadrive", "images/Hidden-box.png")
    assert ok and not (d / "images" / "Hidden-box.png").exists()
    ok, info = roms.delete_media(env["settings"], "megadrive", "Hidden.md")
    assert not ok  # not a media file


def test_media_path_naming(tmp_path):
    assert roms.media_path(tmp_path, "Sonic", "box").name == "Sonic-box.png"
    assert roms.media_path(tmp_path, "Sonic", "video", ".mp4").parent.name == "videos"
