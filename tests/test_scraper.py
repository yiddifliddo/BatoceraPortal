from portal import scraper


def test_clean_rom_name():
    assert scraper.clean_rom_name("Sonic The Hedgehog (USA, Europe) [!].md") == "Sonic The Hedgehog"
    assert scraper.clean_rom_name("Final_Fantasy.VII.Disc1 (v1.1).chd") == "Final Fantasy VII"


def test_config_roundtrip_masks_secrets(env):
    s = env["settings"]
    ok, cfg = scraper.save_config(s, {"ss_user": "dan", "ss_pass": "secret", "tgdb_key": "ABCDEFGH1234", "region": "eu"})
    assert ok and cfg["ss_user"] == "dan" and cfg["ss_pass"] == "********" and cfg["tgdb_key"].endswith("1234")
    conf = (env["base"] / "system/batocera.conf").read_text()
    assert "global.scraper.screenscraper.password=secret" in conf
    # masked values are not written back
    ok, cfg = scraper.save_config(s, {"ss_pass": "********", "ss_user": "dan2"})
    assert "password=secret" in (env["base"] / "system/batocera.conf").read_text()
    assert cfg["ss_user"] == "dan2" and cfg["region"] == "eu"
    # empty value removes the line
    scraper.save_config(s, {"tgdb_key": ""})
    assert "thegamesdb" not in (env["base"] / "system/batocera.conf").read_text()


def test_config_rejects_newlines(env):
    ok, info = scraper.save_config(env["settings"], {"ss_user": "a\nb"})
    assert not ok


def test_ss_parse_json_repairs_bad_escapes():
    assert scraper.ss_parse_json(b'{"a": "x\\y"}') == {"a": "x\\y"}


def test_ss_build_result_picks_region_and_language():
    jeu = {
        "id": "1", "noms": [{"region": "jp", "text": "Sonikku"}, {"region": "wor", "text": "Sonic"}],
        "synopsis": [{"langue": "fr", "text": "Rapide"}, {"langue": "en", "text": "Fast"}],
        "genres": [{"noms": [{"langue": "en", "text": "Platform"}]}],
        "dates": [{"region": "wor", "text": "1991-06-23"}], "note": {"text": "16"},
        "joueurs": {"text": "1-2"}, "developpeur": {"text": "Sonic Team"}, "editeur": {"text": "Sega"},
        "medias": [{"type": "ss", "region": "us", "url": "http://x/ss-us", "format": "png"},
                   {"type": "ss", "region": "wor", "url": "http://x/ss-wor", "format": "png"},
                   {"type": "box-2D", "region": "eu", "url": "http://x/box", "format": "jpg"}],
    }
    r = scraper.ss_build_result(jeu, "en", "wor")
    assert r["name"] == "Sonic" and r["desc"] == "Fast" and r["genre"] == "Platform"
    assert r["releasedate"] == "19910623T000000" and r["rating"] == "0.80"
    assert r["media"]["image"]["url"] == "http://x/ss-wor"
    assert r["media"]["box"]["url"] == "http://x/box"


def test_search_requires_credentials(env):
    (env["base"] / "roms" / "megadrive").mkdir()
    (env["base"] / "roms" / "megadrive" / "a.md").write_bytes(b"x")
    r, info = scraper.search(env["settings"], "megadrive", "a.md", "screenscraper")
    assert r is None and "ScreenScraper" in info["error"]
    r, info = scraper.search(env["settings"], "megadrive", "a.md", "thegamesdb")
    assert r is None and "TheGamesDB" in info["error"]


def test_apply_result_writes_media_and_meta(env, monkeypatch):
    d = env["base"] / "roms" / "megadrive"
    d.mkdir()
    (d / "Sonic.md").write_bytes(b"x")
    monkeypatch.setattr(scraper, "_get", lambda url, timeout=25, headers=None: b"\x89PNG" + b"0" * 100)
    result = {"name": "Sonic", "desc": "Fast", "media": {"image": {"url": "http://x/1", "format": "png"},
                                                         "box": {"url": "http://x/2", "format": "jpeg"}}}
    out = scraper.apply_result(env["settings"], "megadrive", "Sonic.md", result, ["image", "box", "wheel"])
    assert out["saved"] == {"image": "images/Sonic-image.png", "box": "images/Sonic-box.jpg"}
    assert "name" in out["meta"] and "thumbnail" in out["meta"]
    from portal.roms import parse_gamelist
    g = parse_gamelist(d / "gamelist.xml")["Sonic.md"]
    assert g["image"] == "./images/Sonic-image.png" and g["name"] == "Sonic"
    # existing file is kept unless overwrite
    (d / "images" / "Sonic-image.png").write_bytes(b"orig")
    scraper.apply_result(env["settings"], "megadrive", "Sonic.md", result, ["image"])
    assert (d / "images" / "Sonic-image.png").read_bytes() == b"orig"
    scraper.apply_result(env["settings"], "megadrive", "Sonic.md", result, ["image"], overwrite=True)
    assert (d / "images" / "Sonic-image.png").read_bytes() != b"orig"


def test_list_roms_for_scrape(env):
    d = env["base"] / "roms" / "megadrive"
    (d / "sub").mkdir(parents=True)
    (d / "images").mkdir()
    (d / "a.md").write_bytes(b"x"); (d / "sub" / "b.zip").write_bytes(b"x"); (d / "images" / "c.md").write_bytes(b"x")
    (d / "readme.txt").write_text("x")
    assert scraper.list_roms_for_scrape(env["settings"], "megadrive") == ["a.md", "sub/b.zip"]


def test_batch_job_lifecycle(env, monkeypatch):
    d = env["base"] / "roms" / "megadrive"
    d.mkdir()
    (d / "a.md").write_bytes(b"x")
    monkeypatch.setattr(scraper, "search", lambda s, slug, rel, src: ({"name": "A", "media": {}}, {}))
    monkeypatch.setattr(scraper, "_ensure_worker", lambda s: None)
    job_id = scraper.start_batch(env["settings"], ["megadrive", "../bad"], "screenscraper", ["image"])
    job = next(j for j in scraper._jobs.values() if j["id"] == job_id)
    scraper._run_job(env["settings"], job)
    assert job["status"] == "completed" and job["ok"] == 1 and job["total"] == 1
    assert any("invalid" in e for e in job["errors"])
    assert scraper.cancel_job("nope") is False
