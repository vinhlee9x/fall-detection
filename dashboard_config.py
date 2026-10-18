import json
import os
import re
import threading

TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")
CHAT_RE = re.compile(r"^(-?\d+|@\w{5,})$")
DEFAULT_TEMPLATE = "🚨 Phát hiện té ngã!\nThời gian: {time}\nXác suất: {p_fall}\nThiết bị: {device}"


class ConfigError(ValueError):
    pass


def default_config():
    return {
        "telegram": {"enabled": False, "bot_token": "", "chat_id": "", "message_template": DEFAULT_TEMPLATE},
        "auth": {"username": "admin", "password": ""},
        "max_alarms": 100,
    }


def _write_secure(path, data):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


class DashboardConfig:
    def __init__(self, path="dashboard_config.json"):
        self.path = path
        self._lock = threading.Lock()
        self.warning = None
        self._data = self._load()

    def _load(self):
        data = default_config()
        if not os.path.exists(self.path):
            _write_secure(self.path, data)
            return data
        try:
            with open(self.path) as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("không phải object")
        except (OSError, ValueError):
            os.replace(self.path, self.path + ".corrupt")
            self.warning = f"{self.path} bị hỏng, đã đổi tên thành .corrupt và dùng cấu hình mặc định"
            _write_secure(self.path, data)
            return data
        for key in ("telegram", "auth"):
            if isinstance(loaded.get(key), dict):
                data[key].update(loaded[key])
        if isinstance(loaded.get("max_alarms"), int) and loaded["max_alarms"] > 0:
            data["max_alarms"] = loaded["max_alarms"]
        return data

    def telegram(self):
        with self._lock:
            return dict(self._data["telegram"])

    def auth(self):
        with self._lock:
            return dict(self._data["auth"])

    @property
    def max_alarms(self):
        with self._lock:
            return self._data["max_alarms"]

    def public_view(self):
        tg = self.telegram()
        token = tg["bot_token"]
        return {"enabled": bool(tg["enabled"]), "has_token": bool(token),
                "token_hint": ("…" + token[-4:]) if token else "",
                "chat_id": tg["chat_id"], "message_template": tg["message_template"]}

    def update_telegram(self, patch):
        if not isinstance(patch, dict):
            raise ConfigError("Dữ liệu không hợp lệ")
        with self._lock:
            tg = dict(self._data["telegram"])
            if "enabled" in patch:
                if not isinstance(patch["enabled"], bool):
                    raise ConfigError("enabled phải là true/false")
                tg["enabled"] = patch["enabled"]
            token = patch.get("bot_token")
            if token:
                if not isinstance(token, str) or not TOKEN_RE.match(token):
                    raise ConfigError("Token bot sai định dạng")
                tg["bot_token"] = token
            if "chat_id" in patch:
                chat = str(patch["chat_id"]).strip()
                if chat and not CHAT_RE.match(chat):
                    raise ConfigError("chat_id sai định dạng")
                tg["chat_id"] = chat
            if "message_template" in patch:
                tpl = patch["message_template"]
                if not isinstance(tpl, str) or not tpl.strip() or len(tpl) > 1000:
                    raise ConfigError("Mẫu tin nhắn rỗng hoặc quá dài")
                tg["message_template"] = tpl
            if tg["enabled"] and not (tg["bot_token"] and tg["chat_id"]):
                raise ConfigError("Cần có token và chat_id để bật Telegram")
            self._data["telegram"] = tg
            _write_secure(self.path, self._data)
        return self.public_view()
