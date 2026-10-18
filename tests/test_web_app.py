import base64
import json
import threading
import time

import pytest

from dashboard_config import DashboardConfig
from event_bus import EventBus
from pipeline import DetectionPipeline
from web_app import create_app

TOKEN = "123456789:ABCdefGhIJKlmnoPQRstuVWXyz_-12"


class FakeStore:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        (tmp_path / "20240101_101010.jpg").write_bytes(b"\xff\xd8jpg")
        self.ids = {"20240101_101010"}

    def list(self, limit=50):
        return [{"id": "20240101_101010", "notify": {"status": "sent", "error": None}}][:limit]

    def image_path(self, alarm_id, kind="annotated"):
        if alarm_id in self.ids and kind == "annotated":
            return str(self.tmp_path / (alarm_id + ".jpg"))
        return None


class FakeMetrics:
    def snapshot(self):
        return {"cpu_temp_c": None, "is_raspberry_pi": False}


class FakeNotifier:
    def send_test(self):
        return True, "Đã gửi tin nhắn thử"


@pytest.fixture
def env(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<h1>ok</h1>")
    (web / "app.js").write_text("1")
    config = DashboardConfig(str(tmp_path / "c.json"))
    pipe = DetectionPipeline(None, None, iter(()), 0.5, quiet=True)
    pipe.state.update(jpeg=b"\xff\xd8first", t=0.5)
    bus = EventBus()
    app = create_app(pipe, FakeMetrics(), FakeStore(tmp_path), config, FakeNotifier(), bus,
                     lambda: [[0.0, 0.1, "normal"]], "test.mp4", str(web))
    return app, config, pipe, bus


def basic(user, pw):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


def test_index_and_static(env):
    app, *_ = env
    c = app.test_client()
    assert c.get("/").status_code == 200
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/static/../c.json").status_code == 404


def test_headers(env):
    app, *_ = env
    r = app.test_client().get("/api/status")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["Cache-Control"] == "no-store"


def test_auth_required_when_password_set(env):
    app, config, *_ = env
    config._data["auth"]["password"] = "secret"
    c = app.test_client()
    assert c.get("/api/status").status_code == 401
    assert c.get("/").status_code == 401
    assert c.get("/events").status_code == 401
    assert c.get("/stream.mjpg").status_code == 401
    assert c.get("/api/alarms/20240101_101010/image").status_code == 401
    assert c.get("/api/status", headers=basic("admin", "wrong")).status_code == 401
    assert c.get("/api/status", headers=basic("admin", "secret")).status_code == 200


def test_no_auth_when_password_empty(env):
    app, *_ = env
    assert app.test_client().get("/api/status").status_code == 200


def test_put_requires_json(env):
    app, *_ = env
    r = app.test_client().put("/api/notify", data="x", content_type="text/plain")
    assert r.status_code == 415


def test_put_bad_token_400(env):
    app, *_ = env
    r = app.test_client().put("/api/notify", json={"bot_token": "bad"})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_put_non_object_body_400(env):
    app, *_ = env
    r = app.test_client().put("/api/notify", data="[1]", content_type="application/json")
    assert r.status_code == 400


def test_get_notify_never_contains_token(env):
    app, *_ = env
    c = app.test_client()
    r = c.put("/api/notify", json={"bot_token": TOKEN, "chat_id": "42", "enabled": True})
    assert r.status_code == 200
    assert TOKEN not in r.get_data(as_text=True)
    assert TOKEN not in c.get("/api/notify").get_data(as_text=True)


def test_notify_test_endpoint(env):
    app, *_ = env
    c = app.test_client()
    assert c.post("/api/notify/test", data="", content_type="text/plain").status_code == 415
    r = c.post("/api/notify/test", json={})
    assert r.get_json()["ok"] is True


def test_image_ok_and_cache_header(env):
    app, *_ = env
    r = app.test_client().get("/api/alarms/20240101_101010/image")
    assert r.status_code == 200
    assert "immutable" in r.headers["Cache-Control"]


@pytest.mark.parametrize("path", [
    "/api/alarms/..%2F..%2Fetc%2Fpasswd/image",
    "/api/alarms/20240101_101010/image?kind=../x",
    "/api/alarms/unknown/image",
    "/api/alarms/20240101_101010/image?kind=raw",
])
def test_image_rejects_bad_input(env, path):
    app, *_ = env
    assert app.test_client().get(path).status_code == 404


def test_alarms_limit_parsing(env):
    app, *_ = env
    c = app.test_client()
    assert c.get("/api/alarms?limit=abc").status_code == 200
    assert c.get("/api/alarms?limit=-5").status_code == 200


def test_stream_limit_503_and_release(env):
    app, *_ = env
    c = app.test_client()
    responses = [c.get("/stream.mjpg", buffered=False) for _ in range(4)]
    assert all(r.status_code == 200 for r in responses)
    over = c.get("/stream.mjpg", buffered=False)
    assert over.status_code == 503
    responses[0].response.close()
    again = c.get("/stream.mjpg", buffered=False)
    assert again.status_code == 200
    again.response.close()
    for r in responses[1:]:
        r.response.close()


def test_stream_viewer_count_returns_to_zero(env):
    app, _, pipe, _ = env
    r = app.test_client().get("/stream.mjpg", buffered=False)
    it = iter(r.response)
    assert pipe.viewers == 1
    assert b"first" in next(it)
    pipe.state.update(jpeg=b"\xff\xd8abc", t=1.0)
    chunk = next(it)
    assert b"image/jpeg" in chunk and b"\xff\xd8abc" in chunk
    r.response.close()
    assert pipe.viewers == 0


def test_sse_history_first_then_events(env):
    app, _, _, bus = env
    r = app.test_client().get("/events", buffered=False)
    it = iter(r.response)
    first = next(it).decode()
    assert first.startswith("event: history")
    assert json.loads(first.split("data: ")[1]) == [[0.0, 0.1, "normal"]]
    assert next(it).decode().startswith("event: status")
    assert next(it).decode().startswith("event: system")
    bus.publish("alarm", {"id": "x"})
    assert next(it).decode().startswith("event: alarm")
    r.response.close()
    time.sleep(0.05)
    assert bus._subs == set()


def test_sse_limit(env):
    app, *_ = env
    c = app.test_client()
    rs = [c.get("/events", buffered=False) for _ in range(8)]
    assert all(r.status_code == 200 for r in rs)
    assert c.get("/events", buffered=False).status_code == 503
    for r in rs:
        r.response.close()


def test_slow_sse_client_does_not_block_publisher(env):
    app, _, _, bus = env
    q = bus.subscribe()
    start = time.perf_counter()
    for i in range(10000):
        bus.publish("status", {"i": i})
    assert time.perf_counter() - start < 1.0
    assert q.qsize() == bus.maxsize
    assert q.get_nowait()[1]["i"] == 10000 - bus.maxsize
