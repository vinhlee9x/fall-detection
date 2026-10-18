import threading
import time
from collections import deque

import cv2

from overlay import draw_overlay

ALARM_BANNER_S = 2.0
STREAM_MAX_SIDE = 640


class AlarmEvent:
    def __init__(self, t, p_fall, raw, annotated):
        self.t = t
        self.p_fall = p_fall
        self.raw = raw
        self.annotated = annotated
        self.wall_time = time.time()


class LiveState:
    def __init__(self, threshold):
        self.cond = threading.Condition()
        self.seq = 0
        self.jpeg = None
        self.data = {"t": 0.0, "p_fall": 0.0, "state": "normal", "pose_ms": 0.0,
                     "fps": 0.0, "threshold": threshold, "alarm_count": 0}

    def update(self, jpeg=None, **fields):
        with self.cond:
            self.data.update(fields)
            if jpeg is not None:
                self.jpeg = jpeg
            self.seq += 1
            self.cond.notify_all()

    def snapshot(self):
        with self.cond:
            return dict(self.data)

    def wait_frame(self, last_seq, timeout=2.0):
        with self.cond:
            if self.seq == last_seq:
                self.cond.wait(timeout)
            return self.seq, self.jpeg


class DetectionPipeline:
    def __init__(self, pose, detector, source, threshold, on_frame=None, on_alarm=None,
                 jpeg_quality=80, report_every=5.0, quiet=False):
        self.pose, self.det, self.source = pose, detector, source
        self.thr = threshold
        self.on_frame, self.on_alarm = on_frame, on_alarm
        self.jpeg_quality = jpeg_quality
        self.report_every = report_every
        self.quiet = quiet
        self.state = LiveState(threshold)
        self.alarm_count = 0
        self.total_frames = 0
        self.total_ms = 0.0
        self._viewers = 0
        self._viewers_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.error = None
        self._recent = deque(maxlen=30)
        self._alarm_until = -1.0

    @property
    def viewers(self):
        with self._viewers_lock:
            return self._viewers

    def add_viewer(self):
        with self._viewers_lock:
            self._viewers += 1

    def remove_viewer(self):
        with self._viewers_lock:
            self._viewers = max(0, self._viewers - 1)

    def start(self):
        self._thread = threading.Thread(target=self._run_safe, name="pipeline", daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        self._stop.set()

    def join(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)

    def alive(self):
        return self._thread is not None and self._thread.is_alive()

    def _run_safe(self):
        try:
            self.run()
        except BaseException as e:
            self.error = e
            raise

    def _log(self, msg):
        if not self.quiet:
            print(msg, flush=True)

    def _encode(self, frame):
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        return buf.tobytes() if ok else None

    def _encode_stream(self, frame, kps, t, prob, state):
        scale = STREAM_MAX_SIDE / max(frame.shape[:2])
        if scale < 1:
            frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            kps = kps.copy()
            kps[:, :2] *= scale
        draw_overlay(frame, kps, t, prob, state, self.thr, t <= self._alarm_until)
        return self._encode(frame)

    def _reset_detectors(self):
        self.det.reset()
        self.pose.reset()
        self._alarm_until = -1.0

    def run(self):
        win_n, win_ms, win_start = 0, 0.0, time.time()
        run_start = time.time()
        try:
            for t, frame in self.source:
                if self._stop.is_set():
                    break
                if t is None:
                    self._reset_detectors()
                    continue
                t1 = time.perf_counter()
                kps = self.pose(frame)
                ms = (time.perf_counter() - t1) * 1000
                alarmed = self.det.push(t, kps, frame.shape[0]) == "alarm"
                prob, state = self.det.last_prob, self.det.state
                if alarmed:
                    self.alarm_count += 1
                    self._alarm_until = t + ALARM_BANNER_S
                    self._log(f"[{t:7.2f}s] PHÁT HIỆN TÉ NGÃ! (p_fall={prob:.2f})")
                    if self.on_alarm:
                        raw = frame.copy()
                        annotated = draw_overlay(frame.copy(), kps, t, prob, state, self.thr, True)
                        self.on_alarm(AlarmEvent(t, prob, raw, annotated))
                if self.on_frame:
                    self.on_frame(t, prob, state, ms)
                self.total_frames += 1
                self.total_ms += ms
                win_n += 1
                win_ms += ms
                now = time.time()
                self._recent.append((now, ms))
                jpeg = None
                if self.viewers > 0:
                    jpeg = self._encode_stream(frame, kps, t, prob, state)
                self.state.update(jpeg=jpeg, t=t, p_fall=prob, state=state, pose_ms=self._avg_ms(),
                                  fps=self._fps(), alarm_count=self.alarm_count)
                if now - win_start >= self.report_every:
                    self._log(f"FPS={win_n / (now - win_start):.1f}  MoveNet={win_ms / win_n:.0f} ms  "
                              f"p_fall={prob:.2f}  state={state}")
                    win_n, win_ms, win_start = 0, 0.0, time.time()
        except KeyboardInterrupt:
            pass
        finally:
            if self.total_frames:
                el = time.time() - run_start
                self._log(f"\nTổng: {self.total_frames} frame trong {el:.1f}s | "
                          f"xử lý {self.total_frames / el:.1f} FPS | "
                          f"MoveNet trung bình {self.total_ms / self.total_frames:.0f} ms/frame | "
                          f"báo động: {self.alarm_count}")

    def _avg_ms(self):
        return sum(m for _, m in self._recent) / len(self._recent) if self._recent else 0.0

    def _fps(self):
        if len(self._recent) < 2:
            return 0.0
        span = self._recent[-1][0] - self._recent[0][0]
        return (len(self._recent) - 1) / span if span > 0 else 0.0
