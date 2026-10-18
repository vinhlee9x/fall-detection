import json
import os
import queue
import secrets
import threading
import time
import urllib.error
import urllib.request

DEFAULT_API_BASE = "https://api.telegram.org"
BACKOFF_S = (2, 5, 15, 45)
MAX_ATTEMPTS = 5
CAPTION_LIMIT = 1024
QUEUE_SIZE = 10
TIMEOUT_S = 10

ERR_NETWORK = "Không kết nối được Telegram"


def render_caption(template, context):
    text = template
    for key in ("time", "p_fall", "device"):
        text = text.replace("{" + key + "}", str(context.get(key, "")))
    return text[:CAPTION_LIMIT]


def describe_error(status, payload):
    desc = ((payload or {}).get("description") or "").lower()
    if status == 0:
        return ERR_NETWORK
    if status == 401:
        return "Token bot sai"
    if status == 400 and "chat not found" in desc:
        return "chat_id sai hoặc bot chưa được nhắn tin/thêm vào nhóm"
    if status == 403:
        return "Bot bị chặn hoặc bị đuổi khỏi nhóm"
    if status == 429:
        return "Gửi quá nhanh, đang chờ"
    return f"Telegram trả lỗi HTTP {status}"


def build_multipart(fields, files):
    boundary = secrets.token_hex(16)
    body = bytearray()
    for name, value in fields.items():
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                 f"{value}\r\n").encode()
    for name, (filename, data, ctype) in files.items():
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
                 f'filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n').encode()
        body += data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


class Notifier:
    def __init__(self, config, on_result, api_base=None, sleep=None, backoff=BACKOFF_S, timeout=TIMEOUT_S):
        self.config = config
        self.on_result = on_result
        self.api_base = (api_base or os.environ.get("FALL_TELEGRAM_API_BASE") or DEFAULT_API_BASE).rstrip("/")
        self.sleep = sleep or time.sleep
        self.backoff = backoff
        self.timeout = timeout
        self._q = queue.Queue(maxsize=QUEUE_SIZE)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, name="telegram", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass

    def enqueue(self, alarm_id, jpeg_bytes, context):
        try:
            self._q.put_nowait((alarm_id, jpeg_bytes, context))
            return True
        except queue.Full:
            self._report(alarm_id, "failed", "hàng đợi đầy")
            return False

    def _report(self, alarm_id, status, error=None):
        try:
            self.on_result(alarm_id, status, error)
        except Exception:
            pass

    def _post(self, method, fields, files=None):
        token = self.config.telegram()["bot_token"]
        url = f"{self.api_base}/bot{token}/{method}"
        try:
            if files:
                body, ctype = build_multipart(fields, files)
            else:
                body, ctype = json.dumps(fields).encode(), "application/json"
            req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype}, method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, self._json(resp.read())
        except urllib.error.HTTPError as e:
            try:
                return e.code, self._json(e.read())
            except Exception:
                return e.code, None
        except Exception:
            return 0, None

    @staticmethod
    def _json(raw):
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
            return data if isinstance(data, dict) else None
        except ValueError:
            return None

    def send_test(self):
        tg = self.config.telegram()
        if not tg["bot_token"] or not tg["chat_id"]:
            return False, "Chưa nhập token hoặc chat_id"
        status, payload = self._post("sendMessage", {"chat_id": tg["chat_id"],
                                                     "text": "✅ Tin nhắn thử từ hệ thống phát hiện té ngã"})
        if status == 200:
            return True, "Đã gửi tin nhắn thử"
        return False, describe_error(status, payload)

    def _worker(self):
        while not self._stop.is_set():
            item = self._q.get()
            if item is None:
                break
            self._deliver(*item)

    def _deliver(self, alarm_id, jpeg, context):
        error = ERR_NETWORK
        for attempt in range(MAX_ATTEMPTS):
            tg = self.config.telegram()
            if not tg["enabled"]:
                self._report(alarm_id, "disabled", None)
                return
            fields = {"chat_id": tg["chat_id"], "caption": render_caption(tg["message_template"], context)}
            status, payload = self._post("sendPhoto", fields, {"photo": ("alarm.jpg", jpeg, "image/jpeg")})
            if status == 200:
                self._report(alarm_id, "sent", None)
                return
            error = describe_error(status, payload)
            if 400 <= status < 500 and status != 429:
                break
            if attempt == MAX_ATTEMPTS - 1:
                break
            wait = self.backoff[min(attempt, len(self.backoff) - 1)]
            if status == 429:
                retry_after = ((payload or {}).get("parameters") or {}).get("retry_after")
                if isinstance(retry_after, (int, float)):
                    wait = max(wait, retry_after)
            self.sleep(wait)
        self._report(alarm_id, "failed", error)
