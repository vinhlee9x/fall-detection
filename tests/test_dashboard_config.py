import json
import os
import stat

import pytest

from dashboard_config import ConfigError, DashboardConfig

TOKEN = "123456789:ABCdefGhIJKlmnoPQRstuVWXyz_-12"


def test_default_created_with_600(tmp_path):
    p = tmp_path / "c.json"
    DashboardConfig(str(p))
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def test_public_view_hides_token(tmp_path):
    c = DashboardConfig(str(tmp_path / "c.json"))
    c.update_telegram({"bot_token": TOKEN, "chat_id": "123"})
    view = json.dumps(c.public_view())
    assert TOKEN not in view
    assert c.public_view()["has_token"] is True
    assert c.public_view()["token_hint"] == "…" + TOKEN[-4:]


def test_empty_token_keeps_old(tmp_path):
    c = DashboardConfig(str(tmp_path / "c.json"))
    c.update_telegram({"bot_token": TOKEN, "chat_id": "123"})
    c.update_telegram({"bot_token": "", "chat_id": "456"})
    assert c.telegram()["bot_token"] == TOKEN
    assert c.telegram()["chat_id"] == "456"


@pytest.mark.parametrize("patch", [
    {"chat_id": "abc"}, {"chat_id": "@ab"}, {"bot_token": "bad"}, {"enabled": "yes"},
    {"message_template": ""}, {"enabled": True},
])
def test_invalid_patch_rejected(tmp_path, patch):
    c = DashboardConfig(str(tmp_path / "c.json"))
    with pytest.raises(ConfigError):
        c.update_telegram(patch)


def test_valid_chat_ids(tmp_path):
    c = DashboardConfig(str(tmp_path / "c.json"))
    for chat in ("123", "-100123", "@mychannel"):
        c.update_telegram({"chat_id": chat})
        assert c.telegram()["chat_id"] == chat


def test_permissions_kept_after_update(tmp_path):
    p = tmp_path / "c.json"
    c = DashboardConfig(str(p))
    c.update_telegram({"bot_token": TOKEN, "chat_id": "1"})
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def test_corrupt_file_renamed_and_defaults(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{oops")
    c = DashboardConfig(str(p))
    assert c.warning
    assert (tmp_path / "c.json.corrupt").exists()
    assert c.telegram()["enabled"] is False


def test_persisted_values_reload(tmp_path):
    p = str(tmp_path / "c.json")
    c = DashboardConfig(p)
    c.update_telegram({"bot_token": TOKEN, "chat_id": "1", "enabled": True})
    again = DashboardConfig(p)
    assert again.telegram()["enabled"] is True
    assert again.telegram()["bot_token"] == TOKEN
