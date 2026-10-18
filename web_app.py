import hmac
import json
import queue
import threading

from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory

from dashboard_config import ConfigError

MAX_STREAMS = 4
MAX_SSE = 8
HEARTBEAT_S = 15
BOUNDARY = "frame"


def sse_format(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_app(pipeline, metrics, store, config, notifier, bus, history_fn, source_label,
               web_dir, target_fps=10, max_streams=MAX_STREAMS, max_sse=MAX_SSE):
    app = Flask(__name__, static_folder=None)
    stream_slots = threading.BoundedSemaphore(max_streams)
    sse_slots = threading.BoundedSemaphore(max_sse)

    @app.before_request
    def check_auth():
        auth_cfg = config.auth()
        password = auth_cfg.get("password") or ""
        if not password:
            return None
        cred = request.authorization
        if cred and cred.username is not None and cred.password is not None:
            user_ok = hmac.compare_digest(cred.username.encode(), str(auth_cfg.get("username", "")).encode())
            pass_ok = hmac.compare_digest(cred.password.encode(), password.encode())
            if user_ok and pass_ok:
                return None
        return Response("Cần đăng nhập", 401, {"WWW-Authenticate": 'Basic realm="Fall dashboard"'})

    @app.after_request
    def set_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:"
        if request.endpoint == "alarm_image" and resp.status_code == 200:
            resp.headers["Cache-Control"] = "private, max-age=31536000, immutable"
        elif request.path.startswith("/api/") or request.path in ("/events", "/stream.mjpg"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def require_json():
        if request.mimetype != "application/json":
            abort(415)

    @app.get("/")
    def index():
        return send_from_directory(web_dir, "index.html")

    @app.get("/static/<path:name>")
    def static_files(name):
        return send_from_directory(web_dir, name)

    def status_payload():
        data = pipeline.state.snapshot()
        data.update(source=source_label, viewers=pipeline.viewers, target_fps=target_fps,
                    running=pipeline.alive())
        return data

    @app.get("/api/status")
    def api_status():
        return jsonify(status_payload())

    @app.get("/api/system")
    def api_system():
        return jsonify(metrics.snapshot())

    @app.get("/api/alarms")
    def api_alarms():
        try:
            limit = max(1, min(200, int(request.args.get("limit", 50))))
        except ValueError:
            limit = 50
        return jsonify(store.list(limit))

    @app.get("/api/alarms/<alarm_id>/image", endpoint="alarm_image")
    def alarm_image(alarm_id):
        kind = request.args.get("kind", "annotated")
        path = store.image_path(alarm_id, kind)
        if not path:
            abort(404)
        return send_file(path, mimetype="image/jpeg")

    @app.get("/api/notify")
    def get_notify():
        return jsonify(config.public_view())

    @app.put("/api/notify")
    def put_notify():
        require_json()
        patch = request.get_json(silent=True)
        try:
            return jsonify(config.update_telegram(patch))
        except ConfigError as e:
            return jsonify({"error": str(e)}), 400

    @app.post("/api/notify/test")
    def notify_test():
        require_json()
        ok, message = notifier.send_test()
        return jsonify({"ok": ok, "message": message}), (200 if ok else 502)

    @app.get("/stream.mjpg")
    def stream():
        if not stream_slots.acquire(blocking=False):
            return jsonify({"error": "Quá số luồng video cho phép"}), 503

        pipeline.add_viewer()

        def generate():
            seq, last = -1, None
            while True:
                new_seq, jpeg = pipeline.state.wait_frame(seq, 2.0)
                timed_out = new_seq == seq
                seq = new_seq
                if jpeg is None or (jpeg is last and not timed_out):
                    continue
                last = jpeg
                yield (f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                       f"Content-Length: {len(jpeg)}\r\n\r\n").encode() + jpeg + b"\r\n"

        def release():
            pipeline.remove_viewer()
            stream_slots.release()

        resp = Response(generate(), mimetype=f"multipart/x-mixed-replace; boundary={BOUNDARY}")
        resp.call_on_close(release)
        return resp

    @app.get("/events")
    def events():
        if not sse_slots.acquire(blocking=False):
            return jsonify({"error": "Quá số kết nối sự kiện cho phép"}), 503
        q = bus.subscribe()

        def generate():
            yield sse_format("history", history_fn())
            yield sse_format("status", status_payload())
            yield sse_format("system", metrics.snapshot())
            while True:
                try:
                    event, data = q.get(timeout=HEARTBEAT_S)
                except queue.Empty:
                    yield ": heartbeat\n\n"
                    continue
                yield sse_format(event, data)

        def release():
            bus.unsubscribe(q)
            sse_slots.release()

        resp = Response(generate(), mimetype="text/event-stream", headers={"X-Accel-Buffering": "no"})
        resp.call_on_close(release)
        return resp

    return app
