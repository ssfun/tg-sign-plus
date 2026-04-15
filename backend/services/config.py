"""
配置管理服务
提供任务配置的导入导出功能
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.config import get_settings
from backend.utils.storage import is_writable_dir

settings = get_settings()


class ConfigService:
    """配置管理服务类"""

    def __init__(self):
        from backend.repositories.sign_task_config_repo import get_sign_task_config_repo

        self.workdir = settings.resolve_workdir()
        self._sign_config_repo = get_sign_task_config_repo()

    @staticmethod
    def _load_app_setting(key: str) -> Optional[Dict[str, Any]]:
        from backend.core.database import get_session_local
        from backend.models.app_setting import AppSetting

        db = get_session_local()()
        try:
            row = db.query(AppSetting).filter(AppSetting.key == key).first()
            if not row or not row.value_json:
                return None
            value = json.loads(row.value_json)
            return value if isinstance(value, dict) else None
        finally:
            db.close()

    @staticmethod
    def _save_app_setting(key: str, value: Dict[str, Any]) -> bool:
        from datetime import datetime

        from backend.core.database import get_session_local
        from backend.models.app_setting import AppSetting

        db = get_session_local()()
        try:
            row = db.query(AppSetting).filter(AppSetting.key == key).first()
            payload = json.dumps(value, ensure_ascii=False)
            if row:
                row.value_json = payload
                row.updated_at = datetime.utcnow()
            else:
                db.add(AppSetting(key=key, value_json=payload))
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False
        finally:
            db.close()

    @staticmethod
    def _delete_app_setting(key: str) -> bool:
        from backend.core.database import get_session_local
        from backend.models.app_setting import AppSetting

        db = get_session_local()()
        try:
            db.query(AppSetting).filter(AppSetting.key == key).delete()
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False
        finally:
            db.close()

    def list_sign_tasks(self) -> List[str]:
        """获取所有签到任务名称列表"""
        tasks = [item["name"] for item in self._sign_config_repo.list_configs()]
        return sorted(list(set(tasks)))  # 去重并排序

    def has_sign_config(self, task_name: str, account_name: Optional[str] = None) -> bool:
        """检查签到任务配置是否存在"""
        return self._sign_config_repo.get_config(task_name, account_name) is not None

    def get_sign_config(
        self, task_name: str, account_name: Optional[str] = None
    ) -> Optional[Dict]:
        """获取签到任务配置"""
        task = self._sign_config_repo.get_config(task_name, account_name)
        if not task:
            return None
        config = {
            "_version": 3,
            "account_name": task.get("account_name", ""),
            "sign_at": task.get("sign_at", ""),
            "random_seconds": task.get("random_seconds", 0),
            "sign_interval": task.get("sign_interval", 1),
            "retry_count": task.get("retry_count", 0),
            "chats": task.get("chats", []),
            "execution_mode": task.get("execution_mode", "fixed"),
            "range_start": task.get("range_start", ""),
            "range_end": task.get("range_end", ""),
        }
        if task.get("last_run"):
            config["last_run"] = task["last_run"]
        return config

    def save_sign_config(self, task_name: str, config: Dict) -> bool:
        """保存签到任务配置"""
        account_name = config.get("account_name", "")
        if not account_name:
            return False
        try:
            self._sign_config_repo.save_config(task_name, account_name, config)
            return True
        except Exception:
            return False

    def delete_sign_config(
        self, task_name: str, account_name: Optional[str] = None
    ) -> bool:
        """删除签到任务配置"""
        return self._sign_config_repo.delete_config(task_name, account_name)

    def export_sign_task(
        self, task_name: str, account_name: Optional[str] = None
    ) -> Optional[str]:
        """
        导出签到任务配置为 JSON 字符串

        Args:
            task_name: 任务名称
            account_name: 账号名称（可选）

        Returns:
            JSON 字符串，如果任务不存在则返回 None
        """
        config = self.get_sign_config(task_name, account_name=account_name)

        if config is None:
            return None

        config = dict(config)
        config.pop("last_run", None)
        # Keep exported payload account-agnostic for cross-account imports.
        config.pop("account_name", None)

        # 添加元数据
        export_data = {
            "task_name": task_name,
            "task_type": "sign",
            "config": config,
        }

        return json.dumps(export_data, ensure_ascii=False, indent=2)

    def import_sign_task(
        self,
        json_str: str,
        task_name: Optional[str] = None,
        account_name: Optional[str] = None,
    ) -> bool:
        """
        导入签到任务配置

        Args:
            json_str: JSON 字符串
            task_name: 新任务名称（可选，如果不提供则使用原名称）
            account_name: 新账号名称（可选，如果不提供则使用原名称）

        Returns:
            是否成功导入
        """
        try:
            data = json.loads(json_str)

            # 验证数据格式
            if "config" not in data:
                return False

            # 确定任务名称
            final_task_name = task_name or data.get("task_name", "imported_task")

            config = data["config"]
            if account_name:
                config["account_name"] = account_name

            # 保存配置
            return self.save_sign_config(final_task_name, config)

        except (json.JSONDecodeError, KeyError):
            return False

    def export_all_configs(self) -> str:
        """
        导出所有配置
        Returns:
            包含所有配置的 JSON 字符串
        """
        all_configs = {
            "signs": {},
            "settings": {},
        }

        for task in self._sign_config_repo.list_configs():
            task_name = task.get("name")
            if not task_name:
                continue
            config = self.get_sign_config(task_name, task.get("account_name"))
            if not config:
                continue
            config.pop("last_run", None)
            account_name = config.get("account_name") or task.get("account_name")
            key = f"{task_name}@{account_name}" if account_name else task_name
            all_configs["signs"][key] = config

        all_configs["settings"] = {
            "global": self.get_global_settings(),
            "ai": self.get_ai_config(),
            "telegram": self.get_telegram_config(),
        }

        return json.dumps(all_configs, ensure_ascii=False, indent=2)

    def import_all_configs(
        self, json_str: str, overwrite: bool = False
    ) -> Dict[str, Any]:
        """
        导入所有配置
        """
        result = {
            "signs_imported": 0,
            "signs_skipped": 0,
            "settings_imported": 0,
            "errors": [],
        }

        try:
            data = json.loads(json_str)

            # 导入签到任务
            for key, config in data.get("signs", {}).items():
                task_name = config.get("name")
                account_name = config.get("account_name")

                if "@" in key:
                    parsed_task_name, parsed_account_name = key.split("@", 1)
                else:
                    parsed_task_name, parsed_account_name = key, None

                if not task_name:
                    task_name = parsed_task_name
                if not account_name and parsed_account_name:
                    account_name = parsed_account_name

                config = dict(config)
                if account_name:
                    config["account_name"] = account_name

                if not overwrite and self.has_sign_config(task_name, account_name):
                    result["signs_skipped"] += 1
                    continue

                if self.save_sign_config(task_name, config):
                    result["signs_imported"] += 1
                else:
                    result["errors"].append(f"Failed to import sign task: {task_name}")

            # 导入设置 (新增)
            settings_data = data.get("settings", {})

            # 导入全局设置
            if "global" in settings_data:
                try:
                    self.save_global_settings(settings_data["global"])
                    result["settings_imported"] += 1
                except Exception as e:
                    result["errors"].append(f"Failed to import global settings: {e}")

            # 导入 AI 配置
            if "ai" in settings_data and settings_data["ai"]:
                try:
                    ai_conf = settings_data["ai"]
                    # 注意：如果 masking 处理过 api_key (e.g. ****)，这里需要处理吗？
                    # 当前 export_ai_config 直接读取文件，应该包含完整 key（文件里是明文）。前端展示才 mask。
                    # 所以这里导出的是完整 key，可以直接导入。
                    if ai_conf.get("api_key"):
                        self.save_ai_config(ai_conf["api_key"], ai_conf.get("base_url"), ai_conf.get("model"))
                        result["settings_imported"] += 1
                except Exception as e:
                    result["errors"].append(f"Failed to import AI config: {e}")

            # 导入 Telegram 配置
            if "telegram" in settings_data:
                try:
                    tg_conf = settings_data["telegram"]
                    if tg_conf.get("is_custom") and tg_conf.get("api_id") and tg_conf.get("api_hash"):
                         self.save_telegram_config(str(tg_conf["api_id"]), tg_conf["api_hash"])
                         result["settings_imported"] += 1
                except Exception as e:
                    result["errors"].append(f"Failed to import Telegram config: {e}")

            # 关键修复：清除 SignTaskService 缓存，否则前端刷新也看不到新任务
            try:
                from backend.services.sign_tasks import get_sign_task_service
                get_sign_task_service()._tasks_cache = None

                # 可选：触发调度同步？
                # 如果导入了新任务，调度器并不知道。
                # 只有 _tasks_cache 清除后，下次调用 list_tasks 才会读文件，但调度器是内存常驻的。
                # 我们应该调用 sync_jobs!

                # 由于 sync_jobs 是 async 的，而这里是同步方法，可能不太好直接调。
                # 但 FastAPI 路由是 async 的，我们可以在路由层调用 sync_jobs。
                # 这里的职责主要是文件操作。清理 cache 是必须的。
                pass
            except Exception as e:
                 print(f"Failed to clear cache: {e}")

        except (json.JSONDecodeError, KeyError) as e:
            result["errors"].append(f"Invalid JSON format: {str(e)}")

        return result

    # ============ AI 配置 ============

    def get_ai_config(self) -> Optional[Dict]:
        """获取 AI 配置"""
        return self._load_app_setting("ai_config")

    def save_ai_config(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> bool:
        """
        保存 AI 配置

        Args:
            api_key: OpenAI API Key
            base_url: API Base URL（可选）
            model: 模型名称（可选）

        Returns:
            是否成功保存
        """
        existing = self.get_ai_config() or {}
        normalized_api_key = (api_key or "").strip()
        final_api_key = normalized_api_key or existing.get("api_key", "")
        if not final_api_key:
            raise ValueError("API Key 不能为空")

        config = {"api_key": final_api_key}
        config["base_url"] = base_url if base_url else None
        config["model"] = model if model else None

        return self._save_app_setting("ai_config", config)

    def delete_ai_config(self) -> bool:
        """
        删除 AI 配置

        Returns:
            是否成功删除
        """
        return self._delete_app_setting("ai_config")

    async def test_ai_connection(self) -> Dict:
        """
        测试 AI 连接

        Returns:
            测试结果
        """
        config = self.get_ai_config()

        if not config:
            return {"success": False, "message": "未配置 AI API Key"}

        api_key = config.get("api_key")
        base_url = config.get("base_url")
        model = config.get("model", "gpt-4o")

        if not api_key:
            return {"success": False, "message": "API Key 为空"}

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key, base_url=base_url)

            # 发送一个简单的测试请求
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Say 'test ok' in 2 words"}],
                max_tokens=10,
            )

            return {
                "success": True,
                "message": f"连接成功！模型响应: {response.choices[0].message.content}",
                "model_used": model,
            }

        except ImportError:
            return {
                "success": False,
                "message": "未安装 openai 库，请运行: pip install openai",
            }
        except Exception as e:
            return {"success": False, "message": f"连接失败: {str(e)}"}

    # ============ 全局设置 ============

    def get_global_settings(self) -> Dict:
        """获取全局设置"""
        default_settings = {
            "sign_interval": None,
            "log_retention_days": 7,
            "data_dir": None,
        }

        settings_data = self._load_app_setting("global_settings") or {}
        merged = dict(default_settings)
        if isinstance(settings_data, dict):
            merged.update(settings_data)
        return merged

    def save_global_settings(self, settings: Dict) -> bool:
        """
        保存全局设置

        Args:
            settings: 设置字典

        Returns:
            是否成功保存
        """
        merged = dict(self.get_global_settings())
        merged.update(settings)

        data_dir_value = merged.get("data_dir")
        if isinstance(data_dir_value, str):
            data_dir_value = data_dir_value.strip()
        if data_dir_value:
            resolved = Path(str(data_dir_value)).expanduser()
            resolved.mkdir(parents=True, exist_ok=True)
            if not is_writable_dir(resolved):
                raise ValueError(f"数据路径不可写: {resolved}")
            merged["data_dir"] = str(resolved)
        elif data_dir_value is None or data_dir_value == "":
            merged["data_dir"] = None

        return self._save_app_setting("global_settings", merged)

    # ============ Telegram API 配置 ============

    # 默认的 Telegram API 凭证
    DEFAULT_TG_API_ID = "611335"
    DEFAULT_TG_API_HASH = "d524b414d21f4d37f08684c1df41ac9c"

    def get_telegram_config(self) -> Dict:
        """
        获取 Telegram API 配置

        Returns:
            配置字典，包含 api_id, api_hash, is_custom (是否为自定义配置)
        """
        default_config = {
            "api_id": self.DEFAULT_TG_API_ID,
            "api_hash": self.DEFAULT_TG_API_HASH,
            "is_custom": False,
        }

        config = self._load_app_setting("telegram_config")
        if config and config.get("api_id") and config.get("api_hash"):
            return {
                "api_id": str(config.get("api_id")),
                "api_hash": str(config.get("api_hash")),
                "is_custom": True,
            }
        return default_config

    def save_telegram_config(self, api_id: str, api_hash: str) -> bool:
        """
        保存 Telegram API 配置

        Args:
            api_id: Telegram API ID
            api_hash: Telegram API Hash

        Returns:
            是否成功保存
        """
        config = {
            "api_id": str(api_id),
            "api_hash": str(api_hash),
        }

        return self._save_app_setting("telegram_config", config)

    def reset_telegram_config(self) -> bool:
        """
        重置 Telegram API 配置（恢复默认）

        Returns:
            是否成功重置
        """
        return self._delete_app_setting("telegram_config")


# 创建全局实例
_config_service: Optional[ConfigService] = None


def get_config_service() -> ConfigService:
    global _config_service
    if _config_service is None:
        _config_service = ConfigService()
    return _config_service
