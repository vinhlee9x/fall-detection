import argparse
import json
import os
import signal
import socket
import threading
import time
from collections import deque

from werkzeug.serving import make_server

from alarm_store import AlarmStore, encode_jpeg
from dashboard_config import DashboardConfig
from event_bus import EventBus
from system_metrics import SystemMetrics
from telegram_notifier import Notifier
from web_app import create_app

HERE = os.path.dirname(os.path.abspath(__file__))
STATUS_HZ = 4
HISTORY_S = 60


class Dashboard:
    def __init__(self, pipeline, metrics, store, config, notifier, bus, source_label, target_fps):
        self.pipeline, self.metrics, self.store = pipeline, metrics, store
        self.config, self.notifier, self.bus = config, notifier, bus
        self.source_label, self.target_fps = source_label, target_fps
        self.history = deque(maxlen=STATUS_HZ * HISTORY_S)
        self._stop = threading.Event()
        self._sampler = threading.Thread(target=self._sample_loop, name="status", daemon=True)

    def on_alarm(self, event):
        tg = self.config.telegram()
        alarm_id = None
        try:
            alarm_id = self.store.save(event, self.pipeline.thr,
                                       "pending" if tg["enabled"] else "disabled")
        except OSError as e:
            print(f"Không lưu được ảnh báo động: {e.__class__.__name__}", flush=True)
        if alarm_id:
            self.bus.publish("alarm", self.store.get(alarm_id))
        if tg["enabled"]:
            context = {"time": time.strftime("%H:%M:%S %d/%m/%Y"), "p_fall": f"{event.p_fall:.2f}",
                       "device": socket.gethostname()}
            self.notifier.enqueue(alarm_id, encode_jpeg(event.annotated), context)

    def on_notify_result(self, alarm_id, status, error):
        if not alarm_id:
            return
        self.store.update_notify(alarm_id, status, error)
        self.bus.publish("notify", {"id": alarm_id, "status": status, "error": error})

    def _sample_loop(self):
        tick = 0
        while not self._stop.wait(1.0 / STATUS_HZ):
            snap = self.pipeline.state.snapshot()
            self.history.append([round(snap["t"], 2), round(snap["p_fall"], 3), snap["state"]])
            snap.update(source=self.source_label, viewers=self.pipeline.viewers,
                        target_fps=self.target_fps, running=self.pipeline.alive())
            self.bus.publish("status", snap)
            tick += 1
            if tick % STATUS_HZ == 0:
                self.bus.publish("system", self.metrics.snapshot())

    def start(self):
        self.metrics.start()
        self._sampler.start()

    def stop(self):
        self._stop.set()
        self.metrics.stop()
        self.notifier.stop()


def build_parser():
    ap = argparse.ArgumentParser(description="Dashboard giám sát phát hiện té ngã")
    ap.add_argument("video", nargs="?", help="file video; bỏ trống để dùng camera")
    ap.add_argument("--loop", action="store_true", help="lặp lại video khi hết")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--size", default="640x480")
    ap.add_argument("--config", default="dashboard_config.json")
    ap.add_argument("--alarm-dir", default="alarms")
    return ap


def main():
    from fall_core import MoveNet, FallDetector, onnx_predictor
    from frame_sources import frames_from_camera, frames_from_video
    from pipeline import DetectionPipeline

    args = build_parser().parse_args()
    cfg = json.load(open(os.path.join(HERE, "fall_config.json")))
    period = 1.0 / cfg["target_fps"]
    pose = MoveNet(os.path.join(HERE, cfg["movenet"]), num_threads=args.threads)
    det = FallDetector(onnx_predictor(os.path.join(HERE, cfg["model"])), threshold=cfg["threshold"],
                       win_s=cfg["win_s"], stride_s=cfg["stride_s"], k=cfg["k"], n=cfg["n"],
                       confirm_s=cfg["confirm_s"])
    if args.video:
        src = frames_from_video(args.video, period, loop=args.loop, realtime=True)
        label = os.path.basename(args.video)
    else:
        src = frames_from_camera(args.size, args.cam, period)
        label = "Camera"

    config = DashboardConfig(args.config)
    if config.warning:
        print(config.warning, flush=True)
    store = AlarmStore(args.alarm_dir, config.max_alarms)
    bus = EventBus()
    metrics = SystemMetrics(disk_path=HERE)
    pipeline = DetectionPipeline(pose, det, src, cfg["threshold"])
    holder = {}
    notifier = Notifier(config, lambda *a: holder["dash"].on_notify_result(*a))
    dash = Dashboard(pipeline, metrics, store, config, notifier, bus, label, cfg["target_fps"])
    holder["dash"] = dash
    pipeline.on_alarm = dash.on_alarm

    app = create_app(pipeline, metrics, store, config, notifier, bus, lambda: list(dash.history),
                     label, os.path.join(HERE, "web"), target_fps=cfg["target_fps"])
    server = make_server(args.host, args.port, app, threaded=True)

    if not config.auth().get("password"):
        print("CẢNH BÁO: chưa đặt mật khẩu (auth.password trong dashboard_config.json); "
              "bất kỳ ai trong mạng đều xem được camera.", flush=True)
    print(f"Dashboard: http://{socket.gethostname()}:{args.port}", flush=True)

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *a: stop.set())
    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    pipeline.start()
    dash.start()
    threading.Thread(target=server.serve_forever, name="http", daemon=True).start()
    code = 0
    try:
        while not stop.wait(0.5):
            if pipeline.error is not None:
                print(f"Pipeline dừng do lỗi: {pipeline.error.__class__.__name__}", flush=True)
                code = 1
                break
    finally:
        pipeline.stop()
        dash.stop()
        server.shutdown()
        pipeline.join(2)
        os._exit(code)


if __name__ == "__main__":
    main()
