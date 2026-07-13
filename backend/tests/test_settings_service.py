from unittest.mock import MagicMock

import pytest

from app.services.settings_service import SettingsService


def test_bool_coercion():
    svc = SettingsService()
    assert svc.validate_and_coerce("auto_index_on_upload", True) == "true"
    assert svc.validate_and_coerce("auto_index_on_upload", False) == "false"
    assert svc.validate_and_coerce("auto_index_on_upload", "TRUE") == "true"
    assert svc.validate_and_coerce("auto_index_on_upload", "0") == "false"


def test_bool_runtime_default():
    svc = SettingsService()
    assert svc.get_runtime_value("auto_index_on_upload") is True


def test_bool_runtime_from_db():
    store = MagicMock()
    store.get.return_value = MagicMock(value="false")
    svc = SettingsService(store=store)
    assert svc.get_runtime_value("auto_index_on_upload") is False


def test_bool_runtime_invalid_fallback():
    store = MagicMock()
    store.get.return_value = MagicMock(value="not-a-bool")
    svc = SettingsService(store=store)
    assert svc.get_runtime_value("auto_index_on_upload") is True


def test_unknown_key_raises():
    svc = SettingsService()
    with pytest.raises(ValueError, match="未知配置项"):
        svc.validate_and_coerce("unknown_key", "x")
