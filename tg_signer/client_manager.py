from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import random
from collections import defaultdict
from typing import Union
from urllib import parse

from pyrogram import Client as BaseClient
from pyrogram.methods.utilities.idle import idle
from pyrogram.session import Session
from pyrogram.storage import MemoryStorage

logger = logging.getLogger("tg-signer")

Session.START_TIMEOUT = 5

_CLIENT_INSTANCES: dict[str, "Client"] = {}
_CLIENT_REFS: defaultdict[str, int] = defaultdict(int)
_CLIENT_ASYNC_LOCKS: dict[str, asyncio.Lock] = {}


class Client(BaseClient):
    def __init__(self, name: str, *args, **kwargs):
        key = kwargs.pop("key", None)
        super().__init__(name, *args, **kwargs)
        self.key = key or str(pathlib.Path(self.workdir).joinpath(self.name).resolve())
        if self.in_memory and self.session_string:
            self.storage = MemoryStorage(self.name, self.session_string)

    async def __aenter__(self):
        lock = _CLIENT_ASYNC_LOCKS.get(self.key)
        if lock is None:
            lock = asyncio.Lock()
            _CLIENT_ASYNC_LOCKS[self.key] = lock
        async with lock:
            _CLIENT_REFS[self.key] += 1
            if _CLIENT_REFS[self.key] == 1:
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        if not self.is_connected:
                            await self.connect()

                        try:
                            await self.get_me()
                        except Exception as e:
                            raise ConnectionError(f"Session invalid: {e}")

                        try:
                            await self.start()
                        except ConnectionError as e:
                            if "already connected" not in str(e).lower():
                                raise e

                        if hasattr(self, "storage") and hasattr(self.storage, "conn"):
                            try:
                                self.storage.conn.execute("PRAGMA journal_mode=WAL")
                                self.storage.conn.execute("PRAGMA busy_timeout=30000")
                            except Exception as e:
                                logger.error(f"Failed to enable WAL mode: {e}")
                        break
                    except Exception as e:
                        is_locked = "database is locked" in str(e)
                        if is_locked and attempt < max_retries - 1:
                            try:
                                if self.is_connected:
                                    await self.stop()
                            except Exception:
                                pass

                            wait_time = (attempt + 1) * 2
                            logger.warning(
                                f"Database locked when starting client {self.name}, retrying in {wait_time}s... ({attempt + 1}/{max_retries})"
                            )
                            await asyncio.sleep(wait_time)
                            continue

                        _CLIENT_REFS[self.key] -= 1
                        if _CLIENT_REFS[self.key] <= 0:
                            _CLIENT_REFS.pop(self.key, None)
                            _CLIENT_INSTANCES.pop(self.key, None)
                            try:
                                await self.stop()
                            except Exception:
                                pass
                        raise e
            return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        lock = _CLIENT_ASYNC_LOCKS.get(self.key)
        if lock is None:
            return
        async with lock:
            _CLIENT_REFS[self.key] -= 1
            if _CLIENT_REFS[self.key] == 0:
                try:
                    await self.stop()
                except Exception:
                    pass

    async def log_out(self):
        await super().log_out()


def get_api_config():
    api_id_env = os.environ.get("TG_API_ID")
    api_hash_env = os.environ.get("TG_API_HASH")

    api_id = 611335
    if api_id_env:
        try:
            api_id = int(api_id_env)
        except (TypeError, ValueError):
            pass

    if isinstance(api_hash_env, str) and api_hash_env.strip():
        api_hash = api_hash_env.strip()
    else:
        api_hash = "d524b414d21f4d37f08684c1df41ac9c"

    return api_id, api_hash


def get_proxy(proxy: str = None):
    proxy = proxy or os.environ.get("TG_PROXY")
    if proxy:
        r = parse.urlparse(proxy)
        return {
            "scheme": r.scheme,
            "hostname": r.hostname,
            "port": r.port,
            "username": r.username,
            "password": r.password,
        }
    return None


def get_client(
    name: str = "my_account",
    proxy: dict = None,
    workdir: Union[str, pathlib.Path] = ".",
    session_string: str = None,
    in_memory: bool = False,
    api_id: int = None,
    api_hash: str = None,
    **kwargs,
) -> Client:
    proxy = proxy or get_proxy()
    if not api_id or not api_hash:
        _api_id, _api_hash = get_api_config()
        api_id = api_id or _api_id
        api_hash = api_hash or _api_hash

    key = str(pathlib.Path(workdir).joinpath(name).resolve())
    if key in _CLIENT_INSTANCES:
        return _CLIENT_INSTANCES[key]
    client = Client(
        name,
        api_id=api_id,
        api_hash=api_hash,
        proxy=proxy,
        workdir=workdir,
        session_string=session_string,
        in_memory=in_memory,
        key=key,
        **kwargs,
    )
    _CLIENT_INSTANCES[key] = client
    return client


async def close_client_by_name(name: str, workdir: Union[str, pathlib.Path] = "."):
    key = str(pathlib.Path(workdir).joinpath(name).resolve())

    lock = _CLIENT_ASYNC_LOCKS.get(key)
    if lock:
        try:
            await asyncio.wait_for(lock.acquire(), timeout=5.0)
            try:
                _CLIENT_REFS[key] = 0
            finally:
                lock.release()
        except asyncio.TimeoutError:
            logger.warning(
                f"Timeout waiting for lock on client {name}, proceeding with forceful cleanup"
            )
            _CLIENT_REFS[key] = 0

    client = _CLIENT_INSTANCES.get(key)
    if client:
        try:
            if client.is_connected:
                await client.stop()
        except Exception as e:
            logger.warning(f"Error stopping client {name}: {e}")
        finally:
            _CLIENT_INSTANCES.pop(key, None)

    if key in _CLIENT_ASYNC_LOCKS:
        _CLIENT_ASYNC_LOCKS.pop(key, None)
    if key in _CLIENT_REFS:
        _CLIENT_REFS.pop(key, None)
