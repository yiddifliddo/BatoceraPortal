"""Autostart (custom.sh) management, process status and EmulationStation control."""
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

MARKER_START = "# [batocera-portal]"
MARKER_END = "# [/batocera-portal]"
SERVICE_NAME = "batocera_portal"

_ES_RESTART_PENDING = {"flag": False}


# ---------------------------------------------------------------- helpers ---
def _run(cmd, timeout=20):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def has_batocera_services():
    """Batocera >= 36 ships `batocera-services`, the supported way to add a service."""
    return bool(shutil.which("batocera-services"))


def services_dir(settings):
    custom = Path(settings.get("custom_sh", "/userdata/system/custom.sh"))
    return custom.parent / "services"


def service_script_path(settings):
    return services_dir(settings) / SERVICE_NAME


def service_script_text(cmd):
    return f"""#!/bin/bash
{MARKER_START}
# Batocera Portal service. Managed from the portal's Settings page.
case "$1" in
  start)
    {cmd} >/dev/null 2>&1 &
    ;;
  stop)
    pkill -f 'python3? [^ ]*batocera_portal/app\\.py' 2>/dev/null
    ;;
  restart)
    "$0" stop; sleep 1; "$0" start
    ;;
  status)
    pgrep -f 'python3? [^ ]*batocera_portal/app\\.py' >/dev/null && echo running || echo stopped
    ;;
esac
{MARKER_END}
"""


def _service_enabled():
    """Ask batocera-services whether our service is enabled."""
    rc, out = _run(["batocera-services", "list"])
    if rc == 0:
        for line in out.splitlines():
            if SERVICE_NAME in line.split():
                return "*" in line
    rc, out = _run(["batocera-settings-get", "system.services"])
    if rc == 0:
        return SERVICE_NAME in re.split(r"[,;\s]+", out.strip())
    return False


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


def _custom_sh_block(content):
    """Return (start, end) of our block in custom.sh, or None."""
    if MARKER_START not in content or MARKER_END not in content:
        return None
    start = content.index(MARKER_START)
    end = content.index(MARKER_END) + len(MARKER_END)
    return start, end


def _cmd_from_block(block):
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("python") or line.startswith("exec python"):
            return line.rstrip("&").strip()
    return None


def autostart_status(settings):
    """Where (if anywhere) the portal is registered to start at boot."""
    script = service_script_path(settings)
    if has_batocera_services() or script.exists():
        registered = script.exists()
        enabled = registered and has_batocera_services() and _service_enabled()
        cmd = _cmd_from_block(script.read_text(encoding="utf-8", errors="replace")) if registered else None
        return {"mechanism": "batocera-services", "registered": registered and enabled,
                "script_present": registered, "enabled": enabled, "cmd": cmd,
                "file": str(script), "exists": registered,
                "note": None if registered or has_batocera_services() else
                "batocera-services not found"}
    p = _custom_sh(settings)
    if not p.exists():
        return {"mechanism": "custom.sh", "registered": False, "cmd": None, "file": str(p),
                "exists": False, "enabled": False, "script_present": False, "note": None}
    content = p.read_text(encoding="utf-8", errors="replace")
    span = _custom_sh_block(content)
    if not span:
        return {"mechanism": "custom.sh", "registered": False, "cmd": None, "file": str(p),
                "exists": True, "enabled": False, "script_present": False, "note": None}
    block = content[span[0]:span[1]]
    return {"mechanism": "custom.sh", "registered": True, "cmd": _cmd_from_block(block),
            "file": str(p), "exists": True, "enabled": True, "script_present": True, "note": None}


def install_autostart(settings, cmd=None):
    cmd = cmd or service_cmd(settings)
    if has_batocera_services():
        script = service_script_path(settings)
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(service_script_text(cmd), encoding="utf-8")
        try:
            script.chmod(0o755)
        except OSError:
            pass
        rc, out = _run(["batocera-services", "enable", SERVICE_NAME])
        status = autostart_status(settings)
        if rc != 0:
            status["note"] = f"batocera-services enable failed: {out.strip()[:200]}"
        return status
    return _install_custom_sh(settings, cmd)


def _install_custom_sh(settings, cmd):
    """Fallback for Batocera builds without batocera-services.

    Batocera's custom.sh template is a case statement that ends with `exit $?`,
    so the block is inserted before that final exit and guarded so it only runs
    when custom.sh is called with `start` (or no argument).
    """
    block = (f"{MARKER_START}\n"
             f'if [ -z "$1" ] || [ "$1" = "start" ]; then\n'
             f"  {cmd} >/dev/null 2>&1 &\n"
             f"fi\n"
             f"{MARKER_END}\n")
    p = _custom_sh(settings)
    if p.exists():
        content = p.read_text(encoding="utf-8", errors="replace")
        span = _custom_sh_block(content)
        if span:
            start, end = span
            if end < len(content) and content[end] == "\n":
                end += 1
            content = content[:start] + block + content[end:]
        else:
            if content and not content.endswith("\n"):
                content += "\n"
            m = re.search(r"^exit\b[^\n]*\n?\Z", content, re.M)
            if m:
                content = content[:m.start()] + block + content[m.start():]
            else:
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
    removed = False
    script = service_script_path(settings)
    if script.exists():
        if has_batocera_services():
            _run(["batocera-services", "disable", SERVICE_NAME])
        script.unlink()
        removed = True
    p = _custom_sh(settings)
    if p.exists():
        content = p.read_text(encoding="utf-8", errors="replace")
        span = _custom_sh_block(content)
        if span:
            start, end = span
            if end < len(content) and content[end] == "\n":
                end += 1
            content = content[:start] + content[end:]
            p.write_text(content.rstrip() + "\n", encoding="utf-8")
            removed = True
    return removed


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
