import base64
import json
import threading
from http.client import HTTPConnection

import pytest

from portal import auth, server


def _reset():
    auth._sessions.clear()
    auth._failures.clear()


def test_default_password_until_changed(env):
    _reset()
    assert auth.password_is_default()
    assert auth.verify_password("linuxrox")
    assert not auth.verify_password("LINUXROX")
    assert not auth.verify_password("")
    ok, err = auth.set_password("newpass1")
    assert ok and err is None
    assert not auth.password_is_default()
    assert auth.verify_password("newpass1")
    assert not auth.verify_password("linuxrox")


def test_set_password_rules(env):
    assert auth.set_password("abc")[0] is False
    assert auth.set_password("x" * 200)[0] is False
    assert auth.set_password("good-one")[0] is True


def test_hash_is_salted_and_never_stored_plain(env):
    auth.set_password("secretpw")
    raw = json.loads(open(env["tmp"] / "settings.json").read())
    assert "secretpw" not in json.dumps(raw)
    assert len(raw["password_hash"]) == 64 and len(raw["password_salt"]) == 32
    d1, s1 = auth.hash_password("a")
    d2, s2 = auth.hash_password("a")
    assert s1 != s2 and d1 != d2


def test_sessions_and_logout():
    _reset()
    tok = auth.create_session()
    assert auth.session_valid(tok)
    assert not auth.session_valid("nope") and not auth.session_valid(None)
    auth.destroy_session(tok)
    assert not auth.session_valid(tok)


def test_changing_password_clears_sessions(env):
    _reset()
    tok = auth.create_session()
    auth.set_password("another1")
    assert not auth.session_valid(tok)


def test_lockout_after_failures():
    _reset()
    for _ in range(auth.MAX_FAILURES - 1):
        auth.record_failure("1.2.3.4")
    assert auth.locked_for("1.2.3.4") == 0
    auth.record_failure("1.2.3.4")
    assert auth.locked_for("1.2.3.4") > 0
    assert auth.locked_for("5.6.7.8") == 0
    auth.clear_failures("1.2.3.4")
    assert auth.locked_for("1.2.3.4") == 0


def test_header_parsing():
    assert auth.parse_cookies("a=1; bp_session=xyz; c=d=e") == {"a": "1", "bp_session": "xyz", "c": "d=e"}
    good = "Basic " + base64.b64encode(b"anyuser:linuxrox").decode()
    assert auth.basic_auth_password(good) == "linuxrox"
    assert auth.basic_auth_password("Basic !!!notbase64") is None
    assert auth.basic_auth_password("Bearer x") is None
    assert auth.basic_auth_password(None) is None


# ---------------------------------------------------------------- HTTP level
@pytest.fixture
def raw_client(env):
    _reset()
    httpd = server.serve("127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    def call(method, path, body=None, headers=None):
        c = HTTPConnection("127.0.0.1", port, timeout=10)
        data = json.dumps(body).encode() if body is not None else None
        h = dict(headers or {})
        if data:
            h["Content-Type"] = "application/json"
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        payload = r.read()
        try:
            payload = json.loads(payload)
        except ValueError:
            pass
        return r.status, payload, r.getheader("Set-Cookie")
    yield call
    httpd.shutdown()
    httpd.server_close()


def test_api_requires_auth(raw_client):
    status, body, _ = raw_client("GET", "/api/info")
    assert status == 401 and body["login"] == "/login"
    status, body, _ = raw_client("POST", "/api/systems", {"name": "x"})
    assert status == 401
    status, body, _ = raw_client("DELETE", "/api/systems/x")
    assert status == 401


def test_root_shows_login_page_when_signed_out(raw_client):
    status, body, _ = raw_client("GET", "/")
    assert status == 200 and b"Sign in" in body and b"panel-dashboard" not in body
    status, body, _ = raw_client("GET", "/static/app.css")
    assert status == 200


def test_login_cookie_flow(raw_client):
    status, body, cookie = raw_client("POST", "/api/login", {"password": "wrong"})
    assert status == 401 and cookie is None
    status, body, cookie = raw_client("POST", "/api/login", {"password": "linuxrox"})
    assert status == 200 and body["password_is_default"] is True
    assert cookie.startswith("bp_session=") and "HttpOnly" in cookie
    token = cookie.split(";")[0]
    status, body, _ = raw_client("GET", "/api/info", headers={"Cookie": token})
    from portal import __version__
    assert status == 200 and body["version"] == __version__
    status, body, _ = raw_client("GET", "/", headers={"Cookie": token})
    assert b"panel-dashboard" in body
    status, body, cleared = raw_client("POST", "/api/logout", headers={"Cookie": token})
    assert status == 200 and "Max-Age=0" in cleared
    status, body, _ = raw_client("GET", "/api/info", headers={"Cookie": token})
    assert status == 401


def test_basic_auth_for_scripts(raw_client):
    h = {"Authorization": "Basic " + base64.b64encode(b":linuxrox").decode()}
    assert raw_client("GET", "/api/info", headers=h)[0] == 200
    bad = {"Authorization": "Basic " + base64.b64encode(b":nope").decode()}
    assert raw_client("GET", "/api/info", headers=bad)[0] == 401


def test_lockout_over_http(raw_client):
    for _ in range(auth.MAX_FAILURES):
        raw_client("POST", "/api/login", {"password": "bad"})
    status, body, _ = raw_client("POST", "/api/login", {"password": "linuxrox"})
    assert status == 429 and "Try again" in body["error"]


def test_change_password_over_http(raw_client, env):
    h = {"Authorization": "Basic " + base64.b64encode(b":linuxrox").decode()}
    status, body, _ = raw_client("POST", "/api/password", {"current": "bad", "new": "newpass1", "confirm": "newpass1"}, h)
    assert status == 401
    status, body, _ = raw_client("POST", "/api/password", {"current": "linuxrox", "new": "newpass1", "confirm": "other"}, h)
    assert status == 400
    status, body, cookie = raw_client("POST", "/api/password", {"current": "linuxrox", "new": "newpass1", "confirm": "newpass1"}, h)
    assert status == 200 and body["changed"] and cookie
    assert raw_client("GET", "/api/info", headers=h)[0] == 401
    h2 = {"Authorization": "Basic " + base64.b64encode(b":newpass1").decode()}
    status, body, _ = raw_client("GET", "/api/settings", headers=h2)
    assert status == 200 and "password_hash" not in body["settings"] and body["settings"]["password_is_default"] is False


def test_settings_endpoint_cannot_set_hash(raw_client):
    h = {"Authorization": "Basic " + base64.b64encode(b":linuxrox").decode()}
    status, body, _ = raw_client("POST", "/api/settings", {"password_hash": "00", "password_salt": "00"}, h)
    assert status == 200
    assert auth.verify_password("linuxrox")
