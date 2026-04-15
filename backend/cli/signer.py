from __future__ import annotations

import subprocess
from typing import Optional

from backend.core.config import get_settings

settings = get_settings()


def _base_args() -> list[str]:
    return [
        "tg-signer",
        "--workdir",
        str(settings.resolve_workdir()),
        "--session_dir",
        str(settings.resolve_session_dir()),
    ]


def login_account(
    account_name: str,
    code: Optional[str] = None,
    password: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """
    Trigger tg-signer login flow.
    When code/password provided, pipe them via stdin (best-effort).
    """
    from backend.core.validators import validate_account_name

    # 验证账号名，防止命令注入
    account_name = validate_account_name(account_name)

    args = _base_args() + ["login", account_name]
    input_parts = []
    if code:
        input_parts.append(code)
    if password:
        input_parts.append(password)
    input_data = ("\n".join(input_parts) + "\n") if input_parts else None
    return subprocess.run(
        args,
        input=input_data.encode() if input_data else None,
        capture_output=True,
        text=True,
    )
