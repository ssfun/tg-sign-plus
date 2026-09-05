# TG-Sign-Plus

<div align="center">

**Telegram 多账号自动签到与任务管理平台**

[![License](https://img.shields.io/badge/license-BSD--3--Clause-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109.2+-009688.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16.2+-black.svg)](https://nextjs.org/)

[快速部署](#快速部署) · [本地开发](#本地开发) · [Web-使用流程](#web-使用流程) · [CLI](#cli) · [配置说明](#配置说明) · [签到任务](#签到任务)

</div>

TG-Sign-Plus 由 FastAPI 后端、Next.js 管理端和 `tg-signer` 自动化核心组成。Web 管理端负责账号、签到任务、执行历史和系统配置；CLI 还提供交互式任务配置、消息监控、诊断和单次执行能力。

## 实际功能边界

| 能力 | Web 管理端 | CLI |
| --- | --- | --- |
| Telegram 账号登录 | 手机验证码、二维码、Telegram 2FA、账号代理 | 手机验证码登录、全局代理 |
| 签到任务 | 创建、编辑、启停、立即执行、复制、导入导出 | 交互式配置、执行、列出 |
| 调度 | 固定时间/Cron、每日时间范围内随机执行 | `run`/`run-once` 只执行一次，不启动后端调度器 |
| 执行记录 | 实时流程、历史记录、结构化诊断、账号日志 | `diagnose-run`、`canary-report` |
| AI 能力 | 配置 OpenAI 兼容接口，用于图片选项、OCR、计算题和诗词题 | 环境变量或 `llm-config` |
| 消息监控 | 当前没有对应页面 | 文本匹配、自动回复、转发、Server酱、UDP/HTTP 回调 |
| 管理端安全 | JWT access token、refresh cookie、CSRF、可选 TOTP | 不适用 |

> 消息监控和外部转发目前属于 CLI/核心库能力，不会随 Web 后端自动启动。
> CLI 交互式任务保存在 `--workdir` 的文件目录中，Web 任务保存在数据库中；两者不会自动同步。

## 项目预览

### 登录界面

![登录界面](assets/login.jpeg)

### 账号工作台

![控制台](assets/dashboard.jpeg)

### 任务管理

![任务管理](assets/tasks.jpeg)

## 快速部署

Docker 镜像会同时构建 Next.js 静态页面并由 FastAPI 托管，部署后只需开放一个端口。

### Docker Compose

```yaml
services:
  tg-sign-plus:
    image: sfun/tg-sign-plus:latest
    container_name: tg-sign-plus
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
    environment:
      TZ: Asia/Shanghai
      APP_SECRET_KEY: "请替换为 openssl rand -hex 32 的输出"
      ADMIN_PASSWORD: "请设置首次启动使用的强密码"
      # 可选：环境变量会覆盖管理端保存的 Telegram API 凭证
      # TG_API_ID: "12345678"
      # TG_API_HASH: "your-api-hash"
      # 仅在 HTTPS 反向代理后启用
      # APP_REFRESH_COOKIE_SECURE: "true"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz').read()"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 60s
```

```bash
docker compose up -d
```

访问 `http://localhost:8080`。首次启动只会在用户表为空时创建 Web 管理员：

- 登录页“用户名”填写 `admin`。
- 设置了 `ADMIN_PASSWORD` 时，使用该密码。
- 未设置时会生成随机密码，宿主机可在 `./data/initial_admin_password.txt` 查看。

这里的用户名是 TG-Sign-Plus 管理端用户名，不是 Telegram 手机号、Telegram `@username`，也不是添加 Telegram 账号时填写的“账号名称”。项目没有 `ADMIN_USERNAME` 环境变量；首次创建的管理端用户名固定为 `admin`。

`ADMIN_PASSWORD` 只影响首次建库，不会覆盖已经存在的管理员密码或用户名。如果已在“设置”中修改用户名，或复用了已有的 `./data` 目录，登录时应填写数据库中现有的用户名，不能再使用 `admin`。

### Docker 命令

```bash
docker run -d \
  --name tg-sign-plus \
  -p 8080:8080 \
  -v "$(pwd)/data:/data" \
  -e TZ=Asia/Shanghai \
  -e APP_SECRET_KEY="$(openssl rand -hex 32)" \
  -e ADMIN_PASSWORD="replace-with-a-strong-password" \
  --restart unless-stopped \
  sfun/tg-sign-plus:latest
```

### 自行构建

```bash
git clone https://github.com/ssfun/tg-sign-plus.git
cd tg-sign-plus
docker build -t tg-sign-plus:local .
docker run -d --name tg-sign-plus -p 8080:8080 -v "$(pwd)/data:/data" tg-sign-plus:local
```

默认镜像包含 Komari，构建阶段会拉取 `ghcr.io/komari-monitor/komari-agent:latest`。只有同时设置 `KOMARI_SERVER` 和 `KOMARI_SECRET` 时，容器入口才会启动该 agent。

## 本地开发

### 环境要求

- Python 3.10+
- Node.js 20+
- npm

### 后端

```bash
git clone https://github.com/ssfun/tg-sign-plus.git
cd tg-sign-plus
pip install -e .

export APP_DATA_DIR="$(pwd)/data"
export APP_SECRET_KEY="$(openssl rand -hex 32)"
export ADMIN_PASSWORD="replace-with-a-strong-password"

uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

本地设置 `APP_DATA_DIR` 很重要，否则默认会尝试 `/data`，不可写时再退回系统临时目录，数据不一定持久化。

### 前端

另开终端：

```bash
cd frontend
npm ci
npm run dev
```

访问 `http://localhost:3000`。开发模式下 Next.js 默认把 `/api/*` 转发到 `http://127.0.0.1:8000`；如果后端使用其他地址，请在启动前设置 `API_PROXY_TARGET`。

```bash
API_PROXY_TARGET=http://127.0.0.1:8080 npm run dev
```

生产构建使用静态导出：

```bash
cd frontend
npm ci
npm run build
```

输出目录为 `frontend/out`。仓库中的 Dockerfile 会把它复制到镜像的 `/web`，无需运行 `next start`。

## Web 使用流程

### 用户名与账号名称

| 页面字段 | 实际含义 | 示例 |
| --- | --- | --- |
| 登录页“用户名” | TG-Sign-Plus Web 管理端用户名；首次启动为 `admin` | `admin` |
| 添加 Telegram 账号时的“账号名称” | 当前面板内用于区分 session、任务和日志的本地名称；由用户自定义，仅允许字母、数字、下划线和连字符，长度 1-64 | `Work_Account_01` |
| Telegram 手机号 | 向 Telegram 请求登录验证码时使用的真实账号标识 | `+8613800138000` |
| Telegram `@username` | Telegram 公开用户名，不用于 TG-Sign-Plus 管理端登录，也不代替手机号 | `@example` |

管理端用户名可在“设置”中修改，长度为 3-50 个字符，修改时需要确认当前密码。修改成功后，后续登录必须使用新用户名；重启容器或重新设置 `ADMIN_PASSWORD` 不会把它恢复为 `admin`。

### 基本操作

1. 使用管理员账号登录，在“设置”中修改用户名/密码，并按需启用管理端 TOTP。
2. 在“设置”中配置 Telegram API 凭证和 OpenAI 兼容接口。项目内置 Telegram API 凭证可直接试用，但长期部署建议换成自己的 `api_id`/`api_hash`。
3. 在账号页通过手机号或二维码登录 Telegram。若 Telegram 账号启用了两步验证，还需输入该账号的 2FA 密码。
4. 每个账号可单独设置代理、备注和聊天缓存有效期。代理格式由后端解析，例如 `socks5://user:pass@host:port`。
5. 进入账号工作台创建任务，选择目标会话、调度模式和动作序列。
6. 任务可以立即执行，也可以交给后端 APScheduler 定时执行；任务历史会保存流程、结果摘要和诊断信息。
7. 单个任务可复制/导入导出；“设置”页可导入导出全部任务和设置。

任务编辑器支持切换编辑多会话任务，保存时保留全部会话。超时、历史扫描和 AI 兜底参数位于“高级设置”，通常无需修改。执行状态暂时无法读取时，页面会保留监控并自动重试。

健康检查端点：

- `/health`、`/healthz`：进程存活即返回 200。
- `/readyz`：数据库初始化和调度同步完成后返回 200，否则返回 503。

## CLI

安装项目后会注册 `tg-signer` 命令。全局选项必须放在子命令前。

```bash
# 帮助
tg-signer --help

# 登录账号；也兼容 tg-signer login my_account
tg-signer --account my_account login

# 交互式创建/修改签到任务
tg-signer --account my_account config my_task

# run 与 run-once 当前等价，均只执行一次
tg-signer --account my_account run my_task
tg-signer --account my_account run-once my_task

# 任务列表和消息发送
tg-signer --account my_account list
tg-signer --account my_account send --chat-id 123456 --text "Hello"
tg-signer --account my_account send-dice --chat-id 123456 --emoji "🎲"

# AI 配置保存在 --workdir 指向的目录
tg-signer --workdir . llm-config

# 消息监控必须保持进程运行
tg-signer --account my_account monitor-config my_monitor
tg-signer --account my_account monitor my_monitor
```

CLI 默认把配置、日志和 session 放在当前目录。可以显式指定：

```bash
tg-signer \
  --workdir /data/.signer \
  --session-dir /data/sessions \
  --account my_account \
  run my_task
```

`diagnose-run` 和 `canary-report` 读取 Web 后端数据库时，需要通过 `--data-dir` 或 `--database-url` 指向同一数据源：

```bash
tg-signer --data-dir /data --account my_account diagnose-run my_task
tg-signer --data-dir /data --account my_account canary-report
tg-signer --data-dir /data --account my_account canary-report --json-output
tg-signer --data-dir /data --account my_account canary-report --max-age-hours 36 --strict
```

`--strict` 会在整体状态不是 `pass` 时返回非零退出码。默认只接受最近 36 小时内的最新运行证据。

## 配置说明

### 服务与安全

| 环境变量 | 实际行为 | 默认值 |
| --- | --- | --- |
| `APP_SECRET_KEY` | JWT 和 CSRF 签名密钥；未设置时尝试在数据目录生成 `.secret_key` | 自动生成并持久化 |
| `ADMIN_PASSWORD` | 仅用于空用户表首次创建 `admin` | 生成随机密码并写入 `initial_admin_password.txt` |
| `APP_DATA_DIR` | SQLite、session、日志和持久化密钥的根目录 | `/data`，不可写时退回临时目录 |
| `APP_DATABASE_URL` | SQLAlchemy 数据库 URL | 数据目录中的 `db.sqlite` |
| `DATABASE_URL` | `APP_DATABASE_URL` 未设置时使用的兼容别名 | 未设置 |
| `TZ` | 调度器时区 | 后端默认 `Asia/Hong_Kong`，Docker 默认 `Asia/Shanghai` |
| `PORT` | Docker 入口启动 Uvicorn 的端口 | `8080` |
| `APP_REFRESH_COOKIE_SECURE` | HTTPS 部署设为 `true`；HTTP/IP 直连必须为 `false` | `false` |
| `APP_CORS_ALLOW_ORIGIN_REGEX` | 跨域来源正则 | 仅 localhost/127.0.0.1 |
| `APP_ALLOW_PASSWORD_TOTP_RESET` | 是否开放通过密码重置管理端 TOTP | `false` |

SQLite 默认启用 WAL。也可使用 PostgreSQL，例如：

```bash
APP_DATABASE_URL=postgresql://user:password@db:5432/tg_sign_plus
```

如果通过 HTTPS 反向代理访问，设置 `APP_REFRESH_COOKIE_SECURE=true`；通过 `http://服务器IP:8080` 访问时不要开启，否则浏览器不会携带安全 cookie，后续写请求会因 CSRF 校验返回 403。

### Telegram 与 AI

| 环境变量 | 说明 |
| --- | --- |
| `TG_API_ID` / `TG_API_HASH` | 覆盖管理端保存或项目内置的 Telegram API 凭证 |
| `OPENAI_API_KEY` | CLI 使用的 OpenAI 或兼容服务 API Key |
| `OPENAI_BASE_URL` | CLI 使用的可选兼容接口地址 |
| `OPENAI_MODEL` | CLI 使用的模型名称 |
| `SERVER_CHAN_SEND_KEY` | CLI 消息监控的 Server酱 SendKey |

Web 后端的 Telegram、AI 和全局设置保存在数据库中。`TG_API_ID`/`TG_API_HASH` 可以覆盖 Web 保存的 Telegram 凭证，但 Web 签到运行时的 AI 配置只读取管理端保存值。CLI 则优先读取上述 OpenAI 环境变量，也可读取 `--workdir` 下的 `.env` 和交互式配置文件。

### 并发与超时

以下变量用于资源受限环境或网络排障。除非出现明确问题，建议保留默认值。

| 环境变量 | 默认值 | 作用 |
| --- | ---: | --- |
| `TG_GLOBAL_CONCURRENCY` | `1` | 全局 Telegram 会话并发数 |
| `TG_CHANNEL_DIFF_CONCURRENCY` | `2` | channel difference 并发数 |
| `TG_RPC_RETRIES` | `2` | Telegram RPC 重试次数 |
| `TG_RPC_TIMEOUT` | `30` | Telegram RPC 超时秒数 |
| `TG_CONNECT_TIMEOUT` | `20` | 连接/认证阶段超时秒数 |
| `TG_CONNECT_RETRIES` | `3` | 连接/认证阶段尝试次数 |
| `TG_CONNECT_RETRY_WAIT` | `3` | 连接重试等待秒数 |
| `TG_TCP_TIMEOUT` | `8` | 底层 TCP 超时秒数 |
| `TG_SLEEP_THRESHOLD` | `120` | FloodWait 自动等待阈值秒数 |
| `TG_WORKERS` | `16` | Telegram updates handler worker 数量 |
| `TG_SEND_MESSAGE_TIMEOUT` | `20` | 发送消息超时秒数 |
| `TG_AI_REQUEST_TIMEOUT` | `45` | AI 请求超时秒数 |
| `SIGN_TASK_RUN_TIMEOUT` | `180` | 单次任务基础总超时秒数；事件任务会按配置扩展 |
| `SIGN_TASK_ACCOUNT_LOCK_TIMEOUT` | `300` | 等待同账号执行锁的最长秒数 |
| `SIGN_TASK_GLOBAL_CONCURRENCY_TIMEOUT` | `300` | 等待全局并发槽的最长秒数 |
| `TG_SIGN_TASK_DISABLE_UPDATES` | `false` | 强制关闭签到 updates，仅用于低内存排障；按钮/回复类任务可能失败 |

## 签到任务

### 当前配置格式

当前写入格式固定为 `_version: 3` 和 `engine: event`。旧版配置会在读取/导入时归一化到事件引擎。

下面是可导入的单任务 JSON。`account_name` 会在导入时由目标账号补入，因此导出文件可以跨账号使用。

```json
{
  "task_name": "daily_checkin",
  "task_type": "sign",
  "config": {
    "_version": 3,
    "engine": "event",
    "sign_at": "0 6 * * *",
    "random_seconds": 0,
    "sign_interval": 1,
    "retry_count": 2,
    "execution_mode": "fixed",
    "chats": [
      {
        "chat_id": 123456789,
        "name": "sample_bot",
        "event_timeout": 120,
        "actions": [
          { "action": 1, "text": "/start" },
          { "action": 3, "text": "签到" },
          { "action": 9, "keywords": ["签到成功", "今日已签到"] }
        ]
      }
    ]
  }
}
```

### 调度模式

- `execution_mode: fixed`：使用 `sign_at`。支持 5 位 Cron、6 位 Cron，以及 `HH:MM`/`HH:MM:SS`。
- `execution_mode: range`：使用 `range_start` 和 `range_end`，每天在时间窗口内预先随机一个执行时间；计划时间会持久化并在服务重启后恢复。此模式下 `sign_at` 仅作为每日触发基准。
- `random_seconds`：每次实际执行前附加的随机延迟；立即执行、固定调度和范围调度都会生效。
- `sign_interval`：同一任务多个 chat 连续执行时的间隔秒数。
- `retry_count`：任务失败后的外层重试次数。

### 动作类型

| 代码 | 行为 | 主要参数 |
| ---: | --- | --- |
| `1` | 发送文本 | `text` |
| `2` | 发送骰子类 emoji | `dice` |
| `3` | 按文本点击回调按钮 | `text` |
| `4` | AI 识别图片选项并点击 | 无 |
| `5` | AI 解答文本计算题并回复 | 无 |
| `6` | AI OCR/验证码识别并回复 | `caption_pattern`、`captcha_lengths`、`captcha_charset`、`captcha_case`、`reply_to_message` |
| `7` | AI 计算并点击对应按钮 | 无 |
| `8` | AI 完成诗词题并点击按钮 | 无 |
| `9` | 按消息文本判断成功 | `keywords`，命中任一项即成功 |

事件引擎收到机器人消息后按配置响应。只有动作序列包含 `action: 9` 时才会等待最终成功关键词；纯发送、投骰子或点击任务可以省略该动作，完成已配置动作后即视为成功。

### Chat 级事件参数

每个 `chats[]` 项可覆盖事件引擎默认值：

| 字段 | 对应环境变量 | 默认值 |
| --- | --- | ---: |
| `event_timeout` | `TG_EVENT_ENGINE_TIMEOUT` | `120` |
| `event_retries` | `TG_EVENT_ENGINE_INLINE_RETRIES` | `3` |
| `event_retry_wait` | `TG_EVENT_ENGINE_RETRY_WAIT` | `2` |
| `event_history_limit` | `TG_EVENT_ENGINE_HISTORY_LIMIT` | `3` |
| `event_history_failure_threshold` | `TG_EVENT_ENGINE_HISTORY_FAILURE_THRESHOLD` | `2` |
| `event_history_rescue_interval` | `TG_EVENT_ENGINE_HISTORY_RESCUE_INTERVAL` | `5` |
| `event_history_rpc_timeout` | `TG_EVENT_ENGINE_HISTORY_RPC_TIMEOUT` | `8` |
| `event_history_result_max_age` | `TG_EVENT_ENGINE_HISTORY_RESULT_MAX_AGE` | `600` |
| `event_action_timeout` | `TG_EVENT_ENGINE_ACTION_TIMEOUT` | `45` |
| `event_send_timeout` | `TG_EVENT_ENGINE_SEND_TIMEOUT` | 跟随 action timeout |
| `event_media_timeout` | `TG_EVENT_ENGINE_MEDIA_TIMEOUT` | `15` |
| `event_ai_timeout` | `TG_EVENT_ENGINE_AI_TIMEOUT` | `30` |
| `event_callback_timeout` | `TG_CALLBACK_TIMEOUT` | `10` |
| `event_callback_retries` | `TG_CALLBACK_RETRIES` | `3` |
| `event_ai_fallback` | `TG_EVENT_ENGINE_AI_FALLBACK` | `false` |

历史补漏默认扫描最近 3 条消息，用于救回漏掉的结果、验证码和消息编辑。设 `event_history_limit: 0` 可对单个 chat 关闭。`event_ai_fallback` 会让未被动作序列覆盖的后续交互尝试 AI 处理，默认关闭，建议只按 chat 开启。

## 技术架构

```text
tg-sign-plus/
├── backend/              FastAPI、认证、API、调度器、SQLAlchemy 数据层
├── frontend/             Next.js App Router 静态管理端
├── tg_signer/            Telegram 自动化、事件引擎、CLI、消息监控
├── tg_signer_contracts/  跨层错误契约
├── docker/               容器入口
├── Dockerfile            Node 构建阶段 + Python 运行阶段
└── pyproject.toml        Python 包与 tg-signer 命令入口
```

- Telegram 客户端：Kurigram（Pyrogram fork）
- 数据库：SQLAlchemy，支持 SQLite 和 PostgreSQL
- 调度：APScheduler
- 管理端认证：JWT、refresh token、CSRF、TOTP
- 前端：Next.js 16、React 18、TypeScript、Tailwind CSS

## 开发验证

```bash
# Python 静态检查
ruff check .

# Python 测试（仅维护者本地存在 tests/ 时可用，该目录不纳入 Git 跟踪）
pytest

# 前端生产构建
cd frontend
npm ci
npm run build
```

## 许可证与致谢

本项目采用 [BSD-3-Clause License](LICENSE)。

- [tg-signer](https://github.com/amchii/tg-signer) by [amchii](https://github.com/amchii)
- [TG-SignPulse](https://github.com/akasls/TG-SignPulse) by [akasls](https://github.com/akasls)
- [Kurigram](https://github.com/KurimuzonAkuma/kurigram)
- [FastAPI](https://fastapi.tiangolo.com/)
- [Next.js](https://nextjs.org/)

## 自动校验

PR、push 和镜像发布前会运行 Python 3.10/3.12 后端回归测试，以及前端 ESLint、TypeScript、Vitest 和生产构建。`tests/` 已纳入版本控制。

```bash
pip install -e . pytest pytest-asyncio ruff
python -m pytest -q
ruff check --select E9,F821,F822,F823 backend tg_signer tg_signer_contracts tests
cd frontend
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

密钥文件无法读取、生成或保存时，后端会拒绝启动；请修复数据目录权限或配置 `APP_SECRET_KEY`。旧版公开默认密钥和空密钥不再接受。
