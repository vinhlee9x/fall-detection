import numpy as np

import pipeline as pipeline_module
from pipeline import DetectionPipeline


class FakePose:
    def __init__(self):
        self.resets = 0

    def __call__(self, frame):
        kps = np.zeros((17, 3), dtype=np.float32)
        kps[:, 0] = 100
        kps[:, 1] = 100
        kps[:, 2] = 0.9
        return kps

    def reset(self):
        self.resets += 1


class FakeDetector:
    def __init__(self, alarm_at):
        self.alarm_at = alarm_at
        self.n = 0
        self.last_prob = 0.1
        self.state = "normal"
        self.resets = 0

    def push(self, t, kps, h):
        self.n += 1
        if self.n == self.alarm_at:
            self.last_prob = 0.9
            return "alarm"
        return None

    def reset(self):
        self.resets += 1
        self.n = 0


def make_source(n, loop_markers=()):
    for i in range(n):
        if i in loop_markers:
            yield None, None
        yield i * 0.1, np.zeros((120, 160, 3), dtype=np.uint8)


def make_pipeline(n=30, alarm_at=10, on_alarm=None, loop_markers=()):
    pose, det = FakePose(), FakeDetector(alarm_at)
    pipe = DetectionPipeline(pose, det, make_source(n, loop_markers), 0.5,
                             on_alarm=on_alarm, quiet=True)
    return pipe, pose, det


def test_alarm_event_called_once_with_distinct_images():
    events = []
    pipe, _, _ = make_pipeline(on_alarm=events.append)
    pipe.run()
    assert len(events) == 1
    ev = events[0]
    assert ev.raw.shape == ev.annotated.shape
    assert not np.array_equal(ev.raw, ev.annotated)
    assert ev.p_fall == 0.9
    assert pipe.state.snapshot()["alarm_count"] == 1


def test_no_encode_without_viewers(monkeypatch):
    calls = []
    real = pipeline_module.cv2.imencode
    monkeypatch.setattr(pipeline_module.cv2, "imencode", lambda *a, **k: calls.append(1) or real(*a, **k))
    pipe, _, _ = make_pipeline()
    pipe.run()
    assert calls == []
    assert pipe.state.jpeg is None


def test_encode_with_viewers():
    pipe, _, _ = make_pipeline()
    pipe.add_viewer()
    pipe.run()
    assert pipe.state.jpeg is not None
    assert pipe.state.jpeg[:2] == b"\xff\xd8"
    pipe.remove_viewer()
    assert pipe.viewers == 0


def test_viewer_count_never_negative():
    pipe, _, _ = make_pipeline()
    pipe.remove_viewer()
    assert pipe.viewers == 0


def test_loop_marker_resets_detectors():
    pipe, pose, det = make_pipeline(loop_markers=(15,))
    pipe.run()
    assert pose.resets == 1
    assert det.resets == 1


def test_on_frame_hook_called_per_frame():
    rows = []
    pose, det = FakePose(), FakeDetector(alarm_at=999)
    pipe = DetectionPipeline(pose, det, make_source(7), 0.5,
                             on_frame=lambda *a: rows.append(a), quiet=True)
    pipe.run()
    assert len(rows) == 7


def test_threaded_start_stop():
    pipe, _, _ = make_pipeline(n=10)
    pipe.start()
    pipe.join(5)
    assert not pipe.alive()
    assert pipe.error is None
    assert pipe.total_frames == 10
