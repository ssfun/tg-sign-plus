"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { ensureAccessToken, logout } from "../../lib/auth";
import {
  listAccounts,
  checkAccountsStatus,
  startAccountLogin,
  startQrLogin,
  getQrLoginStatus,
  cancelQrLogin,
  submitQrPassword,
  updateAccount,
  verifyAccountLogin,
  deleteAccount,
  getAccountLogs,
  clearAccountLogs,
  listSignTasks,
  AccountInfo,
  AccountStatusItem,
  AccountLog,
  SignTask,
} from "../../lib/api";
import {
  Lightning,
  Plus,
  Gear,
  ListDashes,
  Spinner,
  PencilSimple,
  PaperPlaneRight,
  Trash,
  SignOut
} from "@phosphor-icons/react";
import { useToast } from "../../components/ui/toast";
import { PageLoading } from "../../components/ui/page-loading";
import { DashboardFrame } from "../../components/dashboard-frame";
import { EmptyState } from "../../components/ui/empty-state";
import { IconButton } from "../../components/ui/icon-button";
import { ModalShell } from "../../components/ui/modal-shell";
import { FormField } from "../../components/ui/form-field";
import { Input } from "../../components/ui/input";
import { Button } from "../../components/ui/button";
import { StatusBadge } from "../../components/ui/status-badge";
import { useLanguage } from "../../context/LanguageContext";
import { ThemeLanguageToggle } from "../../components/ThemeLanguageToggle";

const DEFAULT_CHAT_CACHE_TTL_MINUTES = 1440;

const EMPTY_LOGIN_DATA = {
  account_name: "",
  phone_number: "",
  proxy: "",
  phone_code: "",
  password: "",
  phone_code_hash: "",
  chat_cache_ttl_minutes: String(DEFAULT_CHAT_CACHE_TTL_MINUTES),
};
const DASHBOARD_STATUS_CHECKED_KEY = "tg-signpulse:dashboard-status-checked";
const DASHBOARD_STATUS_CACHE_KEY = "tg-signpulse:dashboard-status-cache";

export default function Dashboard() {
  const router = useRouter();
  const { t, language } = useLanguage();
  const { toasts, addToast, removeToast } = useToast();
  const [token, setLocalToken] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);
  const [tasks, setTasks] = useState<SignTask[]>([]);
  const [loading, setLoading] = useState(false);

  // 日志弹窗
  const [showLogsDialog, setShowLogsDialog] = useState(false);
  const [logsAccountName, setLogsAccountName] = useState("");
  const [accountLogs, setAccountLogs] = useState<AccountLog[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [deleteAccountName, setDeleteAccountName] = useState<string | null>(null);
  const [showClearLogsDialog, setShowClearLogsDialog] = useState(false);

  // 添加账号对话框
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [loginData, setLoginData] = useState({ ...EMPTY_LOGIN_DATA });
  const [reloginAccountName, setReloginAccountName] = useState<string | null>(null);
  const [loginMode, setLoginMode] = useState<"phone" | "qr">("phone");
  const [qrLogin, setQrLogin] = useState<{
    login_id: string;
    qr_uri: string;
    qr_image?: string | null;
    expires_at: string;
  } | null>(null);
  type QrPhase = "idle" | "loading" | "ready" | "scanning" | "password" | "success" | "expired" | "error";
  const [qrStatus, setQrStatus] = useState<
    "waiting_scan" | "scanned_wait_confirm" | "password_required" | "success" | "expired" | "failed"
  >("waiting_scan");
  const [qrPhase, setQrPhase] = useState<QrPhase>("idle");
  const [qrMessage, setQrMessage] = useState<string>("");
  const [qrCountdown, setQrCountdown] = useState<number>(0);
  const [qrLoading, setQrLoading] = useState(false);
  const [qrPassword, setQrPassword] = useState("");
  const [qrPasswordLoading, setQrPasswordLoading] = useState(false);
  const qrPasswordRef = useRef("");
  const qrPasswordLoadingRef = useRef(false);

  const qrPollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const qrCountdownTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const qrPollDelayRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const qrActiveLoginIdRef = useRef<string | null>(null);
  const qrPollSeqRef = useRef(0);
  const qrToastShownRef = useRef<Record<string, { expired?: boolean; error?: boolean }>>({});
  const qrPollingActiveRef = useRef(false);
  const qrRestartingRef = useRef(false);
  const qrAutoRefreshRef = useRef(0);

  useEffect(() => {
    qrPasswordRef.current = qrPassword;
  }, [qrPassword]);

  useEffect(() => {
    qrPasswordLoadingRef.current = qrPasswordLoading;
  }, [qrPasswordLoading]);

  // 编辑账号对话框
  const [showEditDialog, setShowEditDialog] = useState(false);
  const [editData, setEditData] = useState({
    account_name: "",
    remark: "",
    proxy: "",
    chat_cache_ttl_minutes: String(DEFAULT_CHAT_CACHE_TTL_MINUTES),
  });

  const normalizeAccountName = useCallback((name: string) => name.trim(), []);

  const sanitizeAccountName = (name: string) =>
    name.replace(/[^A-Za-z0-9\u4e00-\u9fff]/g, "");

  const isDuplicateAccountName = useCallback((name: string, allowedSameName?: string | null) => {
    const normalized = normalizeAccountName(name).toLowerCase();
    if (!normalized) return false;
    const allow = normalizeAccountName(allowedSameName || "").toLowerCase();
    return accounts.some((acc) => {
      const current = acc.name.toLowerCase();
      if (allow && current === allow && normalized === allow) {
        return false;
      }
      return current === normalized;
    });
  }, [accounts, normalizeAccountName]);

  const [checking, setChecking] = useState(true);
  const [dataLoaded, setDataLoaded] = useState(false);
  const [accountStatusMap, setAccountStatusMap] = useState<Record<string, AccountStatusItem>>({});
  const statusCheckedRef = useRef(false);

  const addToastRef = useRef(addToast);
  const tRef = useRef(t);

  useEffect(() => {
    addToastRef.current = addToast;
  }, [addToast]);

  useEffect(() => {
    tRef.current = t;
  }, [t]);

  const formatErrorMessage = useCallback((key: string, err?: any) => {
    const base = tRef.current ? tRef.current(key) : key;
    const code = err?.code;
    return code ? `${base} (${code})` : base;
  }, []);

  const shouldRunStatusCheck = useCallback(() => {
    if (typeof window === "undefined") return true;

    let navType = "";
    try {
      const nav = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
      navType = nav?.type || "";
    } catch {
      navType = "";
    }

    if (navType === "reload") {
      return true;
    }

    try {
      return sessionStorage.getItem(DASHBOARD_STATUS_CHECKED_KEY) !== "1";
    } catch {
      return true;
    }
  }, []);

  const restoreCachedStatus = useCallback(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = sessionStorage.getItem(DASHBOARD_STATUS_CACHE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return;
      setAccountStatusMap(parsed as Record<string, AccountStatusItem>);
    } catch {
      // ignore cache parse errors
    }
  }, []);

  const checkAccountStatusOnce = useCallback(async (tokenStr: string, accountList: AccountInfo[]) => {
    const accountNames = accountList.map((item) => item.name).filter(Boolean);
    if (accountNames.length === 0) {
      setAccountStatusMap({});
      return;
    }

    setAccountStatusMap((prev) => {
      const next = { ...prev };
      for (const name of accountNames) {
        next[name] = {
          account_name: name,
          ok: false,
          status: "checking",
          message: "",
          needs_relogin: false,
        };
      }
      return next;
    });

    try {
      const firstPass = await checkAccountsStatus({
        account_names: accountNames,
        timeout_seconds: 8,
      });

      const firstMap: Record<string, AccountStatusItem> = {};
      for (const item of firstPass.results || []) {
        firstMap[item.account_name] = item;
      }

      const retryNames = accountNames.filter((name) => {
        const item = firstMap[name];
        if (!item) return true;
        if (item.needs_relogin) return false;
        return item.status === "error" || item.status === "checking";
      });

      const retryMap: Record<string, AccountStatusItem> = {};
      if (retryNames.length > 0) {
        try {
          const retryPass = await checkAccountsStatus({
            account_names: retryNames,
            timeout_seconds: 12,
          });
          for (const item of retryPass.results || []) {
            retryMap[item.account_name] = item;
          }
        } catch {
          // keep first-pass result
        }
      }

      setAccountStatusMap((prev) => {
        const merged: Record<string, AccountStatusItem> = {};
        for (const name of accountNames) {
          const incomingRaw = retryMap[name] || firstMap[name];
          const incoming =
            incomingRaw && incomingRaw.status === "error" && !incomingRaw.needs_relogin
              ? { ...incomingRaw, status: "checking" as const }
              : incomingRaw;
          if (incoming) {
            const prevItem = prev[name];
            if (
              incoming.status === "error" &&
              !incoming.needs_relogin &&
              prevItem?.status === "connected"
            ) {
              merged[name] = prevItem;
              continue;
            }
            merged[name] = incoming;
            continue;
          }
          merged[name] = prev[name] || {
            account_name: name,
            ok: false,
            status: "checking",
            message: "",
            needs_relogin: false,
          };
        }
        return merged;
      });
    } catch {
      setAccountStatusMap((prev) => {
        const merged: Record<string, AccountStatusItem> = {};
        for (const name of accountNames) {
          merged[name] = prev[name] || {
            account_name: name,
            ok: false,
            status: "checking",
            message: "",
            needs_relogin: false,
          };
        }
        return merged;
      });
    }
  }, []);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      const [accountsData, tasksData] = await Promise.all([
        listAccounts(),
        listSignTasks(),
      ]);
      setAccounts(accountsData.accounts);
      setTasks(tasksData);
    } catch (err: any) {
      addToastRef.current(formatErrorMessage("load_failed", err), "error");
    } finally {
      setLoading(false);
      setDataLoaded(true);
    }
  }, [formatErrorMessage]);

  useEffect(() => {
    let mounted = true;

    void (async () => {
      const tokenStr = await ensureAccessToken();
      if (!mounted) return;
      if (!tokenStr) {
        router.replace("/");
        return;
      }
      setLocalToken(tokenStr);
      setChecking(false);
      setDataLoaded(false);
      statusCheckedRef.current = false;
      restoreCachedStatus();
      loadData();
    })();

    return () => {
      mounted = false;
    };
  }, [loadData, restoreCachedStatus, router]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const keys = Object.keys(accountStatusMap || {});
    if (keys.length === 0) return;
    try {
      sessionStorage.setItem(DASHBOARD_STATUS_CACHE_KEY, JSON.stringify(accountStatusMap));
    } catch {
      // ignore storage write errors
    }
  }, [accountStatusMap]);

  useEffect(() => {
    if (!token || !dataLoaded || statusCheckedRef.current) return;

    if (accounts.length === 0) {
      statusCheckedRef.current = true;
      setAccountStatusMap({});
      if (typeof window !== "undefined") {
        try {
          sessionStorage.setItem(DASHBOARD_STATUS_CHECKED_KEY, "1");
        } catch {
          // ignore storage write errors
        }
      }
      return;
    }

    if (!shouldRunStatusCheck()) {
      statusCheckedRef.current = true;
      return;
    }

    statusCheckedRef.current = true;
    let cancelled = false;

    void (async () => {
      await checkAccountStatusOnce(token, accounts);
      if (cancelled || typeof window === "undefined") return;
      try {
        sessionStorage.setItem(DASHBOARD_STATUS_CHECKED_KEY, "1");
      } catch {
        // ignore storage write errors
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [accounts, checkAccountStatusOnce, dataLoaded, shouldRunStatusCheck, token]);

  const getAccountTaskCount = (accountName: string) => {
    return tasks.filter(task => task.account_name === accountName).length;
  };

  const openAddDialog = () => {
    setReloginAccountName(null);
    setLoginMode("phone");
    setLoginData({ ...EMPTY_LOGIN_DATA });
    setShowAddDialog(true);
  };

  const parseChatCacheTtlMinutes = useCallback((value: string) => {
    const num = Number(value);
    if (!Number.isFinite(num) || num <= 0) return DEFAULT_CHAT_CACHE_TTL_MINUTES;
    return Math.floor(num);
  }, []);

  const handleStartLogin = async () => {
    if (!token) return;
    const trimmedAccountName = normalizeAccountName(loginData.account_name);
    if (!trimmedAccountName || !loginData.phone_number) {
      addToast(t("account_name_phone_required"), "error");
      return;
    }
    if (isDuplicateAccountName(trimmedAccountName, reloginAccountName)) {
      addToast(t("account_name_duplicate"), "error");
      return;
    }
    try {
      setLoading(true);
      const res = await startAccountLogin({
        phone_number: loginData.phone_number,
        account_name: trimmedAccountName,
        proxy: loginData.proxy || undefined,
        chat_cache_ttl_minutes: parseChatCacheTtlMinutes(loginData.chat_cache_ttl_minutes),
      });
      setLoginData({ ...loginData, account_name: trimmedAccountName, phone_code_hash: res.phone_code_hash });
      addToast(t("code_sent"), "success");
    } catch (err: any) {
      addToast(formatErrorMessage("send_code_failed", err), "error");
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyLogin = useCallback(async () => {
    if (!token) return;
    if (!loginData.phone_code) {
      addToast(t("login_code_required"), "error");
      return;
    }
    const trimmedAccountName = normalizeAccountName(loginData.account_name);
    if (!trimmedAccountName) {
      addToast(t("account_name_required"), "error");
      return;
    }
    if (isDuplicateAccountName(trimmedAccountName, reloginAccountName)) {
      addToast(t("account_name_duplicate"), "error");
      return;
    }
    try {
      setLoading(true);
      await verifyAccountLogin({
        account_name: trimmedAccountName,
        phone_number: loginData.phone_number,
        phone_code: loginData.phone_code,
        phone_code_hash: loginData.phone_code_hash,
        password: loginData.password || undefined,
        proxy: loginData.proxy || undefined,
        chat_cache_ttl_minutes: parseChatCacheTtlMinutes(loginData.chat_cache_ttl_minutes),
      });
      addToast(t("login_success"), "success");
      setAccountStatusMap((prev) => ({
        ...prev,
        [trimmedAccountName]: {
          account_name: trimmedAccountName,
          ok: true,
          status: "connected",
          message: "",
          code: "OK",
          checked_at: new Date().toISOString(),
          needs_relogin: false,
        },
      }));
      setReloginAccountName(null);
      setLoginData({ ...EMPTY_LOGIN_DATA });
      setShowAddDialog(false);
      loadData();
    } catch (err: any) {
      addToast(formatErrorMessage("verify_failed", err), "error");
    } finally {
      setLoading(false);
    }
  }, [
    token,
    loginData.account_name,
    loginData.phone_number,
    loginData.phone_code,
    loginData.phone_code_hash,
    loginData.password,
    loginData.proxy,
    loginData.chat_cache_ttl_minutes,
    addToast,
    formatErrorMessage,
    isDuplicateAccountName,
    loadData,
    normalizeAccountName,
    parseChatCacheTtlMinutes,
    reloginAccountName,
    t,
  ]);

  const handleDeleteAccount = async (name: string) => {
    if (!token) return;
    try {
      setLoading(true);
      await deleteAccount(name);
      addToast(t("account_deleted"), "success");
      setDeleteAccountName(null);
      loadData();
    } catch (err: any) {
      addToast(formatErrorMessage("delete_failed", err), "error");
    } finally {
      setLoading(false);
    }
  };

  const handleEditAccount = (acc: AccountInfo) => {
    setEditData({
      account_name: acc.name,
      remark: acc.remark || "",
      proxy: acc.proxy || "",
      chat_cache_ttl_minutes: String(acc.chat_cache_ttl_minutes || DEFAULT_CHAT_CACHE_TTL_MINUTES),
    });
    setShowEditDialog(true);
  };

  const handleSaveEdit = async () => {
    if (!token) return;
    if (!editData.account_name) return;
    try {
      setLoading(true);
      await updateAccount(editData.account_name, {
        remark: editData.remark || "",
        proxy: editData.proxy || "",
        chat_cache_ttl_minutes: parseChatCacheTtlMinutes(editData.chat_cache_ttl_minutes),
      });
      addToast(t("save_changes"), "success");
      setShowEditDialog(false);
      loadData();
    } catch (err: any) {
      addToast(formatErrorMessage("save_failed", err), "error");
    } finally {
      setLoading(false);
    }
  };

  const debugQr = useCallback((payload: Record<string, any>) => {
    if (process.env.NODE_ENV !== "production") {
      // eslint-disable-next-line no-console
      console.debug("[qr-login]", payload);
    }
  }, []);

  const clearQrPollingTimers = useCallback(() => {
    if (qrPollTimerRef.current) {
      clearInterval(qrPollTimerRef.current);
      qrPollTimerRef.current = null;
    }
    if (qrPollDelayRef.current) {
      clearTimeout(qrPollDelayRef.current);
      qrPollDelayRef.current = null;
    }
    qrPollingActiveRef.current = false;
  }, []);

  const clearQrCountdownTimer = useCallback(() => {
    if (qrCountdownTimerRef.current) {
      clearInterval(qrCountdownTimerRef.current);
      qrCountdownTimerRef.current = null;
    }
  }, []);

  const clearQrTimers = useCallback(() => {
    clearQrPollingTimers();
    clearQrCountdownTimer();
  }, [clearQrPollingTimers, clearQrCountdownTimer]);

  const setQrPhaseSafe = useCallback((next: QrPhase, reason: string, extra?: Record<string, any>) => {
    setQrPhase((prev) => {
      if (prev !== next) {
        debugQr({
          login_id: qrActiveLoginIdRef.current,
          prev,
          next,
          reason,
          ...extra,
        });
      }
      return next;
    });
  }, [debugQr]);

  const markToastShown = useCallback((loginId: string, kind: "expired" | "error") => {
    if (!loginId) return;
    if (!qrToastShownRef.current[loginId]) {
      qrToastShownRef.current[loginId] = {};
    }
    qrToastShownRef.current[loginId][kind] = true;
  }, []);

  const hasToastShown = useCallback((loginId: string, kind: "expired" | "error") => {
    if (!loginId) return false;
    return Boolean(qrToastShownRef.current[loginId]?.[kind]);
  }, []);

  const resetQrState = useCallback(() => {
    clearQrTimers();
    qrActiveLoginIdRef.current = null;
    qrRestartingRef.current = false;
    qrAutoRefreshRef.current = 0;
    setQrLogin(null);
    setQrStatus("waiting_scan");
    setQrPhase("idle");
    setQrMessage("");
    setQrCountdown(0);
    setQrLoading(false);
    setQrPassword("");
    setQrPasswordLoading(false);
  }, [clearQrTimers]);

  const openReloginDialog = useCallback((acc: AccountInfo) => {
    resetQrState();
    setReloginAccountName(acc.name);
    setLoginMode("phone");
    setLoginData({
      ...EMPTY_LOGIN_DATA,
      account_name: acc.name,
      proxy: acc.proxy || "",
    });
    setShowAddDialog(true);
    addToast(t("account_relogin_required"), "error");
  }, [addToast, resetQrState, t]);

  const handleAccountCardClick = useCallback((acc: AccountInfo) => {
    const statusInfo = accountStatusMap[acc.name];
    if (statusInfo?.needs_relogin) {
      openReloginDialog(acc);
      return;
    }
    router.push(`/dashboard/account-tasks?name=${acc.name}`);
  }, [accountStatusMap, openReloginDialog, router]);

  const performQrLoginStart = useCallback(async (options?: { autoRefresh?: boolean; silent?: boolean; reason?: string }) => {
    if (!token) return null;
    const trimmedAccountName = normalizeAccountName(loginData.account_name);
    if (!trimmedAccountName) {
      if (!options?.silent) {
        addToast(t("account_name_required"), "error");
      }
      return null;
    }
    if (isDuplicateAccountName(trimmedAccountName, reloginAccountName)) {
      if (!options?.silent) {
        addToast(t("account_name_duplicate"), "error");
      }
      return null;
    }
    try {
      if (options?.autoRefresh) {
        qrRestartingRef.current = true;
      }
      clearQrTimers();
      setQrLoading(true);
      setQrPhaseSafe("loading", options?.reason ?? "start");
      const res = await startQrLogin({
        account_name: trimmedAccountName,
        proxy: loginData.proxy || undefined,
        chat_cache_ttl_minutes: parseChatCacheTtlMinutes(loginData.chat_cache_ttl_minutes),
      });
      setLoginData((prev) => ({ ...prev, account_name: trimmedAccountName }));
      setQrLogin(res);
      qrActiveLoginIdRef.current = res.login_id;
      qrToastShownRef.current[res.login_id] = {};
      setQrStatus("waiting_scan");
      setQrPhaseSafe("ready", "qr_ready", { expires_at: res.expires_at });
      setQrMessage("");
      return res;
    } catch (err: any) {
      setQrPhaseSafe("error", "start_failed");
      if (!options?.silent) {
        addToast(formatErrorMessage("qr_create_failed", err), "error");
      }
      return null;
    } finally {
      setQrLoading(false);
      qrRestartingRef.current = false;
    }
  }, [
    token,
    loginData.account_name,
    loginData.proxy,
    loginData.chat_cache_ttl_minutes,
    addToast,
    clearQrTimers,
    formatErrorMessage,
    isDuplicateAccountName,
    normalizeAccountName,
    parseChatCacheTtlMinutes,
    reloginAccountName,
    setQrPhaseSafe,
    t,
  ]);

  const handleSubmitQrPassword = useCallback(async (passwordOverride?: string) => {
    if (!token || !qrLogin?.login_id) return;
    const passwordValue = passwordOverride ?? qrPasswordRef.current;
    if (!passwordValue) {
      const msg = t("qr_password_missing");
      addToast(msg, "error");
      setQrMessage(msg);
      return;
    }
    try {
      setQrPasswordLoading(true);
      await submitQrPassword({
        login_id: qrLogin.login_id,
        password: passwordValue,
      });
      addToast(t("login_success"), "success");
      const doneAccount = normalizeAccountName(loginData.account_name);
      if (doneAccount) {
        setAccountStatusMap((prev) => ({
          ...prev,
          [doneAccount]: {
            account_name: doneAccount,
            ok: true,
            status: "connected",
            message: "",
            code: "OK",
            checked_at: new Date().toISOString(),
            needs_relogin: false,
          },
        }));
      }
      setReloginAccountName(null);
      setLoginData({ ...EMPTY_LOGIN_DATA });
      resetQrState();
      setShowAddDialog(false);
      loadData();
    } catch (err: any) {
      const errMsg = err?.message ? String(err.message) : "";
      const fallback = formatErrorMessage("qr_login_failed", err);
      let message = errMsg || fallback;
      const lowerMsg = errMsg.toLowerCase();
      if (errMsg.includes("瀵嗙爜閿欒") || errMsg.includes("涓ゆ楠岃瘉") || lowerMsg.includes("2fa")) {
        message = t("qr_password_invalid");
      }
      addToast(message, "error");
      if (message === t("qr_password_invalid")) {
        resetQrState();
        return;
      }
      setQrMessage(message);
    } finally {
      setQrPasswordLoading(false);
    }
  }, [
    token,
    qrLogin?.login_id,
    addToast,
    resetQrState,
    loadData,
    t,
    formatErrorMessage,
    loginData.account_name,
    normalizeAccountName,
  ]);

  const startQrPolling = useCallback((loginId: string, reason: string = "effect") => {
    if (!token || !loginId) return;
    if (loginMode !== "qr" || !showAddDialog) return;
    if (qrPollingActiveRef.current && qrActiveLoginIdRef.current === loginId) {
      debugQr({ login_id: loginId, poll: "skip", reason });
      return;
    }

    clearQrPollingTimers();
    qrActiveLoginIdRef.current = loginId;
    qrPollingActiveRef.current = true;
    qrPollSeqRef.current += 1;
    const seq = qrPollSeqRef.current;
    let stopped = false;

    const stopPolling = () => {
      if (stopped) return;
      stopped = true;
      clearQrPollingTimers();
    };

    const shouldAutoRefresh = () => {
      const now = Date.now();
      if (now - qrAutoRefreshRef.current < 1200) {
        return false;
      }
      qrAutoRefreshRef.current = now;
      return true;
    };

    const poll = async () => {
      try {
        if (qrRestartingRef.current) return;
        const res = await getQrLoginStatus(loginId);
        if (stopped) return;
        if (qrActiveLoginIdRef.current !== loginId) return;
        if (qrPollSeqRef.current !== seq) return;

        const status = res.status as "waiting_scan" | "scanned_wait_confirm" | "password_required" | "success" | "expired" | "failed";
        debugQr({ login_id: loginId, pollResult: status, message: res.message || "" });
        setQrStatus(status);
        if (status !== "password_required") {
          setQrMessage("");
        }
        if (res.expires_at) {
          setQrLogin((prev) => (prev ? { ...prev, expires_at: res.expires_at } : prev));
        }

        if (status === "success") {
          setQrPhaseSafe("success", "poll_success", { status });
          addToast(t("login_success"), "success");
          const doneAccount = normalizeAccountName(loginData.account_name);
          if (doneAccount) {
            setAccountStatusMap((prev) => ({
              ...prev,
              [doneAccount]: {
                account_name: doneAccount,
                ok: true,
                status: "connected",
                message: "",
                code: "OK",
                checked_at: new Date().toISOString(),
                needs_relogin: false,
              },
            }));
          }
          setReloginAccountName(null);
          setLoginData({ ...EMPTY_LOGIN_DATA });
          stopPolling();
          resetQrState();
          setShowAddDialog(false);
          loadData();
          return;
        }

        if (status === "password_required") {
          setQrPhaseSafe("password", "poll_password_required", { status });
          stopPolling();
          setQrMessage(t("qr_password_required"));
          return;
        }

        if (status === "scanned_wait_confirm") {
          setQrPhaseSafe("scanning", "poll_scanned", { status });
          return;
        }

        if (status === "waiting_scan") {
          setQrPhaseSafe("ready", "poll_waiting", { status });
          return;
        }

        if (status === "expired") {
          stopPolling();
          setQrPhaseSafe("loading", "auto_refresh", { status });
          if (!shouldAutoRefresh()) {
            return;
          }
          const refreshed = await performQrLoginStart({
            autoRefresh: true,
            silent: true,
            reason: "auto_refresh",
          });
          if (refreshed?.login_id) {
            startQrPolling(refreshed.login_id, "auto_refresh");
            return;
          }
          setQrPhaseSafe("expired", "auto_refresh_failed", { status });
          if (!hasToastShown(loginId, "expired")) {
            addToast(t("qr_expired_not_found"), "error");
            markToastShown(loginId, "expired");
          }
          return;
        }

        if (status === "failed") {
          setQrPhaseSafe("error", "poll_terminal", { status });
          stopPolling();
          if (!hasToastShown(loginId, "error")) {
            addToast(t("qr_login_failed"), "error");
            markToastShown(loginId, "error");
          }
        }
      } catch (err: any) {
        if (stopped) return;
        if (qrActiveLoginIdRef.current !== loginId) return;
        if (qrPollSeqRef.current !== seq) return;
        debugQr({ login_id: loginId, pollError: err?.message || String(err) });
        if (!hasToastShown(loginId, "error")) {
          addToast(formatErrorMessage("qr_status_failed", err), "error");
          markToastShown(loginId, "error");
        }
      }
    };

    qrPollDelayRef.current = setTimeout(() => {
      poll();
      qrPollTimerRef.current = setInterval(poll, 1500);
    }, 0);

    return stopPolling;
  }, [
    token,
    loginMode,
    showAddDialog,
    addToast,
    clearQrPollingTimers,
    debugQr,
    formatErrorMessage,
    hasToastShown,
    loadData,
    markToastShown,
    loginData.account_name,
    normalizeAccountName,
    performQrLoginStart,
    resetQrState,
    setQrPhaseSafe,
    t,
  ]);

  const handleStartQrLogin = async () => {
    const res = await performQrLoginStart();
    if (res?.login_id) {
      startQrPolling(res.login_id, "start_success");
    }
  };

  const handleCancelQrLogin = async () => {
    if (!token || !qrLogin?.login_id) {
      resetQrState();
      return;
    }
    try {
      setQrLoading(true);
      await cancelQrLogin(qrLogin.login_id);
    } catch (err: any) {
      addToast(formatErrorMessage("cancel_failed", err), "error");
    } finally {
      setQrLoading(false);
      resetQrState();
    }
  };


  // 手动提交 2FA（避免自动重试导致重复请求）

  const handleCloseAddDialog = () => {
    if (qrLogin?.login_id) {
      handleCancelQrLogin();
    }
    setReloginAccountName(null);
    setLoginData({ ...EMPTY_LOGIN_DATA });
    setLoginMode("phone");
    setShowAddDialog(false);
  };

  const handleShowLogs = async (name: string) => {
    if (!token) return;
    setLogsAccountName(name);
    setShowLogsDialog(true);
    setLogsLoading(true);
    try {
      const logs = await getAccountLogs(name, 100);
      setAccountLogs(logs);
    } catch (err: any) {
      addToast(formatErrorMessage("logs_fetch_failed", err), "error");
    } finally {
      setLogsLoading(false);
    }
  };

  const handleClearLogs = async () => {
    if (!token || !logsAccountName) return;
    try {
      setLoading(true);
      await clearAccountLogs(logsAccountName);
      addToast(t("clear_logs_success"), "success");
      setShowClearLogsDialog(false);
      setLogsLoading(true);
      const logs = await getAccountLogs(logsAccountName, 100);
      setAccountLogs(logs);
    } catch (err: any) {
      addToast(formatErrorMessage("clear_logs_failed", err), "error");
    } finally {
      setLogsLoading(false);
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!qrLogin?.expires_at || !qrActiveLoginIdRef.current) {
      setQrCountdown(0);
      clearQrTimers();
      return;
    }
    if (!(qrPhase === "ready" || qrPhase === "scanning")) {
      setQrCountdown(0);
      if (qrCountdownTimerRef.current) {
        clearInterval(qrCountdownTimerRef.current);
        qrCountdownTimerRef.current = null;
      }
      return;
    }
    const update = () => {
      const expires = new Date(qrLogin.expires_at).getTime();
      const diff = Math.max(0, Math.floor((expires - Date.now()) / 1000));
      setQrCountdown(diff);
    };
    update();
    if (qrCountdownTimerRef.current) {
      clearInterval(qrCountdownTimerRef.current);
    }
    qrCountdownTimerRef.current = setInterval(update, 1000);
    return () => {
      if (qrCountdownTimerRef.current) {
        clearInterval(qrCountdownTimerRef.current);
        qrCountdownTimerRef.current = null;
      }
    };
  }, [qrLogin?.expires_at, qrPhase, clearQrTimers]);

  useEffect(() => {
    if (!token || !qrLogin?.login_id || loginMode !== "qr" || !showAddDialog) return;
    if (qrPhase === "success" || qrPhase === "expired" || qrPhase === "error" || qrPhase === "password") return;
    if (qrRestartingRef.current) return;
    const stop = startQrPolling(qrLogin.login_id, "effect");
    return () => {
      if (stop) stop();
    };
  }, [token, qrLogin?.login_id, loginMode, showAddDialog, qrPhase, startQrPolling]);

  if (!token || checking) {
    return <PageLoading fullScreen message={t("loading")} />;
  }

  const connectedAccounts = accounts.filter((acc) => {
    const statusInfo = accountStatusMap[acc.name];
    const status = statusInfo?.status || "checking";
    return status === "connected" || status === "valid";
  }).length;
  const pendingAccounts = Math.max(0, accounts.length - connectedAccounts);
  const summaryItems = [
    {
      label: language === "zh" ? "账号总数" : "Accounts",
      value: accounts.length,
    },
    {
      label: t("connected"),
      value: connectedAccounts,
    },
    {
      label: language === "zh" ? "待处理" : "Pending",
      value: pendingAccounts,
    },
  ];

  return (
    <DashboardFrame
      title={
        <span className="inline-flex items-center gap-3">
          <span className="inline-flex h-10 w-10 items-center justify-center rounded-2xl bg-[var(--accent)] text-white shadow-sm">
            <Lightning weight="fill" size={20} />
          </span>
          <span className="nav-title font-bold tracking-tight text-lg">TG Sign Plus</span>
        </span>
      }
      toasts={toasts}
      removeToast={removeToast}
      showThemeLanguageToggle={false}
      actions={
        <div className="flex items-center gap-1 sm:gap-2">
          <ThemeLanguageToggle />
          <IconButton aria-label={t("sidebar_settings")} title={t("sidebar_settings")} onClick={() => router.push("/dashboard/settings")}>
            <Gear weight="bold" size={18} />
          </IconButton>
          <IconButton aria-label={t("logout")} title={t("logout")} onClick={logout} danger>
            <SignOut weight="bold" size={18} />
          </IconButton>
        </div>
      }

    >
      {loading && accounts.length === 0 ? (
        <PageLoading message={t("loading")} />
      ) : accounts.length === 0 ? (
        <div className="mx-auto flex w-full max-w-[1200px] flex-1 items-center px-4 py-6 sm:px-6 sm:py-10">
          <div className="grid w-full items-center gap-8 lg:grid-cols-[minmax(0,1fr)_420px] lg:gap-12">
            <section className="hidden lg:block">
              <div className="max-w-[520px]">
                <div className="inline-flex h-16 w-16 items-center justify-center rounded-[24px] bg-[var(--accent)] text-white shadow-[var(--shadow-lg)]">
                  <Lightning weight="fill" size={32} />
                </div>
                <h2 className="mt-6 text-4xl font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  {language === "zh" ? "账号工作台" : "Account workspace"}
                </h2>
                <p className="mt-4 max-w-[460px] text-base leading-7 text-[var(--text-secondary)]">
                  {language === "zh"
                    ? "添加 Telegram 账号后，即可进入对应工作台管理任务、日志与登录状态。"
                    : "Add a Telegram account to manage tasks, logs, and login state in its workspace."}
                </p>
              </div>
            </section>

            <section className="w-full">
              <div className="glass-panel mx-auto w-full max-w-[420px] p-5 sm:p-8">
                <div className="mb-6 lg:hidden">
                  <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--accent)] text-white shadow-sm">
                    <Lightning weight="fill" size={24} />
                  </div>
                  <h2 className="mt-4 text-[26px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                    {language === "zh" ? "账号工作台" : "Account workspace"}
                  </h2>
                </div>
                <EmptyState
                  icon={<Plus size={32} weight="bold" />}
                  title={t("add_account")}
                  description={language === "zh" ? "先接入一个 Telegram 账号，才能继续管理任务。" : "Add a Telegram account before managing tasks."}
                  onClick={openAddDialog}
                />
              </div>
            </section>
          </div>
        </div>
      ) : (
        <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8">
          <section className="glass-panel overflow-hidden">
            <div className="px-5 py-5 sm:px-6 sm:py-6">
              <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">
                {language === "zh" ? "Dashboard" : "Dashboard"}
              </div>
              <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-[var(--text-primary)] sm:text-[30px]">
                {language === "zh" ? "账号管理" : "Account management"}
              </h2>
              <div className="mt-3 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div className="flex flex-wrap items-center gap-2">
                  {summaryItems.map((item) => (
                    <div
                      key={item.label}
                      className="rounded-full border border-[var(--border-primary)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-secondary)]"
                    >
                      <span className="font-semibold text-[var(--text-primary)]">{item.value}</span>
                      <span className="ml-2">{item.label}</span>
                    </div>
                  ))}
                </div>
                <Button className="shrink-0 self-start lg:self-auto" onClick={openAddDialog}>
                  <Plus weight="bold" size={14} />
                  {t("add_account")}
                </Button>
              </div>
            </div>
          </section>

          <section className="space-y-4">
            <div>
              <h3 className="text-lg font-semibold tracking-tight text-[var(--text-primary)]">
                {language === "zh" ? "账号列表" : "Account list"}
              </h3>
            </div>

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {accounts.map((acc) => {
                const initial = acc.name.charAt(0).toUpperCase();
                const statusInfo = accountStatusMap[acc.name];
                const status = statusInfo?.status || "checking";
                const isInvalid = status === "invalid" || Boolean(statusInfo?.needs_relogin);
                const isCheckingLike = status === "checking" || (status === "error" && !statusInfo?.needs_relogin);
                const statusKey = (() => {
                  const currentStatus = statusInfo?.status || "connected";
                  const isCheckingOrError = currentStatus === "checking" || (currentStatus === "error" && !statusInfo?.needs_relogin);
                  return (currentStatus === "connected" || currentStatus === "valid")
                    ? "connected"
                    : isCheckingOrError
                      ? "account_status_checking"
                      : "account_status_invalid";
                })();

                return (
                  <div key={acc.name} className="glass-panel p-5 sm:p-6">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0 flex items-center gap-3">
                        <div className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[var(--accent)] text-sm font-bold text-white shadow-sm">
                          {initial}
                        </div>
                        <div className="min-w-0">
                          <div className="truncate text-lg font-semibold tracking-tight text-[var(--text-primary)]">{acc.name}</div>
                          {acc.remark ? (
                            <div className="mt-1 truncate text-sm text-[var(--text-tertiary)]">{acc.remark}</div>
                          ) : null}
                        </div>
                      </div>
                      <StatusBadge tone={isInvalid ? "danger" : isCheckingLike ? "warning" : "success"}>
                        {statusKey === "account_status_checking" ? (
                          <span className="inline-flex items-center gap-1.5">
                            <Spinner className="animate-spin" size={12} />
                            {t(statusKey)}
                          </span>
                        ) : (
                          t(statusKey)
                        )}
                      </StatusBadge>
                    </div>

                    <div className="mt-5 flex items-center justify-between gap-3 rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] px-4 py-3">
                      <div>
                        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">
                          {language === "zh" ? "任务数量" : "Tasks"}
                        </div>
                        <div className="mt-1 text-xl font-semibold tracking-tight text-[var(--text-primary)]">
                          {getAccountTaskCount(acc.name)}
                        </div>
                      </div>
                      <div className="text-right text-xs text-[var(--text-secondary)]">
                        {language === "zh" ? "进入工作台后继续管理任务和日志" : "Open workspace to manage tasks and logs"}
                      </div>
                    </div>

                    <div className="mt-5 flex items-center justify-between gap-3 border-t border-[var(--border-secondary)] pt-4">
                      <Button variant="secondary" size="sm" onClick={() => handleAccountCardClick(acc)}>
                        {language === "zh" ? "进入工作台" : "Open workspace"}
                      </Button>
                      <div className="flex items-center gap-1">
                        <IconButton
                          className="!h-8 !w-8"
                          aria-label={t("logs")}
                          title={t("logs")}
                          onClick={(e) => { e.stopPropagation(); handleShowLogs(acc.name); }}
                        >
                          <ListDashes weight="bold" size={16} />
                        </IconButton>
                        <IconButton
                          className="!h-8 !w-8"
                          aria-label={t("edit_account")}
                          title={t("edit_account")}
                          onClick={(e) => { e.stopPropagation(); handleEditAccount(acc); }}
                        >
                          <PencilSimple weight="bold" size={16} />
                        </IconButton>
                        <IconButton
                          className="!h-8 !w-8"
                          danger
                          aria-label={t("remove")}
                          title={t("remove")}
                          onClick={(e) => { e.stopPropagation(); setDeleteAccountName(acc.name); }}
                        >
                          <Trash weight="bold" size={16} />
                        </IconButton>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      )}

      <ModalShell
        open={showAddDialog}
        title={reloginAccountName ? t("relogin_account") : t("add_account")}
        onClose={handleCloseAddDialog}
        className="max-w-[420px]"
      >
        <div className="animate-float-up space-y-4">
              <div className="flex gap-2">
                <Button
                  variant={loginMode === "phone" ? "default" : "secondary"}
                  size="sm"
                  className="flex-1"
                  onClick={() => {
                    if (loginMode !== "phone" && qrLogin?.login_id) {
                      handleCancelQrLogin();
                    }
                    setLoginMode("phone");
                  }}
                >
                  {t("login_method_phone")}
                </Button>
                <Button
                  variant={loginMode === "qr" ? "default" : "secondary"}
                  size="sm"
                  className="flex-1"
                  onClick={() => setLoginMode("qr")}
                >
                  {t("login_method_qr")}
                </Button>
              </div>

              {loginMode === "phone" ? (
                <>
                  <div className="space-y-4">
                    <FormField label={t("session_name")} htmlFor="account-name-input">
                      <Input
                        id="account-name-input"
                        type="text"
                        className="h-11"
                        placeholder={t("account_name_placeholder")}
                        value={loginData.account_name}
                        onChange={(e) => {
                          const cleaned = sanitizeAccountName(e.target.value);
                          setLoginData({ ...loginData, account_name: cleaned });
                        }}
                      />
                    </FormField>

                    <FormField label={t("phone_number")} htmlFor="phone-number-input">
                      <Input
                        id="phone-number-input"
                        type="text"
                        className="h-11"
                        placeholder={t("phone_number_placeholder")}
                        value={loginData.phone_number}
                        onChange={(e) => setLoginData({ ...loginData, phone_number: e.target.value })}
                      />
                    </FormField>

                    <FormField label={t("login_code")} htmlFor="phone-code-input">
                      <div className="input-group">
                        <Input
                          id="phone-code-input"
                          type="text"
                          className="h-11"
                          placeholder={t("login_code_placeholder")}
                          value={loginData.phone_code}
                          onChange={(e) => setLoginData({ ...loginData, phone_code: e.target.value })}
                        />
                        <IconButton onClick={handleStartLogin} disabled={loading} aria-label={t("send_code")} title={t("send_code")} activeTone="primary">
                          {loading ? <Spinner className="animate-spin" size={16} /> : <PaperPlaneRight weight="bold" />}
                        </IconButton>
                      </div>
                    </FormField>

                    <FormField label={t("two_step_pass")} htmlFor="password-input">
                      <Input
                        id="password-input"
                        type="password"
                        className="h-11"
                        placeholder={t("two_step_placeholder")}
                        value={loginData.password}
                        onChange={(e) => setLoginData({ ...loginData, password: e.target.value })}
                      />
                    </FormField>

                    <FormField label={t("proxy")} htmlFor="proxy-input">
                      <Input
                        id="proxy-input"
                        type="text"
                        className="h-11"
                        placeholder={t("proxy_placeholder")}
                        value={loginData.proxy}
                        onChange={(e) => setLoginData({ ...loginData, proxy: e.target.value })}
                      />
                    </FormField>

                    <FormField label="Chat 列表缓存失效时间（分钟）" htmlFor="chat-cache-ttl-input">
                      <Input
                        id="chat-cache-ttl-input"
                        type="number"
                        min={1}
                        className="h-11"
                        value={loginData.chat_cache_ttl_minutes}
                        onChange={(e) => setLoginData({ ...loginData, chat_cache_ttl_minutes: e.target.value })}
                      />
                    </FormField>
                  </div>

                  <div className="mt-6 flex gap-3">
                    <Button variant="secondary" className="flex-1" onClick={handleCloseAddDialog}>{t("cancel")}</Button>
                    <Button
                      className="flex-1"
                      onClick={handleVerifyLogin}
                      disabled={loading || !loginData.phone_code.trim()}
                    >
                      {loading ? <Spinner className="animate-spin" /> : t("confirm_connect")}
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <div className="space-y-4">
                    <FormField label={t("session_name")} htmlFor="qr-account-name-input">
                      <Input
                        id="qr-account-name-input"
                        type="text"
                        className="h-11"
                        placeholder={t("account_name_placeholder")}
                        value={loginData.account_name}
                        onChange={(e) => {
                          const cleaned = sanitizeAccountName(e.target.value);
                          setLoginData({ ...loginData, account_name: cleaned });
                        }}
                      />
                    </FormField>

                    <FormField label={t("two_step_pass")} htmlFor="qr-password-input">
                      <Input
                        id="qr-password-input"
                        type="password"
                        className="h-11"
                        placeholder={t("two_step_placeholder")}
                        value={qrPassword}
                        onChange={(e) => setQrPassword(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key !== "Enter") return;
                          if (qrPhase !== "password") return;
                          if (!qrPassword || qrPasswordLoading) return;
                          e.preventDefault();
                          handleSubmitQrPassword(qrPassword);
                        }}
                      />
                    </FormField>

                    <FormField label={t("proxy")} htmlFor="qr-proxy-input">
                      <Input
                        id="qr-proxy-input"
                        type="text"
                        className="h-11"
                        placeholder={t("proxy_placeholder")}
                        value={loginData.proxy}
                        onChange={(e) => setLoginData({ ...loginData, proxy: e.target.value })}
                      />
                    </FormField>

                    <FormField label="Chat 列表缓存失效时间（分钟）" htmlFor="qr-chat-cache-ttl-input">
                      <Input
                        id="qr-chat-cache-ttl-input"
                        type="number"
                        min={1}
                        className="h-11"
                        value={loginData.chat_cache_ttl_minutes}
                        onChange={(e) => setLoginData({ ...loginData, chat_cache_ttl_minutes: e.target.value })}
                      />
                    </FormField>
                  </div>

                  <div className="glass-panel !bg-[var(--bg-tertiary)] p-4 rounded-xl space-y-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-xs text-[var(--text-secondary)]">{t("qr_tip")}</div>
                      <Button
                        variant="secondary"
                        size="sm"
                        className="h-8"
                        onClick={handleStartQrLogin}
                        disabled={qrLoading}
                      >
                        {qrLoading ? <Spinner className="animate-spin" /> : (qrLogin ? t("qr_refresh") : t("qr_start"))}
                      </Button>
                    </div>
                    <div className="flex items-center justify-center">
                      {qrLogin?.qr_image ? (
                        <Image src={qrLogin.qr_image} alt={t("qr_alt")} width={160} height={160} className="rounded-lg bg-white p-2" />
                      ) : (
                        <div className="w-40 h-40 rounded-lg bg-[var(--bg-tertiary)] flex items-center justify-center text-xs text-[var(--text-tertiary)]">
                          {t("qr_start")}
                        </div>
                      )}
                    </div>
                    {qrLogin && (qrPhase === "ready" || qrPhase === "scanning") ? (
                      <div className="text-[11px] text-[var(--text-tertiary)] font-mono text-center">
                        {t("qr_expires_in").replace("{seconds}", qrCountdown.toString())}
                      </div>
                    ) : null}
                    <div className="text-xs text-center font-bold">
                      {(qrPhase === "loading" || qrPhase === "ready") && t("qr_waiting")}
                      {qrPhase === "scanning" && t("qr_scanned")}
                      {qrPhase === "password" && t("qr_password_required")}
                      {qrPhase === "success" && t("qr_success")}
                      {qrPhase === "expired" && t("qr_expired")}
                      {qrPhase === "error" && t("qr_failed")}
                    </div>
                    {qrMessage ? (
                      <div className="text-[11px] text-rose-400 text-center">{qrMessage}</div>
                    ) : null}
                  </div>

                  <div className="mt-2 flex gap-3">
                    <Button
                      variant="secondary"
                      className="flex-1"
                      onClick={handleCloseAddDialog}
                    >
                      {t("cancel")}
                    </Button>
                    <Button
                      className="flex-1"
                      onClick={() => handleSubmitQrPassword(qrPassword)}
                      disabled={qrPhase !== "password" || !qrPassword || qrPasswordLoading}
                    >
                      {qrPasswordLoading ? <Spinner className="animate-spin" /> : t("confirm_connect")}
                    </Button>
                  </div>
                </>
              )}
            </div>
      </ModalShell>

      <ModalShell
        open={showEditDialog}
        title={t("edit_account")}
        onClose={() => setShowEditDialog(false)}
        className="max-w-[420px]"
        footer={
          <div className="flex gap-3">
            <Button variant="secondary" className="flex-1" onClick={() => setShowEditDialog(false)}>{t("cancel")}</Button>
            <Button className="flex-1" onClick={handleSaveEdit} disabled={loading}>
              {loading ? <Spinner className="animate-spin" /> : t("save")}
            </Button>
          </div>
        }
      >
        <div className="animate-float-up space-y-4">
          <FormField label={t("session_name")} htmlFor="edit-account-name">
            <Input
              id="edit-account-name"
              type="text"
              className="h-11"
              value={editData.account_name}
              disabled
            />
          </FormField>

          <FormField label={t("remark")} htmlFor="edit-remark">
            <Input
              id="edit-remark"
              type="text"
              className="h-11"
              placeholder={t("remark_placeholder")}
              value={editData.remark}
              onChange={(e) => setEditData({ ...editData, remark: e.target.value })}
            />
          </FormField>

          <FormField label={t("proxy")} htmlFor="edit-proxy">
            <Input
              id="edit-proxy"
              type="text"
              className="h-11"
              placeholder={t("proxy_placeholder")}
              value={editData.proxy}
              onChange={(e) => setEditData({ ...editData, proxy: e.target.value })}
            />
          </FormField>

          <FormField label="Chat 列表缓存失效时间（分钟）" htmlFor="edit-chat-cache-ttl">
            <Input
              id="edit-chat-cache-ttl"
              type="number"
              min={1}
              className="h-11"
              value={editData.chat_cache_ttl_minutes}
              onChange={(e) => setEditData({ ...editData, chat_cache_ttl_minutes: e.target.value })}
            />
          </FormField>
        </div>
      </ModalShell>

      <ModalShell
        open={showLogsDialog}
        title={`${logsAccountName} ${t("running_logs")}`}
        onClose={() => setShowLogsDialog(false)}
        className="max-w-[52rem]"
        contentClassName="max-h-[78vh] overflow-y-auto bg-[var(--bg-secondary)] p-4 font-mono text-[12px] leading-6 custom-scrollbar md:p-5"
        footer={
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="rounded-full border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] px-3 py-1 text-[11px] font-medium text-[var(--text-secondary)]">
              {t("logs_summary")
                .replace("{count}", accountLogs.length.toString())
                .replace("{days}", "3")}
            </div>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              {accountLogs.length > 0 && (
                <Button variant="destructive" size="sm" onClick={() => setShowClearLogsDialog(true)} disabled={loading}>
                  <Trash weight="bold" size={14} />
                  {t("clear_logs")}
                </Button>
              )}
              <Button variant="secondary" size="sm" onClick={() => setShowLogsDialog(false)}>
                {t("close")}
              </Button>
            </div>
          </div>
        }
      >
        {logsLoading ? (
          <div className="flex min-h-[220px] flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-[var(--border-secondary)] bg-[var(--bg-tertiary)] px-6 text-center text-[var(--text-tertiary)]">
            <Spinner className="animate-spin" size={16} />
            <div className="text-sm font-medium text-[var(--text-primary)]">{t("loading")}</div>
          </div>
        ) : accountLogs.length === 0 ? (
          <div className="flex min-h-[220px] items-center justify-center rounded-2xl border border-dashed border-[var(--border-secondary)] bg-[var(--bg-tertiary)] px-6 text-center text-sm text-[var(--text-tertiary)]">
            {t("no_logs")}
          </div>
        ) : (
          <div className="space-y-4">
            {accountLogs.map((log, i) => (
              <div key={i} className="overflow-hidden rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-secondary)] shadow-sm">
                <div className="flex flex-col gap-3 border-b border-[var(--border-secondary)] bg-[var(--bg-tertiary)] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="space-y-2">
                    <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
                      {new Date(log.created_at).toLocaleString()}
                    </div>
                    <div className="text-sm font-semibold text-[var(--text-primary)]">
                      {`${t("task_label")}：${log.task_name}${log.success ? t("task_exec_success") : t("task_exec_failed")}`}
                    </div>
                  </div>
                  <StatusBadge tone={log.success ? "success" : "danger"}>
                    {log.success ? t("success") : t("failure")}
                  </StatusBadge>
                </div>
                <div className="space-y-3 p-4 md:p-5">
                  {log.bot_message ? (
                    <div className="rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-primary)] px-3 py-2.5 text-[var(--text-secondary)] whitespace-pre-wrap break-words leading-relaxed md:max-w-[46rem]">
                      <span className="text-[var(--text-tertiary)]">{t("bot_reply")}：</span>
                      {log.bot_message}
                    </div>
                  ) : null}
                  {log.message && !["Success", "Failed", "执行成功", "执行失败"].includes(log.message.trim()) ? (
                    <pre className="rounded-2xl border border-dashed border-[var(--border-secondary)] bg-[var(--bg-primary)] px-3 py-3 whitespace-pre-wrap break-words leading-relaxed text-[var(--text-secondary)] overflow-x-auto md:max-w-[46rem]">
                      {log.message}
                    </pre>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </ModalShell>

      <ModalShell
        open={Boolean(deleteAccountName)}
        title={t("remove")}
        description={deleteAccountName ? t("confirm_delete_account").replace("{name}", deleteAccountName) : t("confirm_delete_account")}
        onClose={() => {
          if (!loading) {
            setDeleteAccountName(null);
          }
        }}
        className="max-w-md"
        footer={
          <div className="flex gap-3">
            <Button variant="secondary" className="flex-1" onClick={() => setDeleteAccountName(null)} disabled={loading}>
              {t("cancel")}
            </Button>
            <Button className="flex-1" onClick={() => deleteAccountName && handleDeleteAccount(deleteAccountName)} disabled={loading || !deleteAccountName}>
              {loading ? <Spinner className="animate-spin" /> : t("remove")}
            </Button>
          </div>
        }
      >
        <div className="text-sm text-[var(--text-secondary)]">{deleteAccountName || ""}</div>
      </ModalShell>

      <ModalShell
        open={showClearLogsDialog}
        title={t("clear_logs")}
        description={logsAccountName ? t("clear_logs_confirm").replace("{name}", logsAccountName) : t("clear_logs_confirm")}
        onClose={() => {
          if (!loading) {
            setShowClearLogsDialog(false);
          }
        }}
        className="max-w-md"
        footer={
          <div className="flex gap-3">
            <Button variant="secondary" className="flex-1" onClick={() => setShowClearLogsDialog(false)} disabled={loading}>
              {t("cancel")}
            </Button>
            <Button variant="destructive" className="flex-1" onClick={handleClearLogs} disabled={loading}>
              {loading ? <Spinner className="animate-spin" /> : t("clear_logs")}
            </Button>
          </div>
        }
      >
        <div className="text-sm text-[var(--text-secondary)]">{logsAccountName || ""}</div>
      </ModalShell>
    </DashboardFrame>
  );
}
