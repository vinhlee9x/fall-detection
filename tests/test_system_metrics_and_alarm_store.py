import json
import os
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from alarm_store import AlarmStore
from system_metrics import SystemMetrics, decode_throttled, parse_temp


def make_event(wall=None):
    yy, xx = np.mgrid[0:480, 0:640]
    img = np.stack([xx * 255 // 640, yy * 255 // 480, (xx + yy) * 255 // 1120], axis=-1).astype(np.uint8)
    img[100:300, 200:400] = (30, 120, 220)
    return SimpleNamespace(t=12.3, p_fall=0.7, raw=img.copy(), annotated=img.copy(),
                           wall_time=wall or time.time())


def test_decode_throttled_active_and_history():
    d = decode_throttled(0x50005)
    assert set(d["now"]) == {"undervoltage", "throttled"}
    assert set(d["since_boot"]) == {"undervoltage", "throttled"}


def test_decode_throttled_zero():
    d = decode_throttled(0x0)
    assert d["now"] == [] and d["since_boot"] == []


def test_parse_temp():
    assert parse_temp("temp=52.1'C") == 52.1
    assert parse_temp("") is None
    assert parse_temp(None) is None


def test_snapshot_on_non_pi_does_not_fail():
    m = SystemMetrics(disk_path=".")
    snap = m.snapshot()
    assert snap["is_raspberry_pi"] is False
    assert snap["throttled"] is None
    assert snap["ram_total_mb"] and snap["disk_total_gb"]


def test_snapshot_spawns_no_subprocess(monkeypatch):
    m = SystemMetrics()
    import system_metrics
    calls = []
    monkeypatch.setattr(system_metrics.subprocess, "run", lambda *a, **k: calls.append(1))
    for _ in range(1000):
        m.snapshot()
    assert calls == []


def test_metrics_thread_start_stop():
    m = SystemMetrics(interval=0.05)
    m.start()
    time.sleep(0.2)
    m.stop()
    assert m.snapshot()["cpu_percent_per_core"] is not None


def test_save_and_list_newest_first(tmp_path):
    s = AlarmStore(str(tmp_path), max_alarms=10)
    a = s.save(make_event(1000000), 0.5)
    b = s.save(make_event(1000005), 0.5)
    assert [r["id"] for r in s.list()] == [b, a]
    assert s.image_path(a, "annotated") and s.image_path(a, "raw")


def test_alarm_size_under_limit(tmp_path):
    s = AlarmStore(str(tmp_path))
    a = s.save(make_event(), 0.5)
    total = sum(os.path.getsize(os.path.join(tmp_path, n)) for n in os.listdir(tmp_path) if n.startswith(a))
    assert total <= 150 * 1024


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "..", "20240101_000000/../x", None])
def test_invalid_ids_rejected(tmp_path, bad):
    s = AlarmStore(str(tmp_path))
    assert s.image_path(bad, "annotated") is None
    assert s.get(bad) is None
    assert s.update_notify(bad, "sent") is None


def test_invalid_kind_rejected(tmp_path):
    s = AlarmStore(str(tmp_path))
    a = s.save(make_event(), 0.5)
    assert s.image_path(a, "../etc") is None


def test_prune_keeps_exact_count_and_triplets(tmp_path):
    s = AlarmStore(str(tmp_path), max_alarms=3)
    for i in range(7):
        s.save(make_event(1000000 + i), 0.5)
    names = os.listdir(tmp_path)
    assert len([n for n in names if n.endswith(".json")]) == 3
    assert len(names) == 9
    assert not [n for n in names if n.endswith(".tmp")]


def test_corrupt_json_skipped(tmp_path):
    s = AlarmStore(str(tmp_path))
    a = s.save(make_event(1000000), 0.5)
    with open(os.path.join(tmp_path, "20200101_000000.json"), "w") as f:
        f.write("{broken")
    assert [r["id"] for r in s.list()] == [a]


def test_concurrent_saves_unique_ids(tmp_path):
    s = AlarmStore(str(tmp_path))
    ids = []
    ev = make_event(1000000)

    def work():
        ids.append(s.save(ev, 0.5))

    threads = [threading.Thread(target=work) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(set(ids)) == 6


def test_update_notify(tmp_path):
    s = AlarmStore(str(tmp_path))
    a = s.save(make_event(), 0.5)
    s.update_notify(a, "failed", "lỗi")
    assert s.get(a)["notify"] == {"status": "failed", "error": "lỗi"}


def test_orphans_cleaned_on_start(tmp_path):
    (tmp_path / "20200101_000000.jpg").write_bytes(b"x")
    (tmp_path / "20200101_000000_raw.jpg").write_bytes(b"x")
    (tmp_path / "stale.tmp").write_bytes(b"x")
    s = AlarmStore(str(tmp_path))
    assert os.listdir(tmp_path) == []
    assert s.list() == []
