
from portal import bios

SCRIPT = '''#!/usr/bin/env python3
import sys
# comment with { brace
systems = {
    "atari5200": { "name": "Atari 5200", "biosFiles": [ { "md5": "%s", "file": "bios/5200.rom" } ] },
    "neogeo":    { "name": "Neo Geo",    "biosFiles": [ { "md5": "", "file": "bios/neogeo.zip" } ] },
    "psx":       { "name": "PlayStation", "biosFiles": [ { "md5": "aaaa", "file": "bios/scph1001.bin" } ] },
}
class Foo: pass
'''


def _script(env, md5="5d41402abc4b2a76b9719d911017c592"):
    p = env["tmp"] / "batocera-systems"
    p.write_text(SCRIPT % md5)
    return p


def test_extract_dict_literal():
    lit = bios._extract_dict_literal(SCRIPT % "x", "systems")
    assert lit.startswith("{") and lit.endswith("}") and '"psx"' in lit
    assert bios._extract_dict_literal("nothing here", "systems") is None


def test_load_db_from_script(env):
    db, source = bios.load_bios_db(_script(env), force=True)
    assert set(db) == {"atari5200", "neogeo", "psx"} and source.endswith("batocera-systems")


def test_load_db_fallback(env):
    db, source = bios.load_bios_db(env["tmp"] / "missing", force=True)
    assert source == "fallback" and "psx" in db


def test_check_all(env, monkeypatch):
    monkeypatch.setattr(bios, "BATOCERA_SYSTEMS_SCRIPT", str(_script(env)))
    bios.load_bios_db(str(_script(env)), force=True)
    (env["base"] / "bios" / "5200.rom").write_bytes(b"hello")        # md5 matches
    (env["base"] / "bios" / "scph1001.bin").write_bytes(b"wrong")    # mismatch
    out = bios.check_all(env["settings"])
    by = {s["slug"]: s for s in out["systems"]}
    assert by["atari5200"]["complete"] and by["atari5200"]["files"][0]["status"] == "ok"
    assert by["psx"]["files"][0]["status"] == "mismatch" and by["psx"]["mismatch"] == 1
    assert by["neogeo"]["files"][0]["status"] == "missing" and by["neogeo"]["files"][0]["optional"]
    assert out["summary"]["missing_files"] == 1 and out["summary"]["mismatched_files"] == 1


def test_skip_list(env):
    bios.load_bios_db(str(_script(env)), force=True)
    bios.set_skipped(env["settings"], "neogeo:bios/neogeo.zip", True)
    out = bios.check_all(env["settings"], only_slugs={"neogeo"})
    assert out["systems"][0]["complete"] and out["systems"][0]["files"][0]["skipped"]
    bios.set_skipped(env["settings"], "neogeo:bios/neogeo.zip", False)
    assert not bios.check_all(env["settings"], only_slugs={"neogeo"})["systems"][0]["complete"]


def test_missing_for_installed_filters(env):
    bios.load_bios_db(str(_script(env)), force=True)
    out = bios.missing_for_installed(env["settings"], ["psx"])
    assert [s["slug"] for s in out["systems"]] == ["psx"]


def test_upload_verifies_md5(env):
    bios.load_bios_db(str(_script(env)), force=True)
    ok, info = bios.save_uploaded_bios(env["settings"], "bios/5200.rom", b"hello")
    assert ok and info["verified"] is True
    ok, info = bios.save_uploaded_bios(env["settings"], "bios/5200.rom", b"nope")
    assert ok and info["verified"] is False
    ok, info = bios.save_uploaded_bios(env["settings"], "bios/sub/x.bin", b"anything")
    assert ok and info["verified"] is None and (env["base"] / "bios" / "sub" / "x.bin").exists()
    ok, info = bios.save_uploaded_bios(env["settings"], "../etc/passwd", b"x")
    assert not ok


def test_download_rejects_bad_scheme(env):
    ok, info = bios.download_bios(env["settings"], "bios/x.bin", "ftp://host/x")
    assert not ok


def test_download_discards_mismatch(env, monkeypatch):
    bios.load_bios_db(str(_script(env)), force=True)

    class FakeResp:
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n=-1): return b"not hello"

    monkeypatch.setattr(bios.urllib.request, "urlopen", lambda *a, **k: FakeResp())
    ok, info = bios.download_bios(env["settings"], "bios/5200.rom", "https://example.org/5200.rom")
    assert not ok and not (env["base"] / "bios" / "5200.rom").exists()

    class GoodResp(FakeResp):
        def read(self, n=-1): return b"hello"

    monkeypatch.setattr(bios.urllib.request, "urlopen", lambda *a, **k: GoodResp())
    ok, info = bios.download_bios(env["settings"], "bios/5200.rom", "https://example.org/5200.rom")
    assert ok and info["verified"] is True
