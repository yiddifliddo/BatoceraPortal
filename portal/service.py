"""Autostart (custom.sh) management, process status and EmulationStation control."""
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

MARKER_START = "# [batocera-portal]"
MARKER_END = "# [/batocera-portal]"

_ES_RESTART_PENDING = {"flag": False}


def service_cmd(settings):
    app_path = str(settings.get("app_path", "/userdata/system/batocera_portal/app.py"))
    try:
        port = int(settings.get("server_port", 5000))
    except (TypeError, ValueError):
        port = 5000
    if not 1 <= port <= 65535:
        port = 5000
    return f"python3 {shlex.quote(app_path)} --port {port}"


def _custom_sh(settings):
    return Path(settings.get("custom_sh", "/userdata/system/custom.sh"))


def autostart_status(settings):
    p = _custom_sh(settings)
    if not p.exists():
        return {"registered": False, "cmd": None, "file": str(p), "exists": False}
    content = p.read_text(encoding="utf-8", errors="replace")
    if MARKER_START not in content or MARKER_END not in content:
        return {"registered": False, "cmd": None, "file": str(p), "exists": True}
    block = content[content.index(MARKER_START):content.index(MARKER_END) + len(MARKER_END)]
    cmd = None
    for line in block.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            cmd = line.rstrip("&").strip()
            break
    return {"registered": True, "cmd": cmd, "file": str(p), "exists": True}


def install_autostart(settings, cmd=None):
    cmd = cmd or service_cmd(settings)
    block = f"{MARKER_START}\n{cmd} &\n{MARKER_END}\n"
    p = _custom_sh(settings)
    if p.exists():
        content = p.read_text(encoding="utf-8", errors="replace")
        if MARKER_START in content and MARKER_END in content:
            start = content.index(MARKER_START)
            end = content.index(MARKER_END) + len(MARKER_END)
            if end < len(content) and content[end] == "\n":
                end += 1
            content = content[:start] + block + content[end:]
        else:
            if content and not content.endswith("\n"):
                content += "\n"
            content += block
        if not content.startswith("#!"):
            content = "#!/bin/bash\n" + content
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        content = "#!/bin/bash\n" + block
    p.write_text(content, encoding="utf-8")
    try:
        p.chmod(0o755)
    except OSError:
        pass
    return autostart_status(settings)


def remove_autostart(settings):
    p = _custom_sh(settings)
    if not p.exists():
        return False
    content = p.read_text(encoding="utf-8", errors="replace")
    if MARKER_START not in content or MARKER_END not in content:
        return False
    start = content.index(MARKER_START)
    end = content.index(MARKER_END) + len(MARKER_END)
    if start > 0 and content[start - 1] == "\n":
        start -= 1
    content = content[:start] + content[end:]
    p.write_text(content.rstrip() + "\n", encoding="utf-8")
    return True


def _pids_matching(pattern):
    """Return PIDs whose cmdline matches pattern, read from /proc."""
    rx = re.compile(pattern)
    pids = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as f:
                cmd = f.read().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
        except OSError:
            continue
        if cmd and rx.search(cmd):
            pids.append((int(entry), cmd))
    return pids


def process_status(settings):
    """Is the portal running, under which PID and port, and how was it started?"""
    me = os.getpid()
    port = None
    cmdline = ""
    try:
        with open(f"/proc/{me}/cmdline", "rb") as f:
            cmdline = f.read().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
    except OSError:
        pass
    m = re.search(r"--port\s+(\d+)", cmdline)
    if m:
        port = int(m.group(1))
    status = autostart_status(settings)
    return {
        "pid": me,
        "port": port or settings.get("server_port"),
        "cmdline": cmdline,
        "autostart": status["registered"],
        "manual_mode": not status["registered"],
    }


def restart_self(settings):
    """Spawn a fresh server then let the caller exit this one."""
    cmd = service_cmd(settings)
    try:
        subprocess.Popen(cmd, shell=True, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def es_status():
    pids = _pids_matching(r"(^|/)emulationstation(\s|$)")
    running = bool(pids)
    pid = pids[0][0] if pids else None
    uptime = None
    if pid:
        try:
            with open(f"/proc/{pid}/stat") as f:
                start_ticks = int(f.read().split(")")[-1].split()[19])
            with open("/proc/uptime") as f:
                sys_up = float(f.read().split()[0])
            hz = os.sysconf("SC_CLK_TCK")
            uptime = int(sys_up - start_ticks / hz)
        except (OSError, ValueError, IndexError):
            uptime = None
    return {"running": running, "pid": pid, "uptime": uptime,
            "restart_pending": _ES_RESTART_PENDING["flag"]}


def mark_es_restart_pending(flag=True):
    _ES_RESTART_PENDING["flag"] = bool(flag)


def restart_emulationstation():
    """Use batocera-es-swissknife, the supported way to bounce ES on Batocera."""
    if not shutil.which("batocera-es-swissknife"):
        return False, {"error": "batocera-es-swissknife not found (is this Batocera?)"}
    try:
        p = subprocess.run(["batocera-es-swissknife", "--restart"],
                           capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, {"error": "EmulationStation restart timed out"}
    except OSError as e:
        return False, {"error": str(e)}
    if p.returncode != 0:
        return False, {"error": (p.stderr or p.stdout or "unknown error").strip()[:500]}
    mark_es_restart_pending(False)
    return True, {"ok": True}


def reboot_or_shutdown(action):
    cmd = {"reboot": ["reboot"], "shutdown": ["poweroff"]}.get(action)
    if not cmd:
        return False, {"error": "Unknown action"}
    try:
        subprocess.Popen(cmd, start_new_session=True)
        return True, {"ok": True}
    except OSError as e:
        return False, {"error": str(e)}
