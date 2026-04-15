from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

_BASE_DIR: Optional[Path] = None


def _probe_writable_dir(base: Path) -> bool:
    probe_dir = base / ".probe"
    test_file = probe_dir / ".write_test"
    try:
        probe_dir.mkdir(parents=True, exist_ok=True)
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        return True
    except Exception:
        return False
    finally:
        try:
            if test_file.exists():
                test_file.unlink()
        except Exception:
            pass
        try:
            if probe_dir.exists() and not any(probe_dir.iterdir()):
                probe_dir.rmdir()
        except Exception:
            pass


def is_writable_dir(path: Path) -> bool:
    return _probe_writable_dir(path)


def get_initial_data_dir() -> Path:
    env_data_dir = (os.getenv("APP_DATA_DIR") or "").strip()
    if env_data_dir:
        return Path(env_data_dir).expanduser()
    return Path("/data")


def get_writable_base_dir() -> Path:
    global _BASE_DIR
    if _BASE_DIR is not None:
        return _BASE_DIR

    preferred = Path("/data")
    if _probe_writable_dir(preferred):
        _BASE_DIR = preferred
        return _BASE_DIR

    fallback = Path(tempfile.gettempdir()) / "tg-signpulse"
    fallback.mkdir(parents=True, exist_ok=True)
    message = (
        f"WARNING: /data is not writable. Falling back to {fallback}; "
        "data may be non-persistent."
    )
    print(message)
    logging.getLogger("backend.storage").warning(message)
    _BASE_DIR = fallback
    return _BASE_DIR
