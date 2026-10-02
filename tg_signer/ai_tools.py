import base64
import asyncio
import json
import os
import pathlib
import re
from typing import TYPE_CHECKING, Union

import json_repair
from typing_extensions import Optional, Required, TypedDict

if TYPE_CHECKING:
    from openai import AsyncOpenAI  # 在性能弱的机器上导入openai包实在有些慢

from tg_signer.utils import UserInput, print_to_user

DEFAULT_MODEL = "gpt-4o"


def _coerce_option_index(option) -> int | None:
    if option is None or isinstance(option, bool):
        return None
    try:
        return int(str(option).strip())
    except (TypeError, ValueError):
        return None


def _option_index_from_ai_response(value, options: list[tuple[int, str]] | None = None) -> int | None:
    if isinstance(value, dict):
        for key in ("option", "index", "answer", "value", "text"):
            option_index = _coerce_option_index(value.get(key))
            if option_index is not None:
                return option_index
        option_text = next(
            (
                str(value.get(key) or "").strip()
                for key in ("answer", "value", "text", "option")
                if str(value.get(key) or "").strip()
            ),
            "",
        )
    else:
        option_index = _coerce_option_index(value)
        if option_index is not None:
            return option_index
        option_text = str(value or "").strip()
    if option_text and options:
        for index, text in options:
            if option_text == text:
                return index
    return None


def _read_float_env(name: str, default: float, minimum: float = 1.0) -> float:
    try:
        return max(float(os.environ.get(name, default)), minimum)
    except (TypeError, ValueError):
        return default


def encode_image(image: bytes):
    return base64.b64encode(image).decode("utf-8")


class OpenAIConfig(TypedDict, total=False):
    api_key: Required[str]
    base_url: Optional[str]
    model: Optional[str]


class OpenAIConfigManager:
    def __init__(self, workdir: Union[str, pathlib.Path]):
        self.workdir = pathlib.Path(workdir)

    def get_config_file(self) -> pathlib.Path:
        return self.workdir / ".openai_config.json"

    def has_env_config(self):
        return bool(os.environ.get("OPENAI_API_KEY"))

    def has_config(self) -> bool:
        return self.has_env_config() and bool(self.load_file_config())

    def load_file_config(self) -> Optional[dict]:
        config_file = self.get_config_file()
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as fp:
                c = json.load(fp)
            # 简单验证必需字段
            if "api_key" in c:
                return c
        return None

    def save_config(self, api_key: str, base_url: str = None, model: str = None):
        config_file = self.get_config_file()
        config = OpenAIConfig(api_key=api_key, base_url=base_url, model=model)
        with open(config_file, "w", encoding="utf-8") as fp:
            json.dump(config, fp, ensure_ascii=False, indent=2)

    def load_config(self) -> Optional[OpenAIConfig]:
        # 环境变量优先
        if self.has_env_config():
            return OpenAIConfig(
                api_key=os.environ["OPENAI_API_KEY"],
                base_url=os.environ.get("OPENAI_BASE_URL"),
                model=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
            )
        return self.load_file_config()

    def ask_for_config(self):
        print_to_user("开始配置OpenAI API并保存至本地。")
        input_ = UserInput()
        api_key = input_("请输入 OPENAI_API_KEY: ").strip()
        while not api_key:
            print_to_user("API Key不能为空！")
            api_key = input_("请输入 OPENAI_API_KEY: ").strip()

        base_url = (
            input_(
                "请输入 OPENAI_BASE_URL (可选，直接回车使用默认OpenAI地址): "
            ).strip()
            or None
        )
        model = (
            input_(
                f"请输入 OPENAI_MODEL (可选，直接回车使用默认模型({DEFAULT_MODEL})): "
            ).strip()
            or None
        )
        self.save_config(api_key, base_url=base_url, model=model)
        print_to_user("OpenAI配置已保存。")
        return self.load_config()


def get_openai_client(
    api_key: str = None,
    base_url: str = None,
    **kwargs,
) -> Optional["AsyncOpenAI"]:
    from openai import AsyncOpenAI, OpenAIError

    try:
        return AsyncOpenAI(api_key=api_key, base_url=base_url, **kwargs)
    except OpenAIError:
        return None


class AITools:
    def __init__(self, cfg: OpenAIConfig):
        self.client = get_openai_client(
            api_key=cfg["api_key"], base_url=cfg.get("base_url")
        )
        self.default_model = cfg.get("model") or DEFAULT_MODEL
        self.request_timeout = _read_float_env("TG_AI_REQUEST_TIMEOUT", 45.0, minimum=1.0)

    async def close(self):
        if self.client is not None:
            await self.client.close()

    async def _completion(self, client: "AsyncOpenAI", **kwargs):
        return await asyncio.wait_for(
            client.chat.completions.create(**kwargs),
            timeout=self.request_timeout,
        )

    async def choose_option_by_image(
        self,
        image: bytes,
        query: str,
        options: list[tuple[int, str]],
        client: "AsyncOpenAI" = None,
        model: str = None,
        temperature=0.1,
    ) -> int | None:
        sys_prompt = """你是一个**图片识别助手**，可以根据提供的图片和问题选择出**唯一正确**的选项，如果你觉得每个都不对，也要给出一个你认为最符合的答案，以如下JSON格式输出你的回复：
    {
      "option": 1,  // 整数，表示选项序号，从1开始，与输入选项编号保持一致。
      "reason": "这么选择的原因，30字以内"
    }
    option字段必须返回你选择的选项编号。
    """
        client = client or self.client
        model = model or self.default_model
        text_query = f"问题为：{query}, 选项为：{json.dumps(options)}。"
        messages = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text_query},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{encode_image(image)}"
                        },
                    },
                ],
            },
        ]
        # noinspection PyTypeChecker
        completion = await self._completion(
            client,
            messages=messages,
            model=model,
            response_format={"type": "json_object"},
            stream=False,
            temperature=temperature,
        )
        message = completion.choices[0].message
        content = message.content or ""
        try:
            result = json_repair.loads(content or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            result = content
        return _option_index_from_ai_response(result, options)

    async def extract_text_by_image(
        self,
        image: bytes,
        query: str = "",
        client: "AsyncOpenAI" = None,
        model: str = None,
        temperature=0.1,
    ) -> str:
        sys_prompt = (
            "You are an OCR assistant. Extract the most relevant text from the image. "
            "Return plain text only, no markdown, no explanation. "
            "If the image contains a short code, captcha, verification code, or alphanumeric token, "
            "output the characters continuously without spaces, line breaks, or separators."
        )
        client = client or self.client
        model = model or self.default_model
        text_query = query or "Extract the key text from this image."
        messages = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text_query},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{encode_image(image)}"
                        },
                    },
                ],
            },
        ]
        completion = await self._completion(
            client,
            messages=messages,
            model=model,
            stream=False,
            temperature=temperature,
        )
        return (completion.choices[0].message.content or "").strip()

    async def calculate_problem(
        self,
        query: str,
        client: "AsyncOpenAI" = None,
        model: str = None,
        temperature=0.1,
    ) -> str:
        sys_prompt = """你是一个**答题助手**，可以根据用户的问题给出正确的回答，只需要回复答案，不要解释，不要输出任何其他内容。"""
        model = model or self.default_model
        client = client or self.client
        text = f"问题是: {query}\n\n只需要给出答案，不要解释，不要输出任何其他内容。The answer is:"
        # noinspection PyTypeChecker
        completion = await self._completion(
            client,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": text},
            ],
            model=model,
            stream=False,
            temperature=temperature,
        )
        return completion.choices[0].message.content.strip()

    async def solve_poetry_fill(
        self,
        query: str,
        options: list[str],
        client: "AsyncOpenAI" = None,
        model: str = None,
        temperature=0.1,
    ) -> str:
        sys_prompt = (
            "你是一个古诗词填空助手。根据题干中的缺字诗句和候选按钮，"
            "只返回最应该点击的那一个候选文字，不要解释，不要输出其他内容。"
        )
        model = model or self.default_model
        client = client or self.client
        text = (
            f"题目如下：\n{query}\n\n"
            f"可选按钮：{json.dumps(options, ensure_ascii=False)}\n\n"
            "只回复一个候选文字。"
        )
        completion = await self._completion(
            client,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": text},
            ],
            model=model,
            stream=False,
            temperature=temperature,
        )
        return (completion.choices[0].message.content or "").strip()

    async def get_reply(
        self,
        prompt: str,
        query: str,
        client: "AsyncOpenAI" = None,
        model: str = None,
    ) -> str:
        model = model or self.default_model
        client = client or self.client
        messages = [
            {
                "role": "system",
                "content": prompt,
            },
            {"role": "user", "content": f"{query}"},
        ]
        # noinspection PyTypeChecker
        completion = await self._completion(
            client,
            messages=messages,
            model=model,
            stream=False,
        )
        message = completion.choices[0].message
        return message.content

    async def infer_sign_interaction(
        self,
        text: str,
        buttons: list[str],
        client: "AsyncOpenAI" = None,
        model: str = None,
    ) -> dict:
        prompt = (
            "你是 Telegram 签到流程助手。根据机器人消息判断下一步动作。\n"
            "只允许输出 JSON，不要解释。\n"
            "可选动作：\n"
            "- click: 需要点击候选按钮之一\n"
            "- send: 需要发送一段简短文本\n"
            "- status: 这是签到状态或结果，无需操作\n"
            "- noop: 无需操作或不确定\n"
            "JSON 格式：{\"action\":\"click|send|status|noop\",\"value\":\"...\"}。\n"
            "如果 action=click，value 必须等于候选按钮中的一个。"
        )
        query = json.dumps(
            {"message": text or "", "buttons": buttons or []},
            ensure_ascii=False,
        )
        answer = await self.get_reply(prompt, query, client=client, model=model)
        data = json_repair.loads(answer or "{}")
        action = str(data.get("action") or "noop").strip().lower()
        value = str(data.get("value") or "").strip()
        if action not in {"click", "send", "status", "noop"}:
            action = "noop"
        if action == "click" and value not in (buttons or []):
            value = _best_button_match(value, buttons or [])
            if not value:
                action = "noop"
        if action == "send":
            value = value[:128].strip()
            if not value:
                action = "noop"
        return {"action": action, "value": value}


def _best_button_match(value: str, buttons: list[str]) -> str:
    target = _compact(value)
    if not target:
        return ""
    for button in buttons:
        compact_button = _compact(button)
        if target == compact_button or target in compact_button or compact_button in target:
            return button
    return ""


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()
