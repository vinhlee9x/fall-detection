import json
import os
import re
import threading
import time

import cv2

ID_RE = re.compile(r"^\d{8}_\d{6}(_\d{2})?$")
MAX_SIDE = 640
JPEG_QUALITY = 80
KINDS = {"annotated": ".jpg", "raw": "_raw.jpg"}


def _shrink(img):
    h, w = img.shape[:2]
    scale = MAX_SIDE / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def encode_jpeg(img):
    ok, buf = cv2.imencode(".jpg", _shrink(img), [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise OSError("không mã hoá được ảnh")
    return buf.tobytes()


def _atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


class AlarmStore:
    def __init__(self, directory="alarms", max_alarms=100):
        self.dir = directory
        self.max_alarms = max_alarms
        self._lock = threading.Lock()
        os.makedirs(self.dir, exist_ok=True)
        self._cleanup_orphans()

    def is_valid_id(self, alarm_id):
        return bool(ID_RE.match(alarm_id or ""))

    def _path(self, alarm_id, suffix):
        return os.path.join(self.dir, alarm_id + suffix)

    def _new_id(self, stamp):
        base, n = stamp, 0
        while os.path.exists(self._path(base, ".json")) or os.path.exists(self._path(base, ".jpg")):
            n += 1
            base = f"{stamp}_{n:02d}"
        return base

    def _cleanup_orphans(self):
        names = os.listdir(self.dir)
        ids = {n.split(".")[0].replace("_raw", "") for n in names if n.endswith((".jpg", ".json", ".tmp"))}
        for alarm_id in ids:
            if not self.is_valid_id(alarm_id):
                continue
            if not os.path.exists(self._path(alarm_id, ".json")):
                self._remove(alarm_id)
        for n in names:
            if n.endswith(".tmp"):
                try:
                    os.remove(os.path.join(self.dir, n))
                except OSError:
                    pass

    def _remove(self, alarm_id):
        for suffix in (".json", ".jpg", "_raw.jpg"):
            try:
                os.remove(self._path(alarm_id, suffix))
            except OSError:
                pass

    def save(self, event, threshold, notify_status="pending"):
        wall = getattr(event, "wall_time", time.time())
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(wall))
        annotated, raw = encode_jpeg(event.annotated), encode_jpeg(event.raw)
        with self._lock:
            alarm_id = self._new_id(stamp)
            try:
                _atomic_write(self._path(alarm_id, ".jpg"), annotated)
                _atomic_write(self._path(alarm_id, "_raw.jpg"), raw)
                record = {"id": alarm_id,
                          "time_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(wall)),
                          "video_t": round(event.t, 2), "p_fall": round(event.p_fall, 3),
                          "threshold": threshold, "notify": {"status": notify_status, "error": None}}
                _atomic_write(self._path(alarm_id, ".json"), json.dumps(record).encode())
            except OSError:
                self._remove(alarm_id)
                raise
            self._prune()
        return alarm_id

    def _ids(self):
        return sorted(n[:-5] for n in os.listdir(self.dir) if n.endswith(".json") and self.is_valid_id(n[:-5]))

    def _prune(self):
        ids = self._ids()
        for alarm_id in ids[:max(0, len(ids) - self.max_alarms)]:
            self._remove(alarm_id)

    def get(self, alarm_id):
        if not self.is_valid_id(alarm_id):
            return None
        try:
            with open(self._path(alarm_id, ".json")) as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def list(self, limit=50):
        out = []
        for alarm_id in reversed(self._ids()):
            record = self.get(alarm_id)
            if record:
                out.append(record)
            if len(out) >= limit:
                break
        return out

    def image_path(self, alarm_id, kind="annotated"):
        if not self.is_valid_id(alarm_id) or kind not in KINDS:
            return None
        path = self._path(alarm_id, KINDS[kind])
        return path if os.path.isfile(path) else None

    def update_notify(self, alarm_id, status, error=None):
        with self._lock:
            record = self.get(alarm_id)
            if not record:
                return None
            record["notify"] = {"status": status, "error": error}
            _atomic_write(self._path(alarm_id, ".json"), json.dumps(record).encode())
            return record
