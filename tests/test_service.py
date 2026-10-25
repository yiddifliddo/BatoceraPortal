from portal import service


def test_service_cmd_quotes_and_validates_port(env):
    s = dict(env["settings"], app_path="/userdata/system/my portal/app.py", server_port=99999)
    cmd = service.service_cmd(s)
    assert cmd == "python3 '/userdata/system/my portal/app.py' --port 5000"


def test_autostart_roundtrip(env):
    s = env["settings"]
    assert service.autostart_status(s)["registered"] is False
    st = service.install_autostart(s)
    assert st["registered"] and st["cmd"].startswith("python3 ")
    content = open(s["custom_sh"]).read()
    assert content.startswith("#!/bin/bash")
    assert content.count(service.MARKER_START) == 1
    # re-install replaces, never duplicates
    service.install_autostart(s, cmd="python3 /other/app.py --port 8080")
    content = open(s["custom_sh"]).read()
    assert content.count(service.MARKER_START) == 1 and "--port 8080" in content
    assert service.remove_autostart(s) is True
    assert service.MARKER_START not in open(s["custom_sh"]).read()
    assert service.remove_autostart(s) is False


def test_autostart_keeps_user_lines(env):
    s = env["settings"]
    with open(s["custom_sh"], "w") as f:
        f.write("#!/bin/bash\n# user stuff\nmount /dev/sda1 /mnt\n")
    service.install_autostart(s)
    service.remove_autostart(s)
    assert open(s["custom_sh"]).read() == "#!/bin/bash\n# user stuff\nmount /dev/sda1 /mnt\n"


def test_process_status_reports_manual_mode(env):
    st = service.process_status(env["settings"])
    assert st["manual_mode"] is True and st["pid"] > 0


def test_es_restart_without_binary(monkeypatch):
    monkeypatch.setattr(service.shutil, "which", lambda _: None)
    ok, info = service.restart_emulationstation()
    assert not ok and "swissknife" in info["error"]


def test_es_restart_pending_flag():
    service.mark_es_restart_pending(True)
    assert service.es_status()["restart_pending"] is True
    service.mark_es_restart_pending(False)
    assert service.es_status()["restart_pending"] is False
