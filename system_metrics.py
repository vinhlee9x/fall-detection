import os
import re
import shutil
import subprocess
import threading
import time

import psutil

THROTTLE_NOW = {0: "undervoltage", 1: "freq_capped", 2: "throttled", 3: "soft_temp_limit"}
THROTTLE_PAST = {16: "undervoltage", 17: "freq_capped", 18: "throttled", 19: "soft_temp_limit"}


def decode_throttled(value):
    return {
        "now": [name for bit, name in THROTTLE_NOW.items() if value >> bit & 1],
        "since_boot": [name for bit, name in THROTTLE_PAST.items() if value >> bit & 1],
        "raw": value,
    }


def parse_temp(text):
    m = re.search(r"(-?\d+(?:\.\d+)?)", text or "")
    return float(m.group(1)) if m else None


def _read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def detect_raspberry_pi():
    model = _read("/proc/device-tree/model")
    return bool(model and "Raspberry Pi" in model)


def _vcgencmd(*args):
    try:
        out = subprocess.run(["vcgencmd", *args], capture_output=True, text=True, timeout=1)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


class SystemMetrics:
    def __init__(self, disk_path=".", interval=1.0):
        self.disk_path = disk_path
        self.interval = interval
        self.is_pi = detect_raspberry_pi()
        self._proc = psutil.Process(os.getpid())
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        psutil.cpu_percent(interval=None, percpu=True)
        self._proc.cpu_percent(interval=None)
        self._data = self._sample()

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="metrics", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def snapshot(self):
        with self._lock:
            return dict(self._data)

    def _loop(self):
        while not self._stop.wait(self.interval):
            data = self._sample()
            with self._lock:
                self._data = data

    def _temp(self):
        raw = _read("/sys/class/thermal/thermal_zone0/temp")
        if raw and raw.strip().lstrip("-").isdigit():
            return int(raw.strip()) / 1000.0
        if self.is_pi:
            return parse_temp(_vcgencmd("measure_temp"))
        return None

    def _throttled(self):
        if not self.is_pi:
            return None
        out = _vcgencmd("get_throttled")
        if not out or "=" not in out:
            return None
        try:
            return decode_throttled(int(out.split("=", 1)[1], 16))
        except ValueError:
            return None

    def _freq(self):
        try:
            f = psutil.cpu_freq()
            if f and f.current:
                return round(f.current)
        except (OSError, NotImplementedError, AttributeError):
            pass
        if self.is_pi:
            out = _vcgencmd("measure_clock", "arm")
            if out and "=" in out:
                try:
                    return round(int(out.split("=", 1)[1]) / 1e6)
                except ValueError:
                    return None
        return None

    def _safe(self, fn):
        try:
            return fn()
        except Exception:
            return None

    def _sample(self):
        per_core = self._safe(lambda: psutil.cpu_percent(interval=None, percpu=True))
        mem = self._safe(psutil.virtual_memory)
        disk = self._safe(lambda: shutil.disk_usage(self.disk_path))
        proc_mem = self._safe(lambda: self._proc.memory_info().rss)
        return {
            "is_raspberry_pi": self.is_pi,
            "cpu_temp_c": self._safe(self._temp),
            "throttled": self._safe(self._throttled),
            "cpu_percent": round(sum(per_core) / len(per_core), 1) if per_core else None,
            "cpu_percent_per_core": per_core,
            "cpu_freq_mhz": self._safe(self._freq),
            "ram_used_mb": round(mem.used / 1048576) if mem else None,
            "ram_total_mb": round(mem.total / 1048576) if mem else None,
            "ram_percent": mem.percent if mem else None,
            "disk_used_gb": round(disk.used / 1e9, 1) if disk else None,
            "disk_total_gb": round(disk.total / 1e9, 1) if disk else None,
            "disk_percent": round(disk.used * 100 / disk.total, 1) if disk else None,
            "load_avg": self._safe(lambda: list(os.getloadavg())),
            "uptime_s": self._safe(lambda: round(time.time() - psutil.boot_time())),
            "proc_cpu_percent": self._safe(lambda: self._proc.cpu_percent(interval=None)),
            "proc_rss_mb": round(proc_mem / 1048576) if proc_mem else None,
        }
