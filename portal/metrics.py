"""Live hardware metrics read straight from /proc and /sys.

Every reader accepts an optional root so tests can point it at fixtures.
"""
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

from .util import human_size, read_text

_DISK_CACHE = {"ts": 0.0, "data": None}
DISK_TTL = 30


def batocera_version():
    txt = read_text("/usr/share/batocera/batocera.version").strip()
    if txt:
        return txt.split()[0]
    for line in read_text("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return "unknown"


def uptime_seconds(proc="/proc"):
    try:
        return int(float(read_text(f"{proc}/uptime").split()[0]))
    except (IndexError, ValueError):
        return 0


def format_duration(seconds):
    seconds = int(seconds or 0)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def cpu_info(proc="/proc"):
    model, cores = "", 0
    for line in read_text(f"{proc}/cpuinfo").splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        if key in ("model name", "hardware", "model") and not model:
            model = val.strip()
        if key == "processor":
            cores += 1
    return model or "Unknown CPU", cores or os.cpu_count() or 1


def _cpu_times(proc):
    line = read_text(f"{proc}/stat").splitlines()[0]
    vals = [int(x) for x in line.split()[1:]]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    return idle, sum(vals)


def cpu_usage(proc="/proc", interval=0.2):
    try:
        i1, t1 = _cpu_times(proc)
        time.sleep(interval)
        i2, t2 = _cpu_times(proc)
        dt = t2 - t1
        if dt <= 0:
            return 0.0
        return round((1 - (i2 - i1) / dt) * 100, 1)
    except (IndexError, ValueError, OSError):
        return 0.0


def cpu_usage_from_samples(sample1, sample2):
    """Pure helper for tests: samples are (idle, total)."""
    dt = sample2[1] - sample1[1]
    if dt <= 0:
        return 0.0
    return round((1 - (sample2[0] - sample1[0]) / dt) * 100, 1)


def cpu_temp(sys_root="/sys"):
    best = None
    for tz in sorted(Path(f"{sys_root}/class/thermal").glob("thermal_zone*")):
        ttype = read_text(tz / "type").strip().lower()
        try:
            temp = int(read_text(tz / "temp").strip()) / 1000
        except ValueError:
            continue
        if not 0 < temp < 130:
            continue
        if any(k in ttype for k in ("x86_pkg", "cpu", "soc", "core")):
            return round(temp, 1), ttype
        if best is None:
            best = (round(temp, 1), ttype)
    if best:
        return best
    for hw in sorted(Path(f"{sys_root}/class/hwmon").glob("hwmon*")):
        name = read_text(hw / "name").strip().lower()
        if name in ("coretemp", "k10temp", "cpu_thermal", "zenpower", "acpitz"):
            for t in sorted(hw.glob("temp*_input")):
                try:
                    temp = int(read_text(t).strip()) / 1000
                except ValueError:
                    continue
                if 0 < temp < 130:
                    return round(temp, 1), name
    return None, None


def fans(sys_root="/sys"):
    out = []
    for hw in sorted(Path(f"{sys_root}/class/hwmon").glob("hwmon*")):
        name = read_text(hw / "name").strip() or hw.name
        for f in sorted(hw.glob("fan*_input")):
            try:
                rpm = int(read_text(f).strip())
            except ValueError:
                continue
            label = read_text(f.with_name(f.name.replace("_input", "_label"))).strip()
            out.append({"source": name, "label": label or f.name.replace("_input", ""),
                        "rpm": rpm})
    return out


def memory(proc="/proc"):
    info = {}
    for line in read_text(f"{proc}/meminfo").splitlines():
        key, _, val = line.partition(":")
        try:
            info[key.strip()] = int(val.strip().split()[0]) * 1024
        except (ValueError, IndexError):
            pass
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", info.get("MemFree", 0))
    used = max(total - avail, 0)
    return {"total": total, "used": used, "available": avail,
            "percent": round(used / total * 100, 1) if total else 0.0,
            "total_h": human_size(total), "used_h": human_size(used)}


def _disk_entry(label, path):
    try:
        u = shutil.disk_usage(path)
    except OSError:
        return None
    return {"label": label, "path": path, "total": u.total, "used": u.used, "free": u.free,
            "percent": round(u.used / u.total * 100, 1) if u.total else 0.0,
            "total_h": human_size(u.total), "used_h": human_size(u.used),
            "free_h": human_size(u.free)}


def disks(paths=None, force=False):
    now = time.time()
    if not force and _DISK_CACHE["data"] is not None and now - _DISK_CACHE["ts"] < DISK_TTL:
        return _DISK_CACHE["data"]
    paths = paths or [("Userdata", "/userdata"), ("Root", "/")]
    out = [e for e in (_disk_entry(l, p) for l, p in paths) if e]
    _DISK_CACHE.update({"ts": now, "data": out})
    return out


def gpu(sys_root="/sys"):
    """Best-effort GPU info: DRM sysfs (AMD/Intel) then nvidia-smi."""
    for card in sorted(Path(f"{sys_root}/class/drm").glob("card[0-9]")):
        dev = card / "device"
        vendor = read_text(dev / "vendor").strip().lower()
        if not vendor:
            continue
        name = {"0x1002": "AMD", "0x8086": "Intel", "0x10de": "NVIDIA"}.get(vendor, vendor)
        info = {"vendor": name, "model": read_text(dev / "product_name").strip() or name,
                "usage": None, "vram_total": None, "vram_used": None, "temp": None,
                "source": "drm"}
        try:
            info["usage"] = int(read_text(dev / "gpu_busy_percent").strip())
        except ValueError:
            pass
        try:
            info["vram_total"] = int(read_text(dev / "mem_info_vram_total").strip())
            info["vram_used"] = int(read_text(dev / "mem_info_vram_used").strip())
        except ValueError:
            pass
        for hw in (dev / "hwmon").glob("hwmon*") if (dev / "hwmon").is_dir() else []:
            try:
                info["temp"] = int(read_text(hw / "temp1_input").strip()) / 1000
                break
            except ValueError:
                pass
        if vendor != "0x10de":
            return info
    if shutil.which("nvidia-smi"):
        try:
            q = "name,utilization.gpu,memory.total,memory.used,temperature.gpu"
            out = subprocess.run(["nvidia-smi", f"--query-gpu={q}",
                                  "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5).stdout
            parts = [p.strip() for p in out.strip().splitlines()[0].split(",")]
            return {"vendor": "NVIDIA", "model": parts[0], "usage": int(parts[1]),
                    "vram_total": int(parts[2]) * 1024 * 1024,
                    "vram_used": int(parts[3]) * 1024 * 1024, "temp": float(parts[4]),
                    "source": "nvidia-smi"}
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
            pass
    return {"vendor": None, "model": "Not detected", "usage": None,
            "vram_total": None, "vram_used": None, "temp": None, "source": None}


def battery(sys_root="/sys"):
    for ps in sorted(Path(f"{sys_root}/class/power_supply").glob("*")):
        if read_text(ps / "type").strip().lower() != "battery":
            continue
        try:
            cap = int(read_text(ps / "capacity").strip())
        except ValueError:
            continue
        return {"present": True, "percent": cap, "status": read_text(ps / "status").strip()}
    return {"present": False}


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def hostname():
    return socket.gethostname()


def load_average(proc="/proc"):
    try:
        return [float(x) for x in read_text(f"{proc}/loadavg").split()[:3]]
    except ValueError:
        return [0.0, 0.0, 0.0]


def dashboard(es_status_fn=None):
    model, cores = cpu_info()
    temp, temp_src = cpu_temp()
    return {
        "batocera_version": batocera_version(),
        "hostname": hostname(),
        "ip": local_ip(),
        "uptime": uptime_seconds(),
        "uptime_h": format_duration(uptime_seconds()),
        "load": load_average(),
        "cpu": {"model": model, "cores": cores, "usage": cpu_usage(),
                "temp": temp, "temp_source": temp_src},
        "gpu": gpu(),
        "memory": memory(),
        "disks": disks(),
        "fans": fans(),
        "battery": battery(),
        "es": es_status_fn() if es_status_fn else None,
        "timestamp": int(time.time()),
    }
