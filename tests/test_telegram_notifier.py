import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from dashboard_config import DashboardConfig
from telegram_notifier import CAPTION_LIMIT, Notifier, render_caption

TOKEN = "123456789:ABCdefGhIJKlmnoPQRstuVWXyz_-12"


class FakeTelegram:
    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(n)
                outer.requests.append((self.path, self.headers.get("Content-Type"), body))
                status, payload, delay = outer.script.pop(0) if outer.script else (200, {"ok": True}, 0)
                if delay:
                    time.sleep(delay)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def cfg(tmp_path):
    c = DashboardConfig(str(tmp_path / "c.json"))
    c.update_telegram({"bot_token": TOKEN, "chat_id": "42", "enabled": True})
    return c


def run_notifier(cfg, script, backoff=(0, 0, 0, 0), sleeps=None):
    fake = FakeTelegram(script)
    results = []
    done = threading.Event()

    def on_result(alarm_id, status, error):
        results.append((alarm_id, status, error))
        done.set()

    sleeps = sleeps if sleeps is not None else []
    n = Notifier(cfg, on_result, api_base=fake.url, sleep=sleeps.append, backoff=backoff)
    n.enqueue("a1", b"\xff\xd8jpeg", {"time": "t", "p_fall": "0.9", "device": "pi"})
    assert done.wait(10)
    n.stop()
    fake.close()
    return results[0], fake, sleeps


def test_success(cfg):
    res, fake, _ = run_notifier(cfg, [(200, {"ok": True}, 0)])
    assert res == ("a1", "sent", None)
    assert "sendPhoto" in fake.requests[0][0]
    assert b"photo" in fake.requests[0][2]


def test_401_no_retry(cfg):
    res, fake, _ = run_notifier(cfg, [(401, {"ok": False}, 0)])
    assert res[1] == "failed" and res[2] == "Token bot sai"
    assert len(fake.requests) == 1


def test_500_then_200_retries(cfg):
    res, fake, sleeps = run_notifier(cfg, [(500, {}, 0), (200, {"ok": True}, 0)], backoff=(2, 5, 15, 45))
    assert res[1] == "sent"
    assert len(fake.requests) == 2
    assert sleeps == [2]


def test_429_respects_retry_after(cfg):
    res, fake, sleeps = run_notifier(
        cfg, [(429, {"parameters": {"retry_after": 30}}, 0), (200, {"ok": True}, 0)], backoff=(2, 5, 15, 45))
    assert res[1] == "sent"
    assert sleeps == [30]


def test_chat_not_found_and_403_messages(cfg):
    res, _, _ = run_notifier(cfg, [(400, {"description": "Bad Request: chat not found"}, 0)])
    assert "chat_id sai" in res[2]
    res, _, _ = run_notifier(cfg, [(403, {}, 0)])
    assert res[2] == "Bot bị chặn hoặc bị đuổi khỏi nhóm"


def test_five_attempts_then_failed(cfg):
    res, fake, sleeps = run_notifier(cfg, [(500, {}, 0)] * 6, backoff=(2, 5, 15, 45))
    assert res[1] == "failed"
    assert len(fake.requests) == 5
    assert sleeps == [2, 5, 15, 45]


def test_server_down_failed_network_error(cfg):
    results, done = [], threading.Event()
    n = Notifier(cfg, lambda *a: (results.append(a), done.set()), api_base="http://127.0.0.1:1",
                 sleep=lambda s: None, timeout=1)
    n.enqueue("a1", b"x", {})
    assert done.wait(15)
    n.stop()
    assert results[0][1] == "failed"
    assert results[0][2] == "Không kết nối được Telegram"


def test_token_not_in_logs_or_errors(cfg, caplog):
    caplog.set_level(logging.DEBUG)
    res, _, _ = run_notifier(cfg, [(500, {}, 0)] * 6)
    assert TOKEN not in str(res)
    assert TOKEN not in caplog.text


def test_enqueue_does_not_block_with_hung_server(cfg):
    fake = FakeTelegram([(200, {"ok": True}, 3)])
    n = Notifier(cfg, lambda *a: None, api_base=fake.url, sleep=lambda s: None)
    start = time.perf_counter()
    n.enqueue("a1", b"x", {})
    assert time.perf_counter() - start < 0.001
    n.stop()
    fake.close()


def test_queue_full_reports_failed(cfg):
    fake = FakeTelegram([(200, {"ok": True}, 2)] * 20)
    results = []
    n = Notifier(cfg, lambda *a: results.append(a), api_base=fake.url, sleep=lambda s: None)
    for i in range(14):
        n.enqueue(f"a{i}", b"x", {})
    assert any(r[2] == "hàng đợi đầy" for r in results)
    n.stop()
    fake.close()


def test_send_test_messages(cfg):
    fake = FakeTelegram([(200, {"ok": True}, 0), (401, {}, 0)])
    n = Notifier(cfg, lambda *a: None, api_base=fake.url)
    assert n.send_test()[0] is True
    assert n.send_test() == (False, "Token bot sai")
    n.stop()
    fake.close()


def test_send_test_without_credentials(tmp_path):
    c = DashboardConfig(str(tmp_path / "c.json"))
    n = Notifier(c, lambda *a: None, api_base="http://127.0.0.1:1")
    assert n.send_test()[0] is False
    n.stop()


def test_caption_truncated_and_replace_only_three_keys():
    text = render_caption("{time}|{p_fall}|{device}|{other}|" + "x" * 2000, {"time": "T", "p_fall": "0.9", "device": "D"})
    assert text.startswith("T|0.9|D|{other}|")
    assert len(text) == CAPTION_LIMIT


def test_config_change_applies_immediately(cfg):
    fake = FakeTelegram([(200, {"ok": True}, 0)])
    results, done = [], threading.Event()
    n = Notifier(cfg, lambda *a: (results.append(a), done.set()), api_base=fake.url)
    cfg.update_telegram({"enabled": False})
    n.enqueue("a1", b"x", {})
    assert done.wait(5)
    assert results[0][1] == "disabled"
    assert fake.requests == []
    n.stop()
    fake.close()
