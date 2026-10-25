from portal import metrics


def test_cpu_usage_from_samples():
    assert metrics.cpu_usage_from_samples((100, 1000), (150, 1200)) == 75.0
    assert metrics.cpu_usage_from_samples((100, 1000), (100, 1000)) == 0.0


def test_cpu_info_and_memory(tmp_path):
    (tmp_path / "cpuinfo").write_text("processor\t: 0\nmodel name\t: Intel N100\nprocessor\t: 1\n")
    (tmp_path / "meminfo").write_text("MemTotal:       8000000 kB\nMemFree:  1000000 kB\nMemAvailable:    4000000 kB\n")
    assert metrics.cpu_info(str(tmp_path)) == ("Intel N100", 2)
    m = metrics.memory(str(tmp_path))
    assert m["total"] == 8000000 * 1024 and m["percent"] == 50.0


def test_cpu_temp_and_fans(tmp_path):
    tz = tmp_path / "class/thermal/thermal_zone0"
    tz.mkdir(parents=True)
    (tz / "type").write_text("x86_pkg_temp\n")
    (tz / "temp").write_text("51500\n")
    hw = tmp_path / "class/hwmon/hwmon0"
    hw.mkdir(parents=True)
    (hw / "name").write_text("nct6775\n")
    (hw / "fan1_input").write_text("1200\n")
    (hw / "fan1_label").write_text("CPU Fan\n")
    assert metrics.cpu_temp(str(tmp_path)) == (51.5, "x86_pkg_temp")
    assert metrics.fans(str(tmp_path)) == [{"source": "nct6775", "label": "CPU Fan", "rpm": 1200}]


def test_gpu_from_drm(tmp_path):
    dev = tmp_path / "class/drm/card0/device"
    dev.mkdir(parents=True)
    (dev / "vendor").write_text("0x1002\n")
    (dev / "gpu_busy_percent").write_text("37\n")
    (dev / "mem_info_vram_total").write_text("1073741824\n")
    (dev / "mem_info_vram_used").write_text("536870912\n")
    g = metrics.gpu(str(tmp_path))
    assert g["vendor"] == "AMD" and g["usage"] == 37 and g["vram_used"] == 536870912


def test_gpu_not_detected(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics.shutil, "which", lambda _: None)
    assert metrics.gpu(str(tmp_path))["model"] == "Not detected"


def test_battery(tmp_path):
    ps = tmp_path / "class/power_supply/BAT0"
    ps.mkdir(parents=True)
    (ps / "type").write_text("Battery\n")
    (ps / "capacity").write_text("77\n")
    (ps / "status").write_text("Discharging\n")
    assert metrics.battery(str(tmp_path)) == {"present": True, "percent": 77, "status": "Discharging"}
    assert metrics.battery(str(tmp_path / "none")) == {"present": False}


def test_format_duration():
    assert metrics.format_duration(59) == "0m"
    assert metrics.format_duration(3600 * 5 + 120) == "5h 2m"
    assert metrics.format_duration(86400 * 2 + 3600) == "2d 1h 0m"
