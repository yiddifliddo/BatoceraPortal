from portal import service

BATOCERA_TEMPLATE = """#!/bin/bash
case "$1" in
    start)
        echo "started"
        ;;
    stop)
        echo "stopped"
        ;;
    *)
        echo "all other conditions"
        ;;
esac

exit $?
"""


def _no_services(monkeypatch):
    monkeypatch.setattr(service, "has_batocera_services", lambda: False)


def test_service_cmd_quotes_and_validates_port(env):
    s = dict(env["settings"], app_path="/userdata/system/my portal/app.py", server_port=99999)
    cmd = service.service_cmd(s)
    assert cmd == "python3 '/userdata/system/my portal/app.py' --port 5000"


def test_custom_sh_fallback_roundtrip(env, monkeypatch):
    _no_services(monkeypatch)
    s = env["settings"]
    assert service.autostart_status(s)["registered"] is False
    st = service.install_autostart(s)
    assert st["mechanism"] == "custom.sh" and st["registered"] and st["cmd"].startswith("python3 ")
    content = open(s["custom_sh"]).read()
    assert content.startswith("#!/bin/bash")
    assert content.count(service.MARKER_START) == 1
    service.install_autostart(s, cmd="python3 /other/app.py --port 8080")
    content = open(s["custom_sh"]).read()
    assert content.count(service.MARKER_START) == 1 and "--port 8080" in content
    assert service.remove_autostart(s) is True
    assert service.MARKER_START not in open(s["custom_sh"]).read()
    assert service.remove_autostart(s) is False


def test_custom_sh_block_goes_before_final_exit(env, monkeypatch):
    """Batocera's template ends with `exit $?`; a block after it would never run."""
    _no_services(monkeypatch)
    s = env["settings"]
    with open(s["custom_sh"], "w") as f:
        f.write(BATOCERA_TEMPLATE)
    service.install_autostart(s)
    content = open(s["custom_sh"]).read()
    assert content.index(service.MARKER_END) < content.index("exit $?")
    assert 'if [ -z "$1" ] || [ "$1" = "start" ]; then' in content
    service.remove_autostart(s)
    assert open(s["custom_sh"]).read() == BATOCERA_TEMPLATE


def test_custom_sh_keeps_user_lines(env, monkeypatch):
    _no_services(monkeypatch)
    s = env["settings"]
    with open(s["custom_sh"], "w") as f:
        f.write("#!/bin/bash\n# user stuff\nmount /dev/sda1 /mnt\n")
    service.install_autostart(s)
    service.remove_autostart(s)
    assert open(s["custom_sh"]).read() == "#!/bin/bash\n# user stuff\nmount /dev/sda1 /mnt\n"


def test_batocera_services_path(env, monkeypatch):
    s = env["settings"]
    calls = []
    enabled = {"on": False}

    def fake_run(cmd, timeout=20):
        calls.append(cmd)
        if cmd[:2] == ["batocera-services", "enable"]:
            enabled["on"] = True
            return 0, ""
        if cmd[:2] == ["batocera-services", "disable"]:
            enabled["on"] = False
            return 0, ""
        if cmd[:2] == ["batocera-services", "list"]:
            return 0, ("* batocera_portal\n" if enabled["on"] else "  batocera_portal\n") + "  other\n"
        return 1, "unknown"

    monkeypatch.setattr(service, "has_batocera_services", lambda: True)
    monkeypatch.setattr(service, "_run", fake_run)

    st = service.autostart_status(s)
    assert st["mechanism"] == "batocera-services" and not st["registered"]
    st = service.install_autostart(s)
    script = service.service_script_path(s)
    assert script.exists() and st["registered"] and st["enabled"]
    text = script.read_text()
    assert text.startswith("#!/bin/bash") and "start)" in text and "--port 5000" in text
    assert ["batocera-services", "enable", "batocera_portal"] in calls
    assert service.remove_autostart(s) is True
    assert not script.exists()
    assert ["batocera-services", "disable", "batocera_portal"] in calls
    assert service.autostart_status(s)["registered"] is False


def test_services_enable_failure_is_reported(env, monkeypatch):
    monkeypatch.setattr(service, "has_batocera_services", lambda: True)
    monkeypatch.setattr(service, "_run", lambda cmd, timeout=20: (1, "boom"))
    st = service.install_autostart(env["settings"])
    assert st["script_present"] and not st["enabled"] and "failed" in st["note"]


def test_process_status_reports_manual_mode(env, monkeypatch):
    _no_services(monkeypatch)
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
