from pathlib import Path

import pytest

from backend.core.config import Settings, get_default_secret_key


def test_generated_key_is_private_and_persistent(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_SECRET_KEY")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    key = get_default_secret_key()
    assert len(key) >= 32
    assert get_default_secret_key() == key
    assert (tmp_path / ".secret_key").stat().st_mode & 0o777 == 0o600


def test_unwritable_key_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_SECRET_KEY")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    def deny(*args, **kwargs):
        raise PermissionError("read-only volume")
    monkeypatch.setattr("backend.core.config.os.open", deny)
    with pytest.raises(RuntimeError, match="APP_SECRET_KEY"):
        get_default_secret_key()


def test_unreadable_existing_key_is_not_replaced(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_SECRET_KEY")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    keyfile = tmp_path / ".secret_key"
    keyfile.write_text("existing-private-key")
    original = Path.read_text
    def deny(path, *args, **kwargs):
        if path == keyfile:
            raise PermissionError("denied")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", deny)
    with pytest.raises(RuntimeError, match="APP_SECRET_KEY"):
        get_default_secret_key()
    assert original(keyfile) == "existing-private-key"


@pytest.mark.parametrize("key", ["", "  ", "tg-signer-default-secret-key-please-change-in-production-2024"])
def test_settings_rejects_insecure_explicit_keys(key):
    with pytest.raises(ValueError):
        Settings(secret_key=key)


def test_explicit_key_works_without_local_key_storage(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "secure-environment-managed-key")
    assert get_default_secret_key() == "secure-environment-managed-key"
