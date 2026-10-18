import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = "123456789:ABCdefGhIJKlmnoPQRstuVWXyz_-12"
received = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        received.append((self.path, body))
        data = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_fake(port):
    server = HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def stop_fake(server):
    server.shutdown()
    server.server_close()


def get_json(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as r:
        return json.loads(r.read())


def wait_for(predicate, timeout, label):
    end = time.time() + timeout
    while time.time() < end:
        value = predicate()
        if value:
            return value
        time.sleep(1)
    raise SystemExit(f"HẾT GIỜ chờ: {label}")


def check(label, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + label + (f" | {detail}" if detail else ""), flush=True)
    if not condition:
        raise SystemExit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", default=os.path.join(HERE, ".venv311", "bin", "python"))
    ap.add_argument("--video", default=os.path.join(HERE, "test.mp4"))
    ap.add_argument("--port", type=int, default=18080)
    ap.add_argument("--fake-port", type=int, default=18099)
    args = ap.parse_args()

    work = tempfile.mkdtemp(prefix="e2e_")
    config = os.path.join(work, "dashboard_config.json")
    with open(config, "w") as f:
        json.dump({"telegram": {"enabled": True, "bot_token": TOKEN, "chat_id": "42",
                                "message_template": "Té ngã {time} p={p_fall} {device}"},
                   "auth": {"username": "admin", "password": ""}, "max_alarms": 100}, f)
    os.chmod(config, 0o600)

    fake = start_fake(args.fake_port)
    env = dict(os.environ, FALL_TELEGRAM_API_BASE=f"http://127.0.0.1:{args.fake_port}")
    log_path = os.path.join(work, "dashboard.log")
    log = open(log_path, "w")
    proc = subprocess.Popen([args.python, "-u", "fall_dashboard.py", args.video, "--loop", "--port", str(args.port),
                             "--host", "127.0.0.1", "--config", config, "--alarm-dir", os.path.join(work, "alarms")],
                            cwd=HERE, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{args.port}"
    try:
        wait_for(lambda: _safe(lambda: get_json(base, "/api/status")), 60, "dashboard khởi động")
        print("Dashboard đã chạy, chờ báo động đầu tiên (~30s)...", flush=True)

        first = wait_for(lambda: get_json(base, "/api/alarms"), 90, "báo động đầu tiên")
        alarm_id = first[0]["id"]
        wait_for(lambda: get_json(base, "/api/alarms")[0]["notify"]["status"] == "sent", 20, "Telegram sent")
        check("báo động 1 được lưu và gửi Telegram", True)
        for kind in ("annotated", "raw"):
            with urllib.request.urlopen(f"{base}/api/alarms/{alarm_id}/image?kind={kind}") as r:
                check(f"ảnh {kind} tải được", r.status == 200 and len(r.read()) > 1000)
        photo_reqs = [r for r in received if "sendPhoto" in r[0]]
        check("server giả nhận sendPhoto", len(photo_reqs) == 1)
        body = photo_reqs[0][1].decode("latin-1")
        check("caption đúng mẫu", "Té ngã" in body or "T\xc3\xa9 ng\xc3\xa3" in body)
        check("token không có trong response notify", TOKEN not in json.dumps(get_json(base, "/api/notify")))

        print("Tắt server Telegram giả, chờ báo động kế tiếp (retry ~67s)...", flush=True)
        stop_fake(fake)
        sent_before = len(first)
        wait_for(lambda: len(get_json(base, "/api/alarms")) > sent_before, 90, "báo động 2")
        failed = wait_for(lambda: [a for a in get_json(base, "/api/alarms")
                                   if a["notify"]["status"] == "failed"], 150, "trạng thái failed")
        check("UI nhận lỗi tiếng Việt", failed[0]["notify"]["error"] == "Không kết nối được Telegram",
              failed[0]["notify"]["error"])
        status = get_json(base, "/api/status")
        check("pipeline vẫn chạy khi Telegram lỗi", status["running"] and status["fps"] > 5, f"fps={status['fps']:.1f}")

        print("Bật lại server giả, chờ báo động kế tiếp...", flush=True)
        received.clear()
        fake = start_fake(args.fake_port)
        count = len(get_json(base, "/api/alarms"))
        wait_for(lambda: len(get_json(base, "/api/alarms")) > count, 90, "báo động 3")
        wait_for(lambda: get_json(base, "/api/alarms")[0]["notify"]["status"] == "sent", 30, "Telegram sent lại")
        check("gửi lại thành công sau khi mạng trở lại", any("sendPhoto" in r[0] for r in received))
        print("E2E OK")
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        leaked = TOKEN in open(log_path).read()
        print("Token trong log:", "CÓ (LỖI)" if leaked else "không")
        print("Log:", log_path)
        if leaked:
            sys.exit(1)


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


if __name__ == "__main__":
    main()
