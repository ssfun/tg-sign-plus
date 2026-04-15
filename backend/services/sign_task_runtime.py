from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from tg_signer.ai_tools import OpenAIConfig
from tg_signer.core import UserSigner

from backend.services.task_flow_logger import TaskFlowLogger


class TaskLogHandler(logging.Handler):
    """将运行日志实时写入文本列表和结构化步骤流。"""

    def __init__(
        self,
        log_list: List[str],
        flow_items: List[Dict[str, object]],
        offset_ref: Dict[str, int],
        max_lines: int = 1000,
    ):
        super().__init__()
        self.flow_logger = TaskFlowLogger(log_list, flow_items, offset_ref, max_lines=max_lines)

    def emit(self, record):
        try:
            text = record.getMessage()
            stage = getattr(record, "flow_stage", "message")
            event = getattr(record, "flow_event", "log")
            level = record.levelname.lower()
            meta = getattr(record, "flow_meta", None)
            self.flow_logger.append(
                text,
                level=level,
                stage=stage,
                event=event,
                meta=meta,
            )
        except Exception:
            self.handleError(record)


class BackendUserSigner(UserSigner):
    """后端专用 UserSigner，适配数据库配置并禁止交互输入。"""

    def log(
        self,
        msg,
        level: str = "INFO",
        *,
        stage: str = "message",
        event: str = "log",
        meta: Optional[Dict[str, object]] = None,
        **kwargs,
    ):
        extra = kwargs.pop("extra", {}) or {}
        extra.update({
            "flow_stage": stage,
            "flow_event": event,
            "flow_meta": meta or {},
        })
        super().log(msg, level=level, extra=extra, **kwargs)

    @staticmethod
    def _load_backend_ai_config() -> Optional[OpenAIConfig]:
        from backend.services.config import get_config_service

        config = get_config_service().get_ai_config()
        if not config:
            return None

        api_key = (config.get("api_key") or "").strip()
        if not api_key:
            return None

        return OpenAIConfig(
            api_key=api_key,
            base_url=config.get("base_url") or None,
            model=config.get("model") or None,
        )

    def _get_config_repo(self):
        from backend.repositories.sign_task_config_repo import get_sign_task_config_repo

        return get_sign_task_config_repo()

    @property
    def task_dir(self):
        return self.tasks_dir / self._account / self.task_name

    def write_config(self, config):
        self._get_config_repo().save_config(
            self.task_name, self._account, config.to_jsonable()
        )
        self.config = config

    def ask_for_config(self):
        raise ValueError(
            f"任务配置文件不存在: {self.config_file}，且后端模式下禁止交互式输入。"
        )

    def reconfig(self):
        raise ValueError(
            f"任务配置文件不存在: {self.config_file}，且后端模式下禁止交互式输入。"
        )

    def load_config(self, cfg_cls=None):
        cfg_cls = cfg_cls or self.cfg_cls
        payload = self._get_config_repo().get_config(self.task_name, self._account)
        if not payload:
            config = self.reconfig()
        else:
            payload = dict(payload)
            payload.pop("name", None)
            config, from_old = cfg_cls.load(payload)
            if from_old:
                self.write_config(config)
        self.config = config
        return config

    def export(self):
        payload = self._get_config_repo().get_config(self.task_name, self._account)
        if not payload:
            raise FileNotFoundError(f"任务配置不存在: {self.task_name}")
        payload = dict(payload)
        payload.pop("name", None)
        return json.dumps(payload, ensure_ascii=False)

    def import_(self, config_str: str):
        payload = json.loads(config_str)
        if not isinstance(payload, dict):
            raise ValueError("任务配置必须为 JSON 对象")
        payload["account_name"] = self._account
        self._get_config_repo().save_config(self.task_name, self._account, payload)
        self.config = None

    def ensure_ai_cfg(self):
        cfg = self._load_backend_ai_config()
        if cfg:
            return cfg
        raise ValueError("未配置 AI 能力，请先在系统设置中保存 AI 配置")

    def ask_one(self):
        raise ValueError("后端模式下禁止交互式输入")
