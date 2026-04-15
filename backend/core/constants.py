"""常量定义

集中定义项目中使用的常量，避免魔法数字。
"""

from __future__ import annotations


# ============ 时间相关常量 ============

# Token 过期时间（分钟）
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 14

# 聊天缓存 TTL（分钟）
DEFAULT_CHAT_CACHE_TTL_MINUTES = 1440  # 24小时

# 数据库连接超时（秒）
DATABASE_TIMEOUT_SECONDS = 30

# 数据库连接池回收时间（秒）
DATABASE_POOL_RECYCLE_SECONDS = 1800  # 30分钟


# ============ 速率限制常量 ============

# 登录速率限制
LOGIN_RATE_LIMIT = "5/minute"

# Token 刷新速率限制
REFRESH_RATE_LIMIT = "10/minute"

# TOTP 重置速率限制
TOTP_RESET_RATE_LIMIT = "5/minute"


# ============ 密码相关常量 ============

# 密码最小长度
PASSWORD_MIN_LENGTH = 8

# 密码最大长度
PASSWORD_MAX_LENGTH = 128


# ============ 输入验证常量 ============

# 账号名最大长度
ACCOUNT_NAME_MAX_LENGTH = 64

# 任务名最大长度
TASK_NAME_MAX_LENGTH = 128

# 用户名最大长度
USERNAME_MAX_LENGTH = 64

# TOTP 验证码长度
TOTP_CODE_LENGTH = 6


# ============ 数据库连接池常量 ============

# PostgreSQL 连接池大小
POSTGRES_POOL_SIZE = 20

# PostgreSQL 连接池最大溢出
POSTGRES_MAX_OVERFLOW = 30

# PostgreSQL 连接池超时（秒）
POSTGRES_POOL_TIMEOUT = 30


# ============ 审计日志常量 ============

# 审计日志操作类型
AUDIT_ACTION_LOGIN = "login"
AUDIT_ACTION_LOGIN_FAILED = "login_failed"
AUDIT_ACTION_LOGOUT = "logout"
AUDIT_ACTION_PASSWORD_CHANGE = "password_change"
AUDIT_ACTION_ACCOUNT_CREATE = "account_create"
AUDIT_ACTION_ACCOUNT_DELETE = "account_delete"
AUDIT_ACTION_TASK_CREATE = "task_create"
AUDIT_ACTION_TASK_DELETE = "task_delete"

# 审计日志状态
AUDIT_STATUS_SUCCESS = "success"
AUDIT_STATUS_FAILURE = "failure"


# ============ HTTP 状态码常量 ============

# 成功
HTTP_200_OK = 200
HTTP_201_CREATED = 201
HTTP_204_NO_CONTENT = 204

# 客户端错误
HTTP_400_BAD_REQUEST = 400
HTTP_401_UNAUTHORIZED = 401
HTTP_403_FORBIDDEN = 403
HTTP_404_NOT_FOUND = 404
HTTP_409_CONFLICT = 409
HTTP_429_TOO_MANY_REQUESTS = 429

# 服务器错误
HTTP_500_INTERNAL_SERVER_ERROR = 500
HTTP_503_SERVICE_UNAVAILABLE = 503


# ============ 其他常量 ============

# JWT 算法
JWT_ALGORITHM = "HS256"

# Cookie 配置
REFRESH_COOKIE_NAME = "tg-signer-refresh"
REFRESH_COOKIE_PATH = "/api"
REFRESH_COOKIE_SAMESITE = "lax"

# 默认管理员用户名
DEFAULT_ADMIN_USERNAME = "admin"

# 默认管理员密码长度（自动生成）
DEFAULT_ADMIN_PASSWORD_LENGTH = 16
