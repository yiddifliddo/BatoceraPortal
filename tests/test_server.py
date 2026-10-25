import base64
import json
import threading
from http.client import HTTPConnection

import pytest

from portal import server


@pytest.fixture
def client(env, monkeypatch):
    httpd = server.serve("127.0.0.1", 0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    port = httpd.server_address[1]

    def call(method, path, body=None, raw=None, ctype="application/json"):
        c = HTTPConnection("127.0.0.1", port, timeout=10)
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        headers = {"Content-Type": ctype} if data else {}
        headers["Authorization"] = "Basic " + base64.b64encode(b":linuxrox").decode()
        c.request(method, path, body=data, headers=headers)
        r = c.getresponse()
        payload = r.read()
        try:
            return r.status, json.loads(payload)
        except ValueError:
            return r.status, payload
    yield call
    httpd.shutdown()
    httpd.server_close()


def test_index_and_static(client):
    status, body = client("GET", "/")
    assert status == 200 and b"Batocera Portal" in body and b"{{app_version}}" not in body
    status, body = client("GET", "/static/app.css")
    assert status == 200 and b":root" in body
    status, body = client("GET", "/static/../app.py")
    assert status in (400, 404)


def test_info_and_404(client):
    status, body = client("GET", "/api/info")
    assert status == 200 and body["ok"] and body["author"] == "Dan Lee" and body["version"]
    status, body = client("GET", "/api/nothing")
    assert status == 404 and body["ok"] is False


def test_system_crud_over_http(client, env):
    payload = {"fullname": "Test", "name": "testsys", "rompath": "/userdata/roms/testsys",
               "extensions": ".zip", "emulator": "libretro", "core": "x", "create_roms_dir": False}
    status, body = client("POST", "/api/systems/preview", payload)
    assert status == 200 and "<name>testsys</name>" in body["xml"] and body["errors"] == []
    status, body = client("POST", "/api/systems", payload)
    assert status == 200 and body["ok"]
    status, body = client("GET", "/api/systems")
    assert [s["name"] for s in body["systems"]] == ["testsys"]
    status, body = client("GET", "/api/systems/testsys")
    assert status == 200 and body["system"]["fullname"] == "Test"
    status, body = client("PUT", "/api/systems/testsys", dict(payload, fullname="Renamed"))
    assert status == 200
    status, body = client("POST", "/api/systems", dict(payload, name="BAD NAME"))
    assert status == 400 and body["errors"]
    status, body = client("DELETE", "/api/systems/testsys")
    assert status == 200
    status, body = client("DELETE", "/api/systems/testsys")
    assert status == 404


def test_bad_json_is_400(client):
    status, body = client("POST", "/api/systems", raw=b"{broken")
    assert status == 400 and "JSON" in body["error"]


def test_settings_validation(client):
    status, body = client("POST", "/api/settings", {"server_port": "99999"})
    assert status == 400
    status, body = client("POST", "/api/settings", {"server_port": 8080, "ra_api_key": "k"})
    assert status == 200 and body["settings"]["server_port"] == 8080 and body["settings"]["ra_api_key"] == "********"


def test_logo_upload_multipart(client, env):
    (env["base"] / "themes" / "t").mkdir()
    boundary = "bnd"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"system\"\r\n\r\nsnes\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"theme\"\r\n\r\nt\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"l.png\"\r\n\r\n").encode() \
        + b"\x89PNG\r\n\x1a\nxx" + f"\r\n--{boundary}--\r\n".encode()
    status, resp = client("POST", "/api/themes/logo", raw=body, ctype=f"multipart/form-data; boundary={boundary}")
    assert status == 200 and resp["path"].endswith("t/snes/art/logo.png")
    status, resp = client("GET", "/api/themes/logo/snes?theme=t")
    assert status == 200 and resp.startswith(b"\x89PNG")


def test_service_autostart_endpoint(client, env):
    status, body = client("POST", "/api/service/autostart", {"enabled": True})
    assert status == 200 and body["autostart"]["registered"]
    status, body = client("GET", "/api/service/status")
    assert body["process"]["manual_mode"] is False
    status, body = client("POST", "/api/service/autostart", {"enabled": False})
    assert body["removed"] is True


def test_rom_endpoints(client, env):
    d = env["base"] / "roms" / "gba"
    d.mkdir()
    (d / "game.gba").write_bytes(b"x")
    status, body = client("GET", "/api/roms?force=1")
    assert status == 200 and body["systems"][0]["slug"] == "gba"
    status, body = client("GET", "/api/roms/gba")
    assert body["entries"][0]["name"] == "game.gba"
    status, body = client("POST", "/api/roms/gba/meta", {"rom": "game.gba", "meta": {"name": "My Game"}})
    assert status == 200
    status, body = client("GET", "/api/roms/gba?path=../")
    assert status == 400
    status, body = client("GET", "/api/stats")
    assert status == 200 and body["total_plays"] == 0


def test_bios_endpoints(client, env):
    status, body = client("GET", "/api/bios")
    assert status == 200 and "summary" in body
    status, body = client("POST", "/api/bios/skip", {"key": "psx:bios/scph1001.bin"})
    assert status == 200 and "psx:bios/scph1001.bin" in body["skipped"]
    status, body = client("POST", "/api/bios/skip", {"key": "nocolon"})
    assert status == 400
