import pytest

from portal import util


def test_safe_slug():
    assert util.is_safe_slug("megadrive-hacks")
    assert util.is_safe_slug("snes_2")
    assert not util.is_safe_slug("Mega Drive")
    assert not util.is_safe_slug("../etc")
    assert not util.is_safe_slug("")
    assert not util.is_safe_slug("-leading")


def test_safe_component():
    assert util.is_safe_component("Sonic (USA).md")
    assert not util.is_safe_component("..")
    assert not util.is_safe_component("a/b")
    assert not util.is_safe_component("a\\b")


def test_confine_blocks_traversal(tmp_path):
    inside = util.confine(tmp_path, "roms", "snes")
    assert str(inside).startswith(str(tmp_path))
    with pytest.raises(ValueError):
        util.confine(tmp_path, "..", "etc", "passwd")
    with pytest.raises(ValueError):
        util.confine(tmp_path, "roms/../../x")


def test_confine_strips_leading_slash(tmp_path):
    assert util.confine(tmp_path, "/abs/path") == (tmp_path / "abs" / "path").resolve()


def test_sanitize_conf_value():
    assert util.sanitize_conf_value(" libretro ") == "libretro"
    with pytest.raises(ValueError):
        util.sanitize_conf_value("x\ny")
    with pytest.raises(ValueError):
        util.sanitize_conf_value("a b")


def test_human_size():
    assert util.human_size(0) == "0 B"
    assert util.human_size(1536) == "1.5 KB"
    assert util.human_size(5 * 1024 ** 3) == "5.0 GB"
    assert util.human_size("junk") == "0 B"


def test_md5_and_crc(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    assert util.md5_file(p) == "5d41402abc4b2a76b9719d911017c592"
    assert util.crc32_file(p) == "3610a686"


def test_parse_multipart():
    boundary = "XXboundaryXX"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"system\"\r\n\r\nsnes\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"../logo.png\"\r\n"
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + b"\x89PNG\r\n\x1a\nDATA" + f"\r\n--{boundary}--\r\n".encode()
    out = util.parse_multipart(f"multipart/form-data; boundary={boundary}", body)
    assert out["fields"] == {"system": "snes"}
    assert len(out["files"]) == 1
    assert out["files"][0]["filename"] == "logo.png"  # basename only
    assert out["files"][0]["data"] == b"\x89PNG\r\n\x1a\nDATA"


def test_parse_multipart_rejects_other_types():
    with pytest.raises(ValueError):
        util.parse_multipart("application/json", b"{}")
