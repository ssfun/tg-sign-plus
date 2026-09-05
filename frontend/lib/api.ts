import { TokenResponse } from "./types";
import { clearToken, getToken, refreshAccessToken } from "./auth";
import { CSRF_HEADER_NAME, csrfHeaders } from "./utils";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api";

const pathSegment = (value: string) => encodeURIComponent(value);

const toRecord = (headers?: HeadersInit): Record<string, string> => {
  if (!headers) return {};
  if (headers instanceof Headers) {
    return Object.fromEntries(headers.entries());
  }
  if (Array.isArray(headers)) {
    return Object.fromEntries(headers);
  }
  return headers as Record<string, string>;
};

const redirectToLogin = () => {
  clearToken();
  if (typeof window !== "undefined") {
    window.location.href = "/";
  }
};

const buildHeaders = (headers?: HeadersInit, token?: string | null, body?: BodyInit | null, method?: string) => {
  const mergedHeaders: Record<string, string> = {
    ...toRecord(headers),
  };
  if (!mergedHeaders["Content-Type"] && typeof body === "string") {
    mergedHeaders["Content-Type"] = "application/json";
  }
  if (token) {
    mergedHeaders["Authorization"] = `Bearer ${token}`;
  }
  const methodName = (method || "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS", "TRACE"].includes(methodName) && !mergedHeaders[CSRF_HEADER_NAME]) {
    Object.assign(mergedHeaders, csrfHeaders());
  }
  return mergedHeaders;
};

const parseError = async (res: Response) => {
  let errorMessage = "请求失败";
  let errorCode: string | undefined;
  try {
    const errorData = await res.json();
    if (errorData && typeof errorData === "object") {
      errorMessage = errorData.detail || errorData.message || JSON.stringify(errorData);
      errorCode = errorData.code;
    } else {
      errorMessage = JSON.stringify(errorData);
    }
  } catch {
    try {
      errorMessage = await res.text() || "请求失败";
    } catch {
      // ignore
    }
  }
  const err: any = new Error(errorMessage);
  err.status = res.status;
  if (errorCode) {
    err.code = errorCode;
  }
  return err;
};

async function request<T>(
  path: string,
  options: RequestInit = {},
  allowRefresh: boolean = true
): Promise<T> {
  const currentToken = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: buildHeaders(options.headers, currentToken, options.body, options.method),
    cache: "no-store",
    credentials: "include",
  });

  if (res.status === 401 && currentToken && allowRefresh && !path.startsWith("/auth/refresh") && !path.startsWith("/auth/login") && !path.startsWith("/auth/logout")) {
    const refreshedToken = await refreshAccessToken();
    if (refreshedToken) {
      return request<T>(path, options, false);
    }
    redirectToLogin();
  }

  if (!res.ok) {
    if (res.status === 401 && path.startsWith("/auth/refresh")) {
      redirectToLogin();
    }
    throw await parseError(res);
  }
  if (res.status === 204) {
    return {} as T;
  }
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return res.json();
  }
  return (await res.text()) as T;
}

// ============ 认证 ============

export const login = (payload: {
  username: string;
  password: string;
  totp_code?: string;
}) =>
  request<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  }, false);

export const getMe = () =>
  request("/auth/me");

export const resetTOTP = (payload: { username: string; password: string }) =>
  request<{ success: boolean; message: string }>("/auth/reset-totp", {
    method: "POST",
    body: JSON.stringify(payload),
  }, false);


// ============ 账号管理（重构版）============

export interface LoginStartRequest {
  account_name: string;
  phone_number: string;
  proxy?: string;
  chat_cache_ttl_minutes?: number;
}

export interface LoginStartResponse {
  phone_code_hash: string;
  phone_number: string;
  account_name: string;
  message: string;
}

export interface LoginVerifyRequest {
  account_name: string;
  phone_number: string;
  phone_code: string;
  phone_code_hash: string;
  password?: string;
  proxy?: string;
  chat_cache_ttl_minutes?: number;
}

export interface LoginVerifyResponse {
  success: boolean;
  user_id?: number;
  first_name?: string;
  username?: string;
  message: string;
}

export interface QrLoginStartRequest {
  account_name: string;
  proxy?: string;
  chat_cache_ttl_minutes?: number;
}

export interface QrLoginStartResponse {
  login_id: string;
  qr_uri: string;
  qr_image?: string | null;
  expires_at: string;
}

export interface QrLoginStatusResponse {
  status: string;
  expires_at?: string;
  message?: string;
  account?: AccountInfo | null;
  user_id?: number;
  first_name?: string;
  username?: string;
}

export interface QrLoginCancelResponse {
  success: boolean;
  message: string;
}

export interface QrLoginPasswordRequest {
  login_id: string;
  password: string;
}

export interface QrLoginPasswordResponse {
  success: boolean;
  message: string;
  account?: AccountInfo | null;
  user_id?: number;
  first_name?: string;
  username?: string;
}

export interface AccountInfo {
  name: string;
  session_file: string;
  exists: boolean;
  size: number;
  remark?: string | null;
  proxy?: string | null;
  chat_cache_ttl_minutes?: number;
}

export interface AccountStatusCheckRequest {
  account_names?: string[];
  timeout_seconds?: number;
}

export interface AccountStatusItem {
  account_name: string;
  ok: boolean;
  status: "connected" | "invalid" | "error" | "not_found" | string;
  message?: string;
  code?: string;
  checked_at?: string;
  needs_relogin?: boolean;
  user_id?: number;
}

export interface AccountStatusCheckResponse {
  results: AccountStatusItem[];
}

export const startAccountLogin = (data: LoginStartRequest) =>
  request<LoginStartResponse>("/accounts/login/start", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const verifyAccountLogin = (data: LoginVerifyRequest) =>
  request<LoginVerifyResponse>("/accounts/login/verify", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const listAccounts = () =>
  request<{ accounts: AccountInfo[]; total: number }>("/accounts");

export const checkAccountsStatus = (data: AccountStatusCheckRequest) =>
  request<AccountStatusCheckResponse>("/accounts/status/check", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const deleteAccount = (accountName: string) =>
  request<{ success: boolean; message: string }>(`/accounts/${pathSegment(accountName)}`, {
    method: "DELETE",
  });

export const checkAccountExists = (accountName: string) =>
  request<{ exists: boolean; account_name: string }>(`/accounts/${pathSegment(accountName)}/exists`);

export const updateAccount = (
  accountName: string,
  data: { remark?: string | null; proxy?: string | null; chat_cache_ttl_minutes?: number | null }
) =>
  request<{ success: boolean; message: string; account?: AccountInfo | null }>(`/accounts/${pathSegment(accountName)}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const startQrLogin = (data: QrLoginStartRequest) =>
  request<QrLoginStartResponse>("/accounts/qr/start", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const getQrLoginStatus = (loginId: string) =>
  request<QrLoginStatusResponse>(`/accounts/qr/status?login_id=${encodeURIComponent(loginId)}`);

export const cancelQrLogin = (loginId: string) =>
  request<QrLoginCancelResponse>("/accounts/qr/cancel", {
    method: "POST",
    body: JSON.stringify({ login_id: loginId }),
  });

export const submitQrPassword = (data: QrLoginPasswordRequest) =>
  request<QrLoginPasswordResponse>("/accounts/qr/password", {
    method: "POST",
    body: JSON.stringify(data),
  });

// ============ 配置管理 ============

export const listConfigTasks = () =>
  request<{ sign_tasks: string[]; total: number }>("/config/tasks");

export const exportSignTask = (taskName: string, accountName?: string) => {
  const params = new URLSearchParams();
  if (accountName) params.append("account_name", accountName);
  const url = `/config/export/sign/${pathSegment(taskName)}${params.toString() ? `?${params.toString()}` : ""}`;
  return request<string>(url, {
    headers: {
      Accept: "text/plain",
    },
  });
};

export const importSignTask = (
  configJson: string,
  taskName?: string,
  accountName?: string
) =>
  request<{ success: boolean; task_name: string; message: string }>("/config/import/sign", {
    method: "POST",
    body: JSON.stringify({ config_json: configJson, task_name: taskName, account_name: accountName }),
  });

export const exportAllConfigs = () =>
  request<Record<string, unknown>>("/config/export/all");

export const importAllConfigs = (configJson: string, overwrite = false) =>
  request<{
    signs_imported: number;
    signs_skipped: number;
    errors: string[];
    message: string;
  }>("/config/import/all", {
    method: "POST",
    body: JSON.stringify({ config_json: configJson, overwrite }),
  });

export const deleteSignConfig = (taskName: string, accountName?: string) => {
  const params = new URLSearchParams();
  if (accountName) params.append("account_name", accountName);
  const url = `/config/sign/${pathSegment(taskName)}${params.toString() ? `?${params.toString()}` : ""}`;
  return request<{ success: boolean; message: string }>(url, {
    method: "DELETE",
  });
};


// ============ 用户设置 ============

export const changePassword = (oldPassword: string, newPassword: string) =>
  request<{ success: boolean; message: string }>("/user/password", {
    method: "PUT",
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  });

export const getTOTPStatus = () =>
  request<{ enabled: boolean; secret?: string }>("/user/totp/status");

export const setupTOTP = () =>
  request<{ enabled: boolean; secret: string }>("/user/totp/setup", {
    method: "POST",
  });

export const enableTOTP = (totpCode: string) =>
  request<{ success: boolean; message: string }>("/user/totp/enable", {
    method: "POST",
    body: JSON.stringify({ totp_code: totpCode }),
  });

export const disableTOTP = (totpCode: string) =>
  request<{ success: boolean; message: string }>("/user/totp/disable", {
    method: "POST",
    body: JSON.stringify({ totp_code: totpCode }),
  });

export const changeUsername = (newUsername: string, password: string) =>
  request<ChangeUsernameResponse>("/user/username", {
    method: "PUT",
    body: JSON.stringify({ new_username: newUsername, password: password }),
  });

// ============ AI 配置 ============

export interface AIConfig {
  has_config: boolean;
  base_url?: string;
  model?: string;
  api_key_masked?: string;
}

export interface ChangeUsernameResponse {
  success: boolean;
  message: string;
  access_token?: string;
}

export interface AITestResult {
  success: boolean;
  message: string;
  model_used?: string;
}

export const getAIConfig = () =>
  request<AIConfig>("/config/ai");

export const saveAIConfig = (
  config: { api_key?: string; base_url?: string; model?: string }
) =>
  request<{ success: boolean; message: string }>("/config/ai", {
    method: "POST",
    body: JSON.stringify(config),
  });

export const testAIConnection = () =>
  request<AITestResult>("/config/ai/test", {
    method: "POST",
  });

export const deleteAIConfig = () =>
  request<{ success: boolean; message: string }>("/config/ai", {
    method: "DELETE",
  });

// ============ 全局设置 ============

export interface GlobalSettings {
  sign_interval?: number | null;  // null 表示随机 1-120 秒
  log_retention_days?: number;    // 日志保留天数，默认 7
  data_dir?: string | null;
}

export const getGlobalSettings = () =>
  request<GlobalSettings>("/config/settings");

export const saveGlobalSettings = (settings: GlobalSettings) =>
  request<{ success: boolean; message: string }>("/config/settings", {
    method: "POST",
    body: JSON.stringify(settings),
  });

// ============ Telegram API 配置 ============

export interface TelegramConfig {
  api_id: string;
  api_hash_masked?: string | null;
  has_api_hash: boolean;
  is_custom: boolean;
  default_api_id: string;
  default_api_hash_masked?: string | null;
}

export const getTelegramConfig = () =>
  request<TelegramConfig>("/config/telegram");

export const saveTelegramConfig = (
  config: { api_id: string; api_hash: string }
) =>
  request<{ success: boolean; message: string }>("/config/telegram", {
    method: "POST",
    body: JSON.stringify(config),
  });

export const resetTelegramConfig = () =>
  request<{ success: boolean; message: string }>("/config/telegram", {
    method: "DELETE",
  });

// ============ 账号日志 ============

export interface AccountLog {
  id: number;
  account_name: string;
  task_name: string;
  message: string;
  summary?: string;
  bot_message?: string;
  success: boolean;
  created_at: string;
  flow_event_counts?: Record<string, number>;
  run_summary?: SignTaskRunSummary;
}

export const getAccountLogs = (accountName: string, limit: number = 100) =>
  request<AccountLog[]>(`/accounts/${pathSegment(accountName)}/logs?limit=${limit}`);

export const clearAccountLogs = (accountName: string) =>
  request<{ success: boolean; cleared: number; message: string; code?: string }>(
    `/accounts/${pathSegment(accountName)}/logs/clear`,
    { method: "POST" }
  );

export const exportAccountLogs = async (accountName: string) => {
  const res = await fetch(`${API_BASE}/accounts/${pathSegment(accountName)}/logs/export`, {
    headers: {
      Authorization: `Bearer ${getToken()}`,
    },
    credentials: "include",
    cache: "no-store",
  });
  if (!res.ok) throw new Error("Export failed");
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `logs_${accountName}.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
};

// ============ 签到任务管理 ============

export type SignTaskAction =
  | { action: 1; text: string }
  | { action: 2; dice: string }
  | { action: 3; text: string }
  | { action: 4 }
  | { action: 5 }
  | {
      action: 6;
      caption_pattern?: string;
      captcha_lengths?: number[];
      captcha_charset?: string;
      captcha_case?: "preserve" | "upper" | "lower";
      reply_to_message?: boolean;
    }
  | { action: 7 }
  | { action: 8 }
  | {
      action: 9;
      keywords: string[];
    };

export interface SignTaskChat {
  chat_id: number;
  name: string;
  actions: SignTaskAction[];
  delete_after?: number;
  event_timeout?: number;
  event_retries?: number;
  event_retry_wait?: number;
  event_history_limit?: number;
  event_history_failure_threshold?: number;
  event_history_rescue_interval?: number;
  event_history_rpc_timeout?: number;
  event_history_result_max_age?: number;
  event_action_timeout?: number;
  event_send_timeout?: number;
  event_media_timeout?: number;
  event_ai_timeout?: number;
  event_callback_timeout?: number;
  event_callback_retries?: number;
  event_ai_fallback?: boolean;
}

export interface SignTaskRunSummary {
  [key: string]: unknown;
  success: boolean;
  status: "success" | "checked" | "failed" | string;
  error?: string;
  attempt?: number;
  total_attempts?: number;
  task_timeout_seconds?: number | null;
  requires_updates?: boolean | null;
  retry_count?: number;
  retry_budget_remaining?: number;
  retry_suppressed_count?: number;
  current_response_index?: number;
  response_action_count?: number;
  current_action?: string;
  attempt_epoch?: number;
  result_match?: {
    [key: string]: unknown;
    event?: string;
    matched?: boolean;
    status?: string;
    source?: string;
    message_id?: number;
    keyword?: string;
    attempt_epoch?: number;
    current_response_index?: number;
    current_action?: string;
    retry_count?: number;
    retry_budget_remaining?: number;
    retry_pending?: boolean;
  };
  retry?: {
    [key: string]: unknown;
    last_event?: string;
    last_reason?: string;
    last_retry_count?: number;
    last_budget_remaining?: number;
    last_attempt_epoch?: number;
    last_source?: string;
    last_message_id?: number;
    last_trigger?: string;
    attempt_state_resets?: number;
    last_reset_previous_attempt_epoch?: number;
    last_reset_attempt_epoch?: number;
    last_reset_cleared_processed_versions?: number;
    last_reset_cleared_sent_captcha_versions?: number;
    last_reset_cleared_clicked_versions?: number;
    last_reset_cleared_history_duplicates?: number;
    last_reset_cleared_history_filtered?: number;
    last_reset_cleared_history_unhandled?: number;
    last_reset_cleared_history_unhandled_duplicates?: number;
    last_reset_cleared_history_tracked_message_ids?: number;
    last_current_response_index?: number;
    last_current_action?: string;
    last_retry_pending?: boolean;
    scheduled_count?: number;
    started_count?: number;
    completed_count?: number;
    cancelled_count?: number;
    suppressed_count?: number;
    initial_send_failed_count?: number;
    initial_send_error_count?: number;
    limit_exceeded?: boolean;
    limit_exceeded_count?: number;
    max_inline_retries?: number;
    task_configured_count?: number;
    task_configured_total_attempts?: number;
    task_last_event?: string;
    task_scheduled_count?: number;
    task_started_count?: number;
    task_last_attempt?: number;
    task_last_total_attempts?: number;
    task_last_retry_count?: number;
    task_last_budget_remaining?: number;
    task_last_error_type?: string;
    task_last_retryable?: boolean;
  };
  callbacks?: {
    [key: string]: unknown;
    confirmed?: number;
    trusted_timeout?: number;
    data_invalid_after_timeout?: number;
    unconfirmed?: number;
    total_results?: number;
    outer_timeouts?: number;
    exceptions?: number;
    released_for_retry?: number;
    callback_texts?: number;
    stale_callback_texts?: number;
    last_status?: string;
    last_reason?: string;
    last_source?: string;
    last_current_response_index?: number;
    last_current_action?: string;
    last_retry_pending?: boolean;
    last_retry_budget_remaining?: number;
    last_message_id?: number;
    last_button_text?: string;
    last_confirmed?: boolean;
    last_attempt?: number;
    last_max_retries?: number;
    last_timeout?: number;
    last_error_type?: string;
    last_had_timeout?: boolean;
    last_trusted_consumed?: boolean;
    last_has_callback_text?: boolean;
    last_outer_timeout_source?: string;
    last_outer_timeout_scope?: string;
    last_outer_operation_timeout?: number;
    last_outer_timeout_attempt_epoch?: number;
    last_outer_timeout_current_response_index?: number;
    last_outer_timeout_current_action?: string;
    last_outer_timeout_retry_count?: number;
    last_outer_timeout_retry_budget_remaining?: number;
    last_outer_timeout_retry_pending?: boolean;
    last_exception_source?: string;
    last_exception_error_type?: string;
    last_exception_operation_timeout?: number;
    last_unconfirmed_source?: string;
    last_unconfirmed_message_id?: number;
    last_unconfirmed_button_text?: string;
    last_unconfirmed_status?: string;
    last_unconfirmed_reason?: string;
    last_unconfirmed_attempt_epoch?: number;
    last_unconfirmed_current_response_index?: number;
    last_unconfirmed_current_action?: string;
    last_unconfirmed_retry_count?: number;
    last_unconfirmed_retry_budget_remaining?: number;
    last_unconfirmed_retry_pending?: boolean;
    last_unconfirmed_attempt?: number;
    last_unconfirmed_max_retries?: number;
    last_unconfirmed_timeout?: number;
    last_unconfirmed_error_type?: string;
    last_unconfirmed_had_timeout?: boolean;
    last_released_source?: string;
    last_released_message_id?: number;
    last_released_button_text?: string;
    last_released_status?: string;
    last_released_attempt_epoch?: number;
    last_released_current_response_index?: number;
    last_released_current_action?: string;
    last_released_retry_count?: number;
    last_released_retry_budget_remaining?: number;
    last_released_attempt?: number;
    last_released_max_retries?: number;
    last_released_timeout?: number;
    last_released_retry_pending?: boolean;
    last_released_clicked_versions?: number;
    last_stale_callback_text_message_id?: number;
    last_stale_callback_text_attempt_epoch?: number;
    last_stale_callback_text_current_epoch?: number;
  };
  messages?: {
    [key: string]: unknown;
    processed_versions?: number;
    processing_versions?: number;
    sent_captcha_versions?: number;
    captcha_result_text_preemptions?: number;
    response_messages_sent?: number;
    response_actions_advanced?: number;
    last_response_action_from_index?: number;
    last_response_action_to_index?: number;
    last_response_action_source?: string;
    last_response_action_reason?: string;
    last_response_action_attempt_epoch?: number;
    last_response_action_message_id?: number;
    response_actions_not_advanced?: number;
    last_response_action_not_advanced_index?: number;
    last_response_action_not_advanced_source?: string;
    last_response_action_not_advanced_reason?: string;
    last_response_action_not_advanced_finished?: boolean;
    last_response_action_not_advanced_retry_pending?: boolean;
    last_response_action_not_advanced_attempt_epoch?: number;
    last_response_action_not_advanced_message_id?: number;
    message_retryable_errors?: number;
    last_message_retryable_message_id?: number;
    last_message_retryable_error_type?: string;
    last_message_retryable_operation?: string;
    last_message_retryable_timeout_scope?: string;
    last_message_retryable_operation_timeout?: number;
    last_message_retryable_attempt_epoch?: number;
    last_message_retryable_current_response_index?: number;
    last_message_retryable_current_action?: string;
    last_message_retryable_retry_count?: number;
    last_message_retryable_retry_budget_remaining?: number;
    last_message_retryable_retry_pending?: boolean;
    clicked_versions?: number;
    skipped_clicked_duplicate?: number;
    skipped_duplicate?: number;
    skipped_concurrent_duplicate?: number;
    skipped_finished?: number;
    skipped_non_inbound?: number;
    message_processing_cancelled?: number;
    last_message_processing_cancelled_message_id?: number;
    last_message_processing_cancelled_version_hash?: string;
    last_message_processing_cancelled_action?: string;
    last_message_processing_cancelled_attempt_epoch?: number;
    last_message_processing_cancelled_retry_pending?: boolean;
    last_message_processing_cancelled_will_release?: boolean;
    stale_attempt_processed_marks?: number;
    last_stale_attempt_message_epoch?: number;
    last_stale_attempt_current_epoch?: number;
    last_skip_reason?: string;
    last_skip_message_id?: number;
    last_skip_message_version_hash?: string;
    last_skip_attempt_epoch?: number;
    last_skip_current_response_index?: number;
    last_skip_current_action?: string;
    last_skip_retry_count?: number;
    last_skip_retry_budget_remaining?: number;
    last_skip_retry_pending?: boolean;
    unhandled?: number;
  };
  history?: {
    [key: string]: unknown;
    startup_scans?: number;
    rescue_scans?: number;
    failed_scans?: number;
    messages_handled?: number;
    duplicate_messages?: number;
    messages_seen?: number;
    messages_allowed?: number;
    tracked_rechecks?: number;
    concurrent_skipped?: number;
    cancelled_scans?: number;
    scan_in_progress?: boolean;
    rescue_suspended?: boolean;
    circuit_opened?: number;
    consecutive_failures?: number;
    expired_messages?: number;
    filtered_before_entry?: number;
    filtered_expired?: number;
    hard_failures_skipped?: number;
    unhandled_duplicates?: number;
    last_scan_status?: string;
    last_scan_source?: string;
    last_scan_message_count?: number;
    last_scan_allowed_count?: number;
    last_scan_handled_count?: number;
    last_scan_error_type?: string;
    last_scan_attempt_epoch?: number;
    last_scan_current_response_index?: number;
    last_scan_current_action?: string;
    last_scan_retry_count?: number;
    last_scan_retry_budget_remaining?: number;
    last_scan_retry_pending?: boolean;
    last_failed_source?: string;
    last_failed_operation?: string;
    last_failed_timeout_scope?: string;
    last_failed_error_type?: string;
    last_failed_timeout?: number;
    last_failed_scan_count?: number;
    last_failure_scan_in_progress?: boolean;
    last_failure_blocks_main_flow?: boolean;
    last_failure_retry_pending?: boolean;
    last_failure_will_open_circuit?: boolean;
    last_failure_rescue_will_continue?: boolean;
    last_suspended_source?: string;
    last_suspended_status?: string;
    last_suspended_attempt_epoch?: number;
    last_suspended_current_response_index?: number;
    last_suspended_current_action?: string;
    last_suspended_retry_count?: number;
    last_suspended_retry_budget_remaining?: number;
    last_suspended_retry_pending?: boolean;
  };
  timeouts?: {
    [key: string]: unknown;
    timeout_count_total?: number;
    event?: number;
    response_action?: number;
    callback_outer?: number;
    send_rpc?: number;
    media_rpc?: number;
    ai_rpc?: number;
    task_run?: number;
    client_rpc?: number;
    client_cleanup_rpc?: number;
    client_cleanup_rpc_last_timeout?: number;
    client_rpc_late_cancelled?: number;
    client_rpc_late_completed?: number;
    client_rpc_late_exception?: number;
    client_rpc_last_late_event?: string;
    client_rpc_last_late_operation?: string;
    client_rpc_last_late_timeout_scope?: string;
    client_rpc_last_late_error_type?: string;
    client_rpc_last_late_timeout?: number;
    client_startup_retry?: number;
    client_startup_retry_last_attempt?: number;
    client_startup_retry_total_attempts?: number;
    client_startup_retry_budget_remaining?: number;
    client_startup_retry_wait_seconds?: number;
    client_startup_retry_cleanup_attempted?: boolean;
    client_startup_retry_error_type?: string;
    client_startup_retry_reason?: string;
    client_startup_lock?: number;
    client_startup_lock_timeout_seconds?: number;
    client_exit_lock?: number;
    client_exit_lock_timeout_seconds?: number;
    client_close_lock?: number;
    client_close_lock_timeout_seconds?: number;
    task_run_late_cancelled?: number;
    task_run_late_completed?: number;
    task_run_late_exception?: number;
    task_run_last_late_event?: string;
    task_run_last_late_operation?: string;
    task_run_last_late_timeout_scope?: string;
    task_run_last_late_error_type?: string;
    task_run_last_late_timeout_seconds?: number;
    task_run_last_late_attempt?: number;
    task_run_last_late_total_attempts?: number;
    task_run_cancelled?: boolean;
    task_run_cleanup_expected?: boolean;
    task_run_operation?: string;
    task_run_timeout_scope?: string;
    task_run_timeout_seconds?: number;
    task_run_attempt?: number;
    task_run_total_attempts?: number;
    late_cancelled?: number;
    late_completed?: number;
    late_exception?: number;
    last_late_event?: string;
    last_late_operation?: string;
    last_late_timeout_scope?: string;
    last_late_source?: string;
    last_late_message_id?: number;
    last_late_error_type?: string;
    last_late_timeout?: number;
    last_late_cancelled_by_parent?: boolean;
    last_late_attempt_epoch?: number;
    last_late_current_response_index?: number;
    last_late_current_action?: string;
    last_late_retry_count?: number;
    last_late_retry_budget_remaining?: number;
    last_late_retry_pending?: boolean;
    last_rpc_event?: string;
    last_rpc_kind?: string;
    last_rpc_operation?: string;
    last_rpc_timeout_scope?: string;
    last_rpc_source?: string;
    last_rpc_message_id?: number;
    last_rpc_source_message_id?: number;
    last_rpc_error_type?: string;
    last_rpc_timeout?: number;
  };
  runtime?: {
    [key: string]: unknown;
    runtime_config_key?: string | null;
    chat_count?: number | null;
    event_chat_count?: number | null;
    configured_action_count?: number | null;
    send_action_count?: number | null;
    button_action_count?: number | null;
    image_option_action_count?: number | null;
    captcha_action_count?: number | null;
    captcha_caption_pattern_count?: number | null;
    captcha_length_constrained_count?: number | null;
    captcha_charset_constrained_count?: number | null;
    captcha_reply_to_message_count?: number | null;
    assertion_action_count?: number | null;
    requires_result_assertion?: boolean | null;
    event_timeout?: number | null;
    action_timeout?: number | null;
    send_timeout?: number | null;
    media_timeout?: number | null;
    ai_timeout?: number | null;
    callback_timeout?: number | null;
    callback_retries?: number | null;
    ai_fallback_enabled?: boolean | null;
    retry_wait?: number | null;
    max_inline_retries?: number | null;
    history_limit?: number | null;
    history_rescue_interval?: number | null;
    history_rpc_timeout?: number | null;
    history_result_max_age?: number | null;
    history_failure_threshold?: number | null;
    ai_fallback_enabled_count?: number | null;
    ai_fallback_disabled_count?: number | null;
  };
  cleanup?: {
    [key: string]: unknown;
    started?: boolean;
    completed?: boolean;
    failed?: boolean;
    last_event?: string;
    last_attempt?: number;
    last_total_attempts?: number;
    last_success?: boolean;
    last_operation?: string;
    last_timeout_scope?: string;
    error_type?: string | null;
    timeout_seconds?: number;
    manager_lock_present?: boolean;
    manager_lock_acquired?: boolean;
    manager_lock_wait_timeout?: boolean;
    manager_lock_timeout_seconds?: number;
    manager_force_cleanup?: boolean;
    manager_client_found?: boolean;
    manager_cleanup_attempted?: boolean;
    manager_cleanup_error_type?: string;
    rpc_attempts?: number;
    rpc_timeouts?: number;
    rpc_errors?: number;
    last_rpc_error_type?: string;
    last_rpc_timeout?: number;
    rpc_late_cancelled?: number;
    rpc_late_completed?: number;
    rpc_late_exception?: number;
    last_rpc_late_event?: string;
    last_rpc_late_error_type?: string;
    last_rpc_late_timeout?: number;
    deferred_cancellations?: number;
    last_deferred_cancel_attempt?: number;
    last_deferred_cancel_total_attempts?: number;
    last_deferred_cancel_success?: boolean;
    last_deferred_cancel_timeout_seconds?: number;
    late_cancelled?: number;
    late_completed?: number;
    late_exception?: number;
    last_late_event?: string;
    last_late_operation?: string;
    last_late_timeout_scope?: string;
    last_late_error_type?: string;
    last_late_timeout_seconds?: number;
    last_late_attempt?: number;
    last_late_total_attempts?: number;
    last_late_success?: boolean;
  };
  persistence?: {
    [key: string]: unknown;
    run_info_save_failed?: boolean;
    run_info_save_error_type?: string | null;
  };
  account_lock?: {
    [key: string]: unknown;
    waited?: boolean;
    acquired?: boolean;
    wait_timeout?: boolean;
    last_operation?: string;
    last_timeout_scope?: string;
    wait_timeout_seconds?: number;
    released?: boolean;
    wait_seconds?: number;
    release_success?: boolean;
    release_attempt?: number;
    release_total_attempts?: number;
  };
  global_concurrency?: {
    [key: string]: unknown;
    waited?: boolean;
    acquired?: boolean;
    wait_timeout?: boolean;
    last_operation?: string;
    last_timeout_scope?: string;
    wait_timeout_seconds?: number;
    released?: boolean;
    wait_seconds?: number;
    release_success?: boolean;
    release_attempt?: number;
    release_total_attempts?: number;
  };
  error_type?: string | null;
  error_timeout_scope?: "outer_task" | "internal_rpc" | "none" | string | null;
}

export interface LastRunInfo {
  time: string;
  success: boolean;
  message?: string;
  flow_event_counts?: Record<string, number>;
  run_summary?: SignTaskRunSummary;
}

export interface SignTask {
  name: string;
  account_name: string;
  sign_at: string;
  chats: SignTaskChat[];
  random_seconds: number;
  sign_interval: number;
  retry_count: number;
  engine?: "event";
  enabled: boolean;
  last_run?: LastRunInfo | null;
  execution_mode?: "fixed" | "range";
  range_start?: string;
  range_end?: string;
  next_scheduled_at?: string | null;
}

export interface CreateSignTaskRequest {
  name: string;
  account_name: string;
  sign_at: string;
  chats: SignTaskChat[];
  random_seconds?: number;
  sign_interval?: number;
  retry_count?: number;
  execution_mode?: "fixed" | "range";
  range_start?: string;
  range_end?: string;
}

export interface UpdateSignTaskRequest {
  sign_at?: string;
  chats?: SignTaskChat[];
  random_seconds?: number;
  sign_interval?: number;
  retry_count?: number;
  execution_mode?: "fixed" | "range";
  range_start?: string;
  range_end?: string;
}

export interface ChatInfo {
  id: number;
  title?: string;
  username?: string;
  type: string;
  first_name?: string;
}

export interface ChatSearchResponse {
  items: ChatInfo[];
  total: number;
  limit: number;
  offset: number;
}

export interface ChatCacheResponse {
  items: ChatInfo[];
  last_cached_at?: string | null;
  cache_ttl_minutes: number;
  expired: boolean;
  count: number;
}

export async function listSignTasks(accountName?: string, forceRefresh?: boolean): Promise<SignTask[]> {
  const params = new URLSearchParams();
  if (accountName) params.append('account_name', accountName);
  if (forceRefresh) params.append('force_refresh', 'true');
  const url = `/sign-tasks${params.toString() ? `?${params.toString()}` : ''}`;
  return request<SignTask[]>(url);
}

export const getSignTask = (name: string, accountName?: string) => {
  const params = new URLSearchParams();
  if (accountName) params.append("account_name", accountName);
  const url = `/sign-tasks/${pathSegment(name)}${params.toString() ? `?${params.toString()}` : ""}`;
  return request<SignTask>(url);
};

export const createSignTask = (data: CreateSignTaskRequest) =>
  request<SignTask>("/sign-tasks", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const updateSignTask = (name: string, data: UpdateSignTaskRequest, accountName?: string) => {
  const params = new URLSearchParams();
  if (accountName) params.append("account_name", accountName);
  return request<SignTask>(`/sign-tasks/${pathSegment(name)}${params.toString() ? `?${params.toString()}` : ""}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
};

export const deleteSignTask = (name: string, accountName?: string) => {
  const params = new URLSearchParams();
  if (accountName) params.append("account_name", accountName);
  return request<{ ok: boolean }>(`/sign-tasks/${pathSegment(name)}${params.toString() ? `?${params.toString()}` : ""}`, {
    method: "DELETE",
  });
};

export const setSignTaskEnabled = (name: string, accountName: string, enabled: boolean) =>
  request<SignTask>(`/sign-tasks/${pathSegment(name)}/enabled`, {
    method: "PATCH",
    body: JSON.stringify({ account_name: accountName, enabled }),
  });

export const runSignTask = (name: string, accountName: string) => {
  const params = new URLSearchParams({ account_name: accountName });
  return request<{ success: boolean; output: string; error: string; run_summary?: SignTaskRunSummary; started: boolean; code: string }>(`/sign-tasks/${pathSegment(name)}/run?${params.toString()}`, {
    method: "POST",
  });
};

export const getSignTaskStatus = (name: string, accountName: string, signal?: AbortSignal) =>
  request<{ running: boolean }>(`/sign-tasks/${pathSegment(name)}/status?${new URLSearchParams({ account_name: accountName })}`, { signal });

export const getAccountChats = (
  accountName: string,
  options?: { forceRefresh?: boolean; autoRefreshIfExpired?: boolean; ensureExists?: boolean }
) => {
  const params = new URLSearchParams();
  if (options?.forceRefresh) params.append("force_refresh", "true");
  if (options?.autoRefreshIfExpired) params.append("auto_refresh_if_expired", "true");
  if (options?.ensureExists) params.append("ensure_exists", "true");
  const query = params.toString();
  return request<ChatCacheResponse>(`/sign-tasks/chats/${pathSegment(accountName)}${query ? `?${query}` : ""}`);
};

export const refreshAccountChats = (accountName: string) =>
  request<ChatCacheResponse>(`/sign-tasks/chats/${pathSegment(accountName)}/refresh`, {
    method: "POST",
  });

export const getAccountChatCacheMeta = (accountName: string) =>
  request<Pick<ChatCacheResponse, "last_cached_at" | "cache_ttl_minutes" | "expired" | "count"> & { account_name: string }>(`/sign-tasks/chats/${pathSegment(accountName)}/meta`);

export const searchAccountChats = (
  accountName: string,
  query: string,
  limit: number = 50,
  offset: number = 0
) => {
  const params = new URLSearchParams();
  params.append("q", query);
  params.append("limit", String(limit));
  params.append("offset", String(offset));
  return request<ChatSearchResponse>(`/sign-tasks/chats/${pathSegment(accountName)}/search?${params.toString()}`);
};

export const getSignTaskLogs = (name: string, accountName?: string) => {
    const params = new URLSearchParams();
    if (accountName) params.append("account_name", accountName);
    const url = `/sign-tasks/${pathSegment(name)}/logs${params.toString() ? `?${params.toString()}` : ""}`;
    return request<string[]>(url);
};

export interface SchedulerSignTaskStatus {
  job_id: string;
  account_name: string;
  task_name: string;
  enabled: boolean;
  execution_mode: "fixed" | "range" | string;
  schedule: string;
  next_run?: string | null;
  next_scheduled_at?: string | null;
  effective_next_run?: string | null;
  execution_job_exists: boolean;
  job_exists: boolean;
}

export interface SchedulerStatus {
  timezone: string;
  running: boolean;
  total_jobs: number;
  sign_job_count: number;
  sign_tasks: SchedulerSignTaskStatus[];
}

export const getSchedulerStatus = (accountName?: string) => {
  const params = new URLSearchParams();
  if (accountName) params.append("account_name", accountName);
  return request<SchedulerStatus>(`/sign-tasks/scheduler/status${params.toString() ? `?${params.toString()}` : ""}`);
};

export interface SignTaskFlowItem {
  ts: string;
  level: "info" | "warning" | "error" | "success" | string;
  stage: "task" | "session" | "preheat" | "action" | "message" | "result" | string;
  event: string;
  text: string;
  meta?: Record<string, string | number | boolean | null>;
  text_visible?: boolean;
}

export interface SignTaskDiagnosticCheck {
  id: string;
  label: string;
  status: "pass" | "warn" | "fail" | "skip" | "unknown" | string;
  detail?: string;
}

export interface SignTaskDiagnostics {
  status: "pass" | "warn" | "fail" | "unknown" | string;
  summary: string;
  checks: SignTaskDiagnosticCheck[];
  milestones: Record<string, string | number | boolean | null>;
}

export interface SignTaskHistoryItem {
  time: string;
  success: boolean;
  message?: string;
  flow_logs?: string[];
  flow_items?: SignTaskFlowItem[];
  flow_event_counts?: Record<string, number>;
  flow_truncated?: boolean;
  flow_line_count?: number;
  run_summary?: SignTaskRunSummary;
  diagnostics?: SignTaskDiagnostics;
}

export interface EventEngineDiagnosticRun {
  status: "pass" | "warn" | "fail" | "stale" | "missing" | "unknown" | string;
  success: boolean;
  time: string;
  age_hours?: number | null;
  fresh: boolean;
  message?: string;
  event_counts: Record<string, number>;
  run_summary: Partial<SignTaskRunSummary>;
  diagnostics: SignTaskDiagnostics;
}

export interface EventEngineDiagnosticConfigCheck {
  id: string;
  label: string;
  status: "pass" | "warn" | "fail" | "missing" | "unknown" | string;
  detail?: string;
}

export interface EventEngineDiagnosticTask {
  task_name: string;
  account_name: string;
  engine: string;
  status: "pass" | "warn" | "fail" | "stale" | "missing" | "unknown" | string;
  config_status: "pass" | "warn" | "fail" | "missing" | "unknown" | string;
  config_checks: EventEngineDiagnosticConfigCheck[];
  run_status: string;
  latest_time?: string;
  latest_event_counts: Record<string, number>;
  latest_run_summary: Partial<SignTaskRunSummary>;
  latest_summary: string;
  runs: EventEngineDiagnosticRun[];
}

export interface EventEngineDiagnosticTarget {
  id: string;
  label: string;
  status: string;
  summary: string;
  tasks: EventEngineDiagnosticTask[];
}

export interface EventEngineDiagnosticReport {
  status: "pass" | "warn" | "fail" | "missing" | "unknown" | string;
  generated_at: string;
  max_age_hours?: number | null;
  task_count: number;
  targets: EventEngineDiagnosticTarget[];
  source?: Record<string, string | number | boolean | null>;
  hint?: string | null;
}

const buildEventEngineReportQuery = (options?: {
  accountName?: string;
  historyLimit?: number;
  maxAgeHours?: number;
}) => {
  const params = new URLSearchParams();
  if (options?.accountName) params.append("account_name", options.accountName);
  if (options?.historyLimit !== undefined) params.append("history_limit", String(options.historyLimit));
  if (options?.maxAgeHours !== undefined) params.append("max_age_hours", String(options.maxAgeHours));
  const query = params.toString();
  return query ? `?${query}` : "";
};

export const getEventEngineReport = (options?: {
  accountName?: string;
  historyLimit?: number;
  maxAgeHours?: number;
}) =>
  request<EventEngineDiagnosticReport>(
    `/sign-tasks/event-engine/report${buildEventEngineReportQuery(options)}`
  );

export const getCanaryReport = (options?: {
  accountName?: string;
  historyLimit?: number;
  maxAgeHours?: number;
}) =>
  request<EventEngineDiagnosticReport>(
    `/sign-tasks/canary/report${buildEventEngineReportQuery(options)}`
  );

export const getSignTaskHistory = (
  name: string,
  accountName: string,
  limit: number = 20,
  signal?: AbortSignal
) => {
  const params = new URLSearchParams();
  params.append("account_name", accountName);
  params.append("limit", String(limit));
  return request<SignTaskHistoryItem[]>(
    `/sign-tasks/${pathSegment(name)}/history?${params.toString()}`,
    { signal }
  );
};
