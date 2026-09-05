"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ensureAccessToken, logout } from "../../../lib/auth";
import { listSignTasks, deleteSignTask, runSignTask, getSignTaskHistory, getAccountChats, refreshAccountChats, searchAccountChats, createSignTask, updateSignTask, setSignTaskEnabled, exportSignTask, importSignTask, getSchedulerStatus, SignTask, SignTaskChat, SignTaskHistoryItem, ChatInfo, CreateSignTaskRequest, SchedulerStatus } from "../../../lib/api";
import { Plus, Trash, Spinner, ArrowClockwise, ListDashes, DotsThreeVertical, Robot, MathOperations, Copy, ClipboardText, Lightning, CaretLeft, Gear, SignOut } from "@phosphor-icons/react";
import { ToastContainer, useToast } from "../../../components/ui/toast";
import { PageLoading } from "../../../components/ui/page-loading";
import { EmptyState } from "../../../components/ui/empty-state";
import { IconButton } from "../../../components/ui/icon-button";
import { ModalShell } from "../../../components/ui/modal-shell";
import { FormField } from "../../../components/ui/form-field";
import { Input } from "../../../components/ui/input";
import { Button } from "../../../components/ui/button";
import { StatusBadge } from "../../../components/ui/status-badge";
import { ThemeLanguageToggle } from "../../../components/ThemeLanguageToggle";
import { AppFooter } from "../../../components/app-footer";
import { cn } from "../../../lib/utils";
import { useLanguage } from "../../../context/LanguageContext";

import { HistoryLogView, formatFlowDateTime, runSummaryStatusLabel, runSummaryTone, compactRunSummaryParts, getHistoryDiagnostics, formatHistoryForAi, formatHistoryRawJson, HistoryFlowGroups } from "./task-history";

import { TaskItem } from "./task-item";

import { ActionTypeOption, TaskFormAction, isSuccessAssertionAction, TaskFormState, defaultTaskAction, toSuccessKeywords, toTaskFormAction, DICE_OPTIONS } from "./task-form";

import { TaskAdvancedSettings } from "./task-advanced-settings";
import { chatToForm, formToChat, replaceEditedChat, findInvalidChatIndex } from "./task-form";

import { getNewRunResult } from "./task-history";

import { useTaskMonitor } from "./use-task-monitor";

const DAY_MS = 24 * 60 * 60 * 1000;

type TaskFilterKey = "all" | "enabled" | "disabled" | "success" | "failed" | "pending" | "unregistered";

export default function AccountTasksContent() {
    const router = useRouter();
    const { t, language } = useLanguage();
    const searchParams = useSearchParams();
    const accountName = searchParams.get("name") || "";
    const shouldOpenCreate = searchParams.get("new") === "1";
    const { toasts, addToast, removeToast } = useToast();
    const fieldLabelClass = "text-xs font-bold uppercase tracking-wider text-[var(--text-tertiary)] mb-1 block";
    const selectClassName = "flex h-10 w-full rounded-[12px] border border-[var(--border-primary)] bg-[var(--bg-secondary)] px-4 py-2 text-sm text-[var(--text-primary)] transition-all duration-150 focus-visible:outline-none focus-visible:border-[var(--accent)] focus-visible:ring-2 focus-visible:ring-[var(--accent-muted)] disabled:cursor-not-allowed disabled:opacity-50";
    const textareaClassName = "w-full rounded-[12px] border border-[var(--border-primary)] bg-[var(--bg-secondary)] px-4 py-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] transition-all duration-150 focus-visible:outline-none focus-visible:border-[var(--accent)] focus-visible:ring-2 focus-visible:ring-[var(--accent-muted)] disabled:cursor-not-allowed disabled:opacity-50";

    const [token, setLocalToken] = useState<string | null>(null);
    const [tasks, setTasks] = useState<SignTask[]>([]);
    const [chats, setChats] = useState<ChatInfo[]>([]);
    const [schedulerStatus, setSchedulerStatus] = useState<SchedulerStatus | null>(null);
    const [chatSearch, setChatSearch] = useState("");
    const [chatSearchResults, setChatSearchResults] = useState<ChatInfo[]>([]);
    const [chatSearchLoading, setChatSearchLoading] = useState(false);
    const [loading, setLoading] = useState(false);
    const [runningTaskName, setRunningTaskName] = useState<string | null>(null);
    const runHistoryBaseline = useRef<{ account: string; task: string; time: string | null | undefined } | null>(null);
    const [liveMonitorTaskName, setLiveMonitorTaskName] = useState<string | null>(null);
    const [refreshingChats, setRefreshingChats] = useState(false);
    const [chatCacheMeta, setChatCacheMeta] = useState<{ last_cached_at?: string | null; cache_ttl_minutes: number; expired: boolean; count: number } | null>(null);
    const [historyTaskName, setHistoryTaskName] = useState<string | null>(null);
    const [historyLogs, setHistoryLogs] = useState<SignTaskHistoryItem[]>([]);
    const [selectedHistoryIndex, setSelectedHistoryIndex] = useState(0);
    const [historyLogView, setHistoryLogView] = useState<HistoryLogView>("read");
    const [historyFailureOnly, setHistoryFailureOnly] = useState(false);
    const [historyExpandDetails, setHistoryExpandDetails] = useState(false);
    const [historyLoading, setHistoryLoading] = useState(false);
    const dialogActionsDisabled = loading || refreshingChats;

    const addToastRef = useRef(addToast);
    const tRef = useRef(t);
    const historyTaskNameRef = useRef<string | null>(null);
    const chatDialogLoadKeyRef = useRef<string | null>(null);
    useEffect(() => {
        addToastRef.current = addToast;
        tRef.current = t;
    }, [addToast, t]);

    useEffect(() => {
        historyTaskNameRef.current = historyTaskName;
    }, [historyTaskName]);

    const formatErrorMessage = useCallback((key: string, err?: any) => {
        const base = tRef.current ? tRef.current(key) : key;
        const code = err?.code;
        return code ? `${base} (${code})` : base;
    }, []);
    const handleAccountSessionInvalid = useCallback((err: any) => {
        if (err?.code !== "ACCOUNT_SESSION_INVALID") return false;
        const toast = addToastRef.current;
        const message = tRef.current
            ? tRef.current("account_session_invalid")
            : "Account session expired, please login again";
        if (toast) {
            toast(message, "error");
        }
        setTimeout(() => {
            router.replace("/dashboard");
        }, 800);
        return true;
    }, [router]);

    // 闂傚倷绀侀幉锛勬暜濡ゅ啰鐭欓柟瀵稿Х绾句粙鏌熼幆褜鍤熸い鈺冨厴閹綊宕堕妸銉хシ濡炪値鍋侀崐婵嬪箖濡ゅ懏鍋ㄦ繛鍫熷閺侇垶姊烘导娆戠暢婵☆偄瀚伴妴?
    const [showCreateDialog, setShowCreateDialog] = useState(false);
    const [newTask, setNewTask] = useState<TaskFormState>({
        name: "",
        sign_at: "0 6 * * *",
        random_minutes: 0,
        retry_count: 0,
        chat_id: 0,
        chat_id_manual: "",
        chat_name: "",
        actions: [defaultTaskAction()],
        delete_after: undefined,
        event_timeout: undefined,
        event_retries: undefined,
        event_retry_wait: undefined,
        event_history_limit: undefined,
        event_history_failure_threshold: undefined,
        event_history_rescue_interval: undefined,
        event_history_rpc_timeout: undefined,
        event_history_result_max_age: undefined,
        event_action_timeout: undefined,
        event_send_timeout: undefined,
        event_media_timeout: undefined,
        event_ai_timeout: undefined,
        event_callback_timeout: undefined,
        event_callback_retries: undefined,
        event_ai_fallback: undefined,
        execution_mode: "range",
        range_start: "09:00",
        range_end: "18:00",
    });

    // 缂傚倸鍊搁崐鎼佸磹瑜版帗鍋嬮柣鎰仛椤愯姤銇勯幇鍓佹偧妞も晝鍏橀幃褰掑炊閵娿儳绁峰銈庡亖閸婃繈骞冨Δ鍛仺婵炲牊瀵ч弫顖炴⒑娴兼瑧鐣虫俊顐㈠閵?
    const [showEditDialog, setShowEditDialog] = useState(false);
    const [editingChats, setEditingChats] = useState<SignTaskChat[]>([]);
    const [editingChatIndex, setEditingChatIndex] = useState(0);
    const [editingRandomSeconds, setEditingRandomSeconds] = useState(0);
    const [editingTaskName, setEditingTaskName] = useState("");
    const [editTask, setEditTask] = useState<TaskFormState>({
        sign_at: "0 6 * * *",
        random_minutes: 0,
        retry_count: 0,
        chat_id: 0,
        chat_id_manual: "",
        chat_name: "",
        actions: [defaultTaskAction()],
        delete_after: undefined,
        event_timeout: undefined,
        event_retries: undefined,
        event_retry_wait: undefined,
        event_history_limit: undefined,
        event_history_failure_threshold: undefined,
        event_history_rescue_interval: undefined,
        event_history_rpc_timeout: undefined,
        event_history_result_max_age: undefined,
        event_action_timeout: undefined,
        event_send_timeout: undefined,
        event_media_timeout: undefined,
        event_ai_timeout: undefined,
        event_callback_timeout: undefined,
        event_callback_retries: undefined,
        event_ai_fallback: undefined,
        execution_mode: "fixed",
        range_start: "09:00",
        range_end: "18:00",
    });
    const [copyTaskDialog, setCopyTaskDialog] = useState<{ taskName: string; config: string } | null>(null);
    const [showPasteDialog, setShowPasteDialog] = useState(false);
    const [pasteTaskConfigInput, setPasteTaskConfigInput] = useState("");
    const [copyingConfig, setCopyingConfig] = useState(false);
    const [importingPastedConfig, setImportingPastedConfig] = useState(false);
    const [deleteTaskName, setDeleteTaskName] = useState<string | null>(null);
    const [taskFilter, setTaskFilter] = useState<TaskFilterKey>("all");

    const [checking, setChecking] = useState(true);
    const isZh = language === "zh";
    const taskNamePlaceholder = isZh ? "\u7559\u7A7A\u4F7F\u7528\u9ED8\u8BA4\u540D\u79F0" : "Leave empty to use default name";
    const sendTextLabel = isZh ? "\u53D1\u9001\u6587\u672C\u6D88\u606F" : "Send Text Message";
    const clickTextButtonLabel = isZh ? "\u70B9\u51FB\u6587\u5B57\u6309\u94AE" : "Click Text Button";
    const sendDiceLabel = isZh ? "\u53D1\u9001\u9AB0\u5B50" : "Send Dice";
    const aiVisionLabel = isZh ? "AI\u8BC6\u56FE" : "AI Vision";
    const aiCalcLabel = isZh ? "AI\u8BA1\u7B97" : "AI Calculate";
    const aiPoetryLabel = isZh ? "AI\u586B\u8BD7" : "AI Poetry Fill";
    const assertSuccessLabel = isZh ? "\u6210\u529F\u5224\u5B9A" : "Success Assertion";
    const sendTextPlaceholder = isZh ? "\u53D1\u9001\u7684\u6587\u672C\u5185\u5BB9" : "Text to send";
    const clickButtonPlaceholder = isZh ? "\u8F93\u5165\u6309\u94AE\u6587\u5B57\uFF0C\u4E0D\u8981\u8868\u60C5\uFF01" : "Button text to click, no emoji";
    const assertSuccessPlaceholder = isZh ? "\u591A\u4E2A\u5173\u952E\u5B57\u7528 # \u5206\u9694" : "Separate keywords with #";
    const aiVisionSendModeLabel = isZh ? "\u8BC6\u56FE\u540E\u53D1\u6587\u672C" : "Vision -> Send Text";
    const aiVisionClickModeLabel = isZh ? "\u8BC6\u56FE\u540E\u70B9\u6309\u94AE" : "Vision -> Click Button";
    const aiVisionCaptionPatternPlaceholder = isZh ? "caption 正则，如：请输入验证码" : "Caption regex, e.g. captcha";
    const aiVisionCaptchaLengthsPlaceholder = isZh ? "长度，如：4 或 4,5" : "Lengths, e.g. 4 or 4,5";
    const aiVisionCaptchaCharsetPlaceholder = isZh ? "允许字符，如：A-Z0-9" : "Allowed chars, e.g. A-Z0-9";
    const aiCalcSendModeLabel = isZh ? "\u8BA1\u7B97\u540E\u53D1\u6587\u672C" : "Math -> Send Text";
    const aiCalcClickModeLabel = isZh ? "\u8BA1\u7B97\u540E\u70B9\u6309\u94AE" : "Math -> Click Button";
    const aiPoetryClickModeLabel = isZh ? "\u586B\u8BD7\u540E\u70B9\u6309\u94AE" : "Poetry Fill -> Click Button";
    const pasteTaskTitle = isZh ? "\u7C98\u8D34\u5BFC\u5165\u4EFB\u52A1" : "Paste Task";
    const copyTaskDialogTitle = isZh ? "\u590D\u5236\u4EFB\u52A1\u914D\u7F6E" : "Copy Task Config";
    const copyTaskDialogDesc = isZh ? "\u4EE5\u4E0B\u662F\u4EFB\u52A1\u914D\u7F6E\uFF0C\u53EF\u624B\u52A8\u590D\u5236\u6216\u70B9\u51FB\u4E00\u952E\u590D\u5236\u3002" : "Task config is ready. Copy manually or use one-click copy.";
    const copyConfigAction = isZh ? "\u4E00\u952E\u590D\u5236" : "Copy";
    const filteredEmptyTitle = isZh ? "没有符合当前筛选的任务" : "No tasks match this filter";
    const filteredEmptyDesc = isZh ? "试试切换其它状态，或切回全部后查看全部任务。" : "Try another status, or switch back to all tasks.";
    const taskFilterOptions: Array<{ value: TaskFilterKey; label: string }> = [
        { value: "all", label: isZh ? "全部" : "All" },
        { value: "enabled", label: isZh ? "自动调度" : "Auto" },
        { value: "disabled", label: isZh ? "已暂停" : "Paused" },
        { value: "success", label: isZh ? "今日已完成" : "Completed today" },
        { value: "failed", label: isZh ? "最近失败" : "Recent failure" },
        { value: "pending", label: isZh ? "待完成" : "Pending" },
        { value: "unregistered", label: isZh ? "调度缺失" : "Missing schedule" },
    ];
    const pasteTaskDialogTitle = isZh ? "\u7C98\u8D34\u5BFC\u5165\u4EFB\u52A1" : "Paste Task Config";
    const pasteTaskDialogDesc = isZh ? "\u65E0\u6CD5\u76F4\u63A5\u8BFB\u53D6\u526A\u8D34\u677F\uFF0C\u8BF7\u5728\u4E0B\u65B9\u7C98\u8D34\u914D\u7F6E\u540E\u5BFC\u5165\u3002" : "Clipboard read failed. Paste config below and import.";
    const pasteTaskDialogPlaceholder = isZh ? "\u5728\u6B64\u7C98\u8D34\u4EFB\u52A1\u914D\u7F6E JSON..." : "Paste task config JSON here...";
    const importTaskAction = isZh ? "\u5BFC\u5165\u4EFB\u52A1" : "Import Task";
    const clipboardReadFailed = isZh ? "\u65E0\u6CD5\u8BFB\u53D6\u526A\u8D34\u677F\uFF0C\u5DF2\u5207\u6362\u4E3A\u624B\u52A8\u7C98\u8D34\u5BFC\u5165" : "Clipboard read failed, switched to manual paste import";
    const copyTaskSuccess = (taskName: string) =>
        isZh ? `\u4EFB\u52A1 ${taskName} \u5DF2\u590D\u5236\u5230\u526A\u8D34\u677F` : `Task ${taskName} copied to clipboard`;
    const copyTaskFailed = isZh ? "\u590D\u5236\u4EFB\u52A1\u5931\u8D25" : "Copy task failed";
    const pasteTaskSuccess = (taskName: string) =>
        isZh ? `\u4EFB\u52A1 ${taskName} \u5BFC\u5165\u6210\u529F` : `Task ${taskName} imported`;
    const pasteTaskFailed = isZh ? "\u7C98\u8D34\u4EFB\u52A1\u5931\u8D25" : "Paste task failed";
    const clipboardUnsupported = isZh ? "\u5F53\u524D\u73AF\u5883\u4E0D\u652F\u6301\u526A\u8D34\u677F\u64CD\u4F5C" : "Clipboard API is not available";
    const copyTaskFallbackManual = isZh ? "\u81EA\u52A8\u590D\u5236\u5931\u8D25\uFF0C\u8BF7\u5728\u5F39\u7A97\u5185\u624B\u52A8\u590D\u5236" : "Auto copy failed, please copy manually from dialog";

    const sanitizeTaskName = useCallback((raw: string) => {
        return raw
            .trim()
            .replace(/[<>:"/\\|?*]+/g, "_")
            .replace(/\s+/g, "_")
            .replace(/_+/g, "_")
            .replace(/^_+|_+$/g, "")
            .slice(0, 64);
    }, []);

    const toActionTypeOption = useCallback((action: any): ActionTypeOption => {
        const actionId = Number(action?.action);
        if (actionId === 1) return "1";
        if (actionId === 3) return "3";
        if (actionId === 2) return "2";
        if (actionId === 4 || actionId === 6) return "ai_vision";
        if (actionId === 5 || actionId === 7) return "ai_logic";
        if (actionId === 8) return "ai_poetry";
        if (actionId === 9) return "assert_success";
        return "1";
    }, []);

    const isActionValid = useCallback((action: TaskFormAction) => {
        const actionId = Number(action?.action);
        if (actionId === 1 || actionId === 3) {
            return Boolean(("text" in action ? action.text : "").trim());
        }
        if (actionId === 2) {
            return Boolean(("dice" in action ? action.dice : "").trim());
        }
        if (isSuccessAssertionAction(action)) {
            return toSuccessKeywords(action.raw_input).length > 0;
        }
        return [4, 5, 6, 7, 8].includes(actionId);
    }, []);

    const loadData = useCallback(async () => {
        try {
            setLoading(true);
            const [tasksData, schedulerData] = await Promise.all([
                listSignTasks(accountName),
                getSchedulerStatus(accountName),
            ]);
            setTasks(tasksData);
            setSchedulerStatus(schedulerData);
        } catch (err: any) {
            if (handleAccountSessionInvalid(err)) return;
            const toast = addToastRef.current;
            if (toast) {
                toast(formatErrorMessage("load_failed", err), "error");
            }
            return;
        } finally {
            setLoading(false);
        }
    }, [accountName, formatErrorMessage, handleAccountSessionInvalid]);

    const loadChatCache = useCallback(async (options?: { forceRefresh?: boolean; autoRefreshIfExpired?: boolean; ensureExists?: boolean; silent?: boolean }) => {
        if (!token || !accountName) return;
        try {
            if (!options?.silent) {
                setRefreshingChats(true);
            }
            const res = options?.forceRefresh
                ? await refreshAccountChats(accountName)
                : await getAccountChats(accountName, {
                    autoRefreshIfExpired: options?.autoRefreshIfExpired,
                    ensureExists: options?.ensureExists,
                });
            setChats(res.items || []);
            setChatCacheMeta({
                last_cached_at: res.last_cached_at,
                cache_ttl_minutes: res.cache_ttl_minutes,
                expired: res.expired,
                count: res.count,
            });
            return res;
        } catch (err: any) {
            if (handleAccountSessionInvalid(err)) return;
            if (!options?.silent) {
                const toast = addToastRef.current;
                if (toast) {
                    toast(formatErrorMessage(options?.forceRefresh ? "refresh_failed" : "load_failed", err), "error");
                }
            }
        } finally {
            if (!options?.silent) {
                setRefreshingChats(false);
            }
        }
    }, [token, accountName, handleAccountSessionInvalid, formatErrorMessage]);

    useEffect(() => {
        let mounted = true;

        void (async () => {
            const tokenStr = await ensureAccessToken();
            if (!mounted) return;
            if (!tokenStr) {
                router.replace("/");
                return;
            }
            if (!accountName) {
                router.replace("/dashboard");
                return;
            }
            setLocalToken(tokenStr);
            setChecking(false);
            loadData();
        })();

        return () => {
            mounted = false;
        };
    }, [accountName, loadData, router]);

    useEffect(() => {
        if (!token || !accountName) return;
        const query = chatSearch.trim();
        if (!query) {
            setChatSearchResults([]);
            setChatSearchLoading(false);
            return;
        }
        let cancelled = false;
        setChatSearchLoading(true);
        const timer = setTimeout(async () => {
            try {
                const res = await searchAccountChats(accountName, query, 50, 0);
                if (!cancelled) {
                    setChatSearchResults(res.items || []);
                }
            } catch (err: any) {
                if (!cancelled) {
                    if (handleAccountSessionInvalid(err)) return;
                    const toast = addToastRef.current;
                    if (toast) {
                        toast(formatErrorMessage("search_failed", err), "error");
                    }
                    setChatSearchResults([]);
                }
            } finally {
                if (!cancelled) {
                    setChatSearchLoading(false);
                }
            }
        }, 300);
        return () => {
            cancelled = true;
            clearTimeout(timer);
        };
    }, [chatSearch, token, accountName, formatErrorMessage, handleAccountSessionInvalid]);

    useEffect(() => {
        const dialogOpen = showCreateDialog || showEditDialog;
        if (!dialogOpen) {
            chatDialogLoadKeyRef.current = null;
            setChatSearch("");
            setChatSearchResults([]);
            setChatSearchLoading(false);
            return;
        }
        const dialogType = showCreateDialog ? "create" : "edit";
        const loadKey = `${accountName}:${dialogType}`;
        if (chatDialogLoadKeyRef.current === loadKey) {
            return;
        }
        chatDialogLoadKeyRef.current = loadKey;
        void loadChatCache({ autoRefreshIfExpired: true, ensureExists: true });
    }, [showCreateDialog, showEditDialog, accountName, loadChatCache]);

    useEffect(() => {
        chatDialogLoadKeyRef.current = null;
        setChats([]);
        setChatCacheMeta(null);
        setChatSearch("");
        setChatSearchResults([]);
    }, [accountName]);

    useEffect(() => {
        if (!shouldOpenCreate || !token || !accountName) return;
        setShowEditDialog(false);
        setShowCreateDialog(true);
        router.replace(`/dashboard/account-tasks?name=${encodeURIComponent(accountName)}`);
    }, [shouldOpenCreate, token, accountName, router]);

    useEffect(() => {
        if (selectedHistoryIndex >= historyLogs.length) {
            setSelectedHistoryIndex(0);
        }
    }, [historyLogs.length, selectedHistoryIndex]);

    useEffect(() => {
        if (!token || !historyTaskName) return;
        let stopped = false;
        let timer: ReturnType<typeof setTimeout>;
        const refresh = async () => {
            try {
                const logs = await getSignTaskHistory(historyTaskName, accountName, 30);
                if (!stopped) setHistoryLogs(logs);
            } catch { /* Keep existing history while offline. */ }
            if (!stopped) timer = setTimeout(refresh, 5000);
        };
        timer = setTimeout(refresh, 5000);
        return () => { stopped = true; clearTimeout(timer); };
    }, [token, historyTaskName, accountName]);

    const monitorUnavailable = useTaskMonitor(accountName, liveMonitorTaskName, async () => {
        const taskName = liveMonitorTaskName;
        const baseline = runHistoryBaseline.current;
        setRunningTaskName(null);
        setLiveMonitorTaskName(null);
        try {
            const logs = await getSignTaskHistory(taskName!, accountName, 1, AbortSignal.timeout(10000));
            const latest = baseline?.account === accountName && baseline.task === taskName
                ? getNewRunResult(logs, baseline.time) : undefined;
            addToast(latest
                ? (latest.success ? (isZh ? `任务 ${taskName} 执行成功` : `Task ${taskName} succeeded`) : (isZh ? `任务 ${taskName} 执行失败` : `Task ${taskName} failed`))
                : (isZh ? "任务已结束，暂无执行结果" : "Task finished; result unavailable"),
                latest ? (latest.success ? "success" : "error") : "info");
        } catch {
            addToast(isZh ? "任务已结束，但结果暂时无法读取，请稍后查看历史" : "Task finished, but its result is unavailable. Check history later.", "info");
        }
        await loadData();
    });

    const handleRefreshChats = async () => {
        const res = await loadChatCache({ forceRefresh: true });
        if (res) {
            addToast(t("chats_refreshed"), "success");
        }
    };

    const applyChatSelection = (chatId: number, chatName: string) => {
        if (showCreateDialog) {
            setNewTask({
                ...newTask,
                name: newTask.name || chatName,
                chat_id: chatId,
                chat_id_manual: chatId !== 0 ? chatId.toString() : "",
                chat_name: chatName,
            });
        } else {
            setEditTask({
                ...editTask,
                chat_id: chatId,
                chat_id_manual: chatId !== 0 ? chatId.toString() : "",
                chat_name: chatName,
            });
        }
    };

    const handleDeleteTask = async (taskName: string) => {
        if (!token) return;

        try {
            setLoading(true);
            await deleteSignTask(taskName, accountName);
            setDeleteTaskName(null);
            await loadData();
        } catch (err: any) {
            if (err.status !== 404 && !err.message?.includes("not exist")) {
                addToast(formatErrorMessage("delete_failed", err), "error");
            } else {
                setDeleteTaskName(null);
                await loadData();
            }
        } finally {
            setLoading(false);
        }
    };

    const handleRunTask = async (taskName: string) => {
        if (!token || loading || refreshingChats) return;

        try {
            setRunningTaskName(taskName);
            const baseline = { account: accountName, task: taskName, time: undefined as string | null | undefined };
            try {
                const history = await getSignTaskHistory(taskName, accountName, 1, AbortSignal.timeout(10000));
                baseline.time = history[0]?.time ?? null;
            } catch { /* A missing baseline must never be treated as a confirmed result. */ }
            runHistoryBaseline.current = baseline;
            const result = await runSignTask(taskName, accountName);

            if (result.started) {
                setLiveMonitorTaskName(taskName);
                addToast(
                    isZh ? `任务 ${taskName} 已开始执行` : `Task ${taskName} started`,
                    "info"
                );
            } else if (result.code === "TASK_ALREADY_RUNNING") {
                setLiveMonitorTaskName(taskName);
                addToast(language === "zh" ? "该任务正在运行中，已在后台监控完成状态" : "Task is already running. Monitoring completion in background.", "info");
            } else {
                addToast(result.error || t("task_run_failed"), "error");
                setRunningTaskName(null);
                setLiveMonitorTaskName(null);
            }
        } catch (err: any) {
            setRunningTaskName(null);
            setLiveMonitorTaskName(null);
            addToast(formatErrorMessage("task_run_failed", err), "error");
        }
    };

    const handleToggleTaskEnabled = async (task: SignTask) => {
        if (!token) return;

        const nextEnabled = !task.enabled;
        try {
            setLoading(true);
            await setSignTaskEnabled(task.name, accountName, nextEnabled);
            await loadData();
            addToast(
                nextEnabled
                    ? (isZh ? "已恢复自动执行" : "Auto scheduling resumed")
                    : (isZh ? "已暂停自动执行，仍可手动运行" : "Auto scheduling paused; manual run remains available"),
                "success"
            );
        } catch (err: any) {
            addToast(
                nextEnabled
                    ? (isZh ? `恢复自动执行失败: ${err?.message || ""}` : `Failed to resume auto scheduling: ${err?.message || ""}`)
                    : (isZh ? `暂停自动执行失败: ${err?.message || ""}` : `Failed to pause auto scheduling: ${err?.message || ""}`),
                "error"
            );
        } finally {
            setLoading(false);
        }
    };

    const handleShowTaskHistory = async (task: SignTask) => {
        if (!token) return;
        setHistoryTaskName(task.name);
        setHistoryLogs([]);
        setSelectedHistoryIndex(0);
        setHistoryLogView("read");
        setHistoryFailureOnly(false);
        setHistoryExpandDetails(false);
        setHistoryLoading(true);
        try {
            const logs = await getSignTaskHistory(task.name, accountName, 30);
            setHistoryLogs(logs);
        } catch (err: any) {
            addToast(formatErrorMessage("logs_fetch_failed", err), "error");
        } finally {
            setHistoryLoading(false);
        }
    };


    const selectedHistoryLog = historyLogs[selectedHistoryIndex] || historyLogs[0];

    const handleCopyHistoryText = async (content: string, label: string) => {
        if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
            addToast(clipboardUnsupported, "error");
            return;
        }
        try {
            await navigator.clipboard.writeText(content);
            addToast(isZh ? `已复制${label}` : `${label} copied`, "success");
        } catch (err: any) {
            addToast(err?.message ? `${label}: ${err.message}` : (isZh ? "复制失败" : "Copy failed"), "error");
        }
    };

    const importTaskFromConfig = async (rawConfig: string): Promise<{ ok: boolean; error?: string }> => {
        if (!token) return { ok: false, error: "NO_TOKEN" };
        const taskConfig = (rawConfig || "").trim();
        if (!taskConfig) {
            addToast(t("import_empty"), "error");
            return { ok: false, error: t("import_empty") };
        }

        try {
            setLoading(true);
            const result = await importSignTask(taskConfig, undefined, accountName);
            addToast(pasteTaskSuccess(result.task_name), "success");
            await loadData();
            return { ok: true };
        } catch (err: any) {
            const message = err?.message ? `${pasteTaskFailed}: ${err.message}` : pasteTaskFailed;
            addToast(message, "error");
            return { ok: false, error: message };
        } finally {
            setLoading(false);
        }
    };

    const handleCopyTask = async (taskName: string) => {
        if (!token) return;

        try {
            setLoading(true);
            const taskConfig = await exportSignTask(taskName, accountName);
            if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
                try {
                    await navigator.clipboard.writeText(taskConfig);
                    addToast(copyTaskSuccess(taskName), "success");
                    return;
                } catch {
                    addToast(copyTaskFallbackManual, "error");
                }
            }
            setCopyTaskDialog({ taskName, config: taskConfig });
        } catch (err: any) {
            const message = err?.message ? `${copyTaskFailed}: ${err.message}` : copyTaskFailed;
            addToast(message, "error");
        } finally {
            setLoading(false);
        }
    };

    const handleCopyTaskConfig = async () => {
        if (!copyTaskDialog) return;
        if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
            addToast(clipboardUnsupported, "error");
            return;
        }
        try {
            setCopyingConfig(true);
            await navigator.clipboard.writeText(copyTaskDialog.config);
            addToast(copyTaskSuccess(copyTaskDialog.taskName), "success");
            setCopyTaskDialog(null);
        } catch (err: any) {
            const message = err?.message ? `${copyTaskFailed}: ${err.message}` : copyTaskFailed;
            addToast(message, "error");
        } finally {
            setCopyingConfig(false);
        }
    };

    const handlePasteDialogImport = async () => {
        setImportingPastedConfig(true);
        const result = await importTaskFromConfig(pasteTaskConfigInput);
        if (result.ok) {
            setShowPasteDialog(false);
            setPasteTaskConfigInput("");
        }
        setImportingPastedConfig(false);
    };

    const handlePasteTask = async () => {
        if (!token) return;

        if (typeof navigator !== "undefined" && navigator.clipboard?.readText) {
            try {
                const taskConfig = (await navigator.clipboard.readText()).trim();
                if (taskConfig) {
                    const result = await importTaskFromConfig(taskConfig);
                    if (result.ok) {
                        return;
                    }
                    setPasteTaskConfigInput(taskConfig);
                    setShowPasteDialog(true);
                    return;
                }
            } catch {
                addToast(clipboardReadFailed, "error");
            }
        } else {
            addToast(clipboardUnsupported, "error");
        }

        setPasteTaskConfigInput("");
        setShowPasteDialog(true);
    };

    const closeCopyTaskDialog = () => {
        if (copyingConfig) {
            return;
        }
        setCopyTaskDialog(null);
    };

    const closePasteTaskDialog = () => {
        if (importingPastedConfig || loading) {
            return;
        }
        setShowPasteDialog(false);
        setPasteTaskConfigInput("");
    };

    const handleCreateTask = async () => {
        if (!token) return;

        if (!newTask.sign_at) {
            addToast(t("cron_required"), "error");
            return;
        }

        let chatId = newTask.chat_id;
        if (newTask.chat_id_manual) {
            chatId = parseInt(newTask.chat_id_manual);
            if (isNaN(chatId)) {
                addToast(t("chat_id_numeric"), "error");
                return;
            }
        }

        if (chatId === 0) {
            addToast(t("select_chat_error"), "error");
            return;
        }

        if (newTask.actions.length === 0 || newTask.actions.some((action) => !isActionValid(action))) {
            addToast(t("add_action_error"), "error");
            return;
        }

        try {
            setLoading(true);
            const fallbackTaskName =
                sanitizeTaskName(newTask.chat_name) ||
                sanitizeTaskName(newTask.chat_id_manual ? `chat_${newTask.chat_id_manual}` : "") ||
                `task_${Date.now()}`;
            const finalTaskName = sanitizeTaskName(newTask.name) || fallbackTaskName;

            const request: CreateSignTaskRequest = {
                name: finalTaskName,
                account_name: accountName,
                sign_at: newTask.sign_at,
                retry_count: newTask.retry_count,
                chats: [formToChat(newTask)],
                random_seconds: newTask.random_minutes * 60,
                execution_mode: newTask.execution_mode,
                range_start: newTask.range_start,
                range_end: newTask.range_end,
            };

            await createSignTask(request);
            addToast(t("create_success"), "success");
            setShowCreateDialog(false);
            setNewTask({
                name: "",
                sign_at: "0 6 * * *",
                random_minutes: 0,
                retry_count: 0,
                chat_id: 0,
                chat_id_manual: "",
                chat_name: "",
                actions: [defaultTaskAction()],
                delete_after: undefined,
                event_timeout: undefined,
                event_retries: undefined,
                event_retry_wait: undefined,
                event_history_limit: undefined,
                event_history_failure_threshold: undefined,
                event_history_rescue_interval: undefined,
                event_history_rpc_timeout: undefined,
                event_history_result_max_age: undefined,
                event_action_timeout: undefined,
                event_send_timeout: undefined,
                event_media_timeout: undefined,
                event_ai_timeout: undefined,
                event_callback_timeout: undefined,
                event_callback_retries: undefined,
                event_ai_fallback: undefined,
                execution_mode: "fixed",
                range_start: "09:00",
                range_end: "18:00",
            });
            await loadData();
        } catch (err: any) {
            addToast(formatErrorMessage("create_failed", err), "error");
        } finally {
            setLoading(false);
        }
    };

    const handleAddAction = () => {
        setNewTask({
            ...newTask,
            actions: [...newTask.actions, defaultTaskAction()],
        });
    };

    const handleRemoveAction = (index: number) => {
        setNewTask({
            ...newTask,
            actions: newTask.actions.filter((_, i) => i !== index),
        });
    };

    const handleEditTask = (task: SignTask) => {
        setEditingTaskName(task.name);
        setEditingChats(task.chats);
        setEditingChatIndex(0);
        setEditingRandomSeconds(task.random_seconds);
        const chat = task.chats[0];
        setEditTask({
            sign_at: task.sign_at,
            random_minutes: Math.round(task.random_seconds / 60),
            retry_count: task.retry_count || 0,
            chat_id: chat?.chat_id || 0,
            chat_id_manual: chat?.chat_id?.toString() || "",
            chat_name: chat?.name || "",
            actions: chat?.actions?.map(toTaskFormAction) || [defaultTaskAction()],
            delete_after: chat?.delete_after,
            event_timeout: chat?.event_timeout,
            event_retries: chat?.event_retries,
            event_retry_wait: chat?.event_retry_wait,
            event_history_limit: chat?.event_history_limit,
            event_history_failure_threshold: chat?.event_history_failure_threshold,
            event_history_rescue_interval: chat?.event_history_rescue_interval,
            event_history_rpc_timeout: chat?.event_history_rpc_timeout,
            event_history_result_max_age: chat?.event_history_result_max_age,
            event_action_timeout: chat?.event_action_timeout,
            event_send_timeout: chat?.event_send_timeout,
            event_media_timeout: chat?.event_media_timeout,
            event_ai_timeout: chat?.event_ai_timeout,
            event_callback_timeout: chat?.event_callback_timeout,
            event_callback_retries: chat?.event_callback_retries,
            event_ai_fallback: chat?.event_ai_fallback,
            execution_mode: task.execution_mode || "fixed",
            range_start: task.range_start || "09:00",
            range_end: task.range_end || "18:00",
        });
        setShowEditDialog(true);
    };

    const handleSaveEdit = async () => {
        if (!token) return;

        const chatId = editTask.chat_id || parseInt(editTask.chat_id_manual) || 0;
        if (!chatId) {
            addToast(t("select_chat_error"), "error");
            return;
        }
        if (editTask.actions.length === 0 || editTask.actions.some((action) => !isActionValid(action))) {
            addToast(t("add_action_error"), "error");
            return;
        }

        try {
            setLoading(true);

            const drafts = replaceEditedChat(editingChats, editingChatIndex, editTask);
            const invalidIndex = findInvalidChatIndex(drafts);
            if (invalidIndex !== -1) {
                setEditingChats(drafts);
                setEditingChatIndex(invalidIndex);
                setEditTask(prev => ({ ...prev, ...chatToForm(drafts[invalidIndex]) }));
                addToast(isZh ? `第 ${invalidIndex + 1} 个会话的动作不完整，请补充后保存` : `Complete the actions in chat ${invalidIndex + 1} before saving`, "error");
                return;
            }
            await updateSignTask(editingTaskName, {
                sign_at: editTask.sign_at,
                random_seconds: editingRandomSeconds,
                retry_count: editTask.retry_count,
                chats: drafts,
                execution_mode: editTask.execution_mode,
                range_start: editTask.range_start,
                range_end: editTask.range_end,
            }, accountName);

            addToast(t("update_success"), "success");
            await loadData();
            setShowEditDialog(false);
        } catch (err: any) {
            addToast(formatErrorMessage("update_failed", err), "error");
        } finally {
            setLoading(false);
        }
    };

    const handleEditAddAction = () => {
        setEditTask({
            ...editTask,
            actions: [...editTask.actions, defaultTaskAction()],
        });
    };

    const handleEditRemoveAction = (index: number) => {
        if (editTask.actions.length <= 1) return;
        setEditTask({
            ...editTask,
            actions: editTask.actions.filter((_, i) => i !== index),
        });
    };

    const updateCurrentDialogAction = useCallback((index: number, updater: (action: TaskFormAction) => TaskFormAction) => {
        if (showCreateDialog) {
            setNewTask((prev) => {
                if (index < 0 || index >= prev.actions.length) return prev;
                const nextActions = [...prev.actions];
                nextActions[index] = updater(nextActions[index] || defaultTaskAction());
                return { ...prev, actions: nextActions };
            });
            return;
        }

        setEditTask((prev) => {
            if (index < 0 || index >= prev.actions.length) return prev;
            const nextActions = [...prev.actions];
            nextActions[index] = updater(nextActions[index] || defaultTaskAction());
            return { ...prev, actions: nextActions };
        });
    }, [showCreateDialog]);

    const startOfToday = useMemo(() => {
        const now = new Date();
        return new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    }, []);
    const enabledTaskCount = useMemo(() => tasks.filter((task) => task.enabled).length, [tasks]);
    const todayCompletedTaskCount = useMemo(() => {
        return tasks.filter((task) => {
            if (!task.last_run?.success) return false;
            const runAt = new Date(task.last_run.time).getTime();
            return Number.isFinite(runAt) && runAt >= startOfToday && runAt < startOfToday + DAY_MS;
        }).length;
    }, [startOfToday, tasks]);
    const failedTaskCount = useMemo(() => {
        return tasks.filter((task) => task.enabled && task.last_run?.success === false).length;
    }, [tasks]);
    const pendingTaskCount = useMemo(() => {
        return Math.max(0, enabledTaskCount - todayCompletedTaskCount - failedTaskCount);
    }, [enabledTaskCount, failedTaskCount, todayCompletedTaskCount]);
    const schedulerMap = useMemo(() => {
        return new Map((schedulerStatus?.sign_tasks ?? []).map((item) => [item.task_name, item]));
    }, [schedulerStatus]);
    const filteredTasks = useMemo(() => {
        return tasks.filter((task) => {
            const schedulerItem = schedulerMap.get(task.name);
            switch (taskFilter) {
                case "enabled":
                    return task.enabled;
                case "disabled":
                    return !task.enabled;
                case "success":
                    if (!task.last_run?.success) return false;
                    const successRunAt = task.last_run.time ? new Date(task.last_run.time).getTime() : 0;
                    return Number.isFinite(successRunAt) && successRunAt >= startOfToday && successRunAt < startOfToday + DAY_MS;
                case "failed":
                    return task.last_run?.success === false;
                case "pending":
                    if (!task.enabled) return false;
                    if (task.last_run?.success === false) return false;
                    const runAt = task.last_run?.time ? new Date(task.last_run.time).getTime() : 0;
                    const ranToday = Number.isFinite(runAt) && runAt >= startOfToday && runAt < startOfToday + DAY_MS;
                    return !ranToday;
                case "unregistered":
                    return task.enabled && schedulerItem?.job_exists === false;
                default:
                    return true;
            }
        });
    }, [schedulerMap, taskFilter, tasks, startOfToday]);

    if (!token || checking) {
        return <PageLoading fullScreen message={t("loading")} />;
    }

    return (
        <div className="flex min-h-screen flex-col bg-[var(--bg-primary)] text-[var(--text-primary)]">
            <nav className="navbar">
                <div className="min-w-0 flex flex-1 items-center gap-3">
                    <span className="inline-flex h-10 w-10 items-center justify-center rounded-2xl bg-[var(--accent)] text-white shadow-sm">
                        <Lightning weight="fill" size={20} />
                    </span>
                    <span className="nav-title truncate text-lg font-bold tracking-tight">TG Sign Plus</span>
                </div>
                <div className="top-right-actions shrink-0 flex-nowrap justify-end gap-1 sm:gap-2">
                    <ThemeLanguageToggle />
                    <IconButton aria-label={t("sidebar_settings")} title={t("sidebar_settings")} onClick={() => router.push("/dashboard/settings")}>
                        <Gear weight="bold" size={18} />
                    </IconButton>
                    <IconButton aria-label={t("logout")} title={t("logout")} onClick={logout} danger>
                        <SignOut weight="bold" size={18} />
                    </IconButton>
                </div>
            </nav>

            <main className="main-content !pt-6">
                <div className="space-y-6">
                    <div>
                        <Link href="/dashboard" className="inline-flex items-center gap-2 text-sm font-medium text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)]">
                            <CaretLeft weight="bold" size={16} />
                            <span>{language === "zh" ? "返回 Dashboard" : "Back to dashboard"}</span>
                        </Link>
                    </div>

                    <section className="glass-panel overflow-hidden">
                    <div className="px-5 py-5 sm:px-6 sm:py-6">
                        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">
                            {language === "zh" ? "任务工作台" : "Account workspace"}
                        </div>
                        <div className="mt-2 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                            <div className="min-w-0">
                                <h2 className="truncate text-2xl font-semibold tracking-[-0.03em] text-[var(--text-primary)] sm:text-[30px]" title={accountName}>{accountName}</h2>
                                <div className="mt-3 flex flex-wrap items-center gap-2">
                                    <div className="rounded-full border border-[var(--border-primary)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-secondary)]">
                                        <span className="font-semibold text-[var(--text-primary)]">{tasks.length}</span>
                                        <span className="ml-2">{language === "zh" ? "任务总数" : "Total"}</span>
                                    </div>
                                    <div className="rounded-full border border-[var(--border-primary)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-secondary)]">
                                        <span className="font-semibold text-[var(--text-primary)]">{enabledTaskCount}</span>
                                        <span className="ml-2">{language === "zh" ? "自动调度" : "Auto"}</span>
                                    </div>
                                    <div className="rounded-full border border-[var(--border-primary)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-secondary)]">
                                        <span className="font-semibold text-[var(--text-primary)]">{todayCompletedTaskCount}</span>
                                        <span className="ml-2">{language === "zh" ? "今日已完成" : "Done today"}</span>
                                    </div>
                                    <div className="rounded-full border border-[var(--border-primary)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-secondary)]">
                                        <span className="font-semibold text-[var(--text-primary)]">{pendingTaskCount}</span>
                                        <span className="ml-2">{language === "zh" ? "待完成" : "Pending"}</span>
                                    </div>
                                    <div className="rounded-full border border-[var(--border-primary)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-secondary)]">
                                        <span className="font-semibold text-[var(--text-primary)]">{failedTaskCount}</span>
                                        <span className="ml-2">{language === "zh" ? "失败任务" : "Failed"}</span>
                                    </div>
                                </div>
                            </div>
                            <div className="flex flex-wrap gap-2">
                                <Button
                                    onClick={() => {
                                        setShowEditDialog(false);
                                        setShowCreateDialog(true);
                                    }}
                                    disabled={dialogActionsDisabled}
                                >
                                    <Plus weight="bold" size={16} />
                                    {t("add_task")}
                                </Button>
                                <Button
                                    variant="ghost"
                                    onClick={handlePasteTask}
                                    disabled={dialogActionsDisabled}
                                >
                                    <ClipboardText weight="bold" size={16} />
                                    {pasteTaskTitle}
                                </Button>
                            </div>
                        </div>
                    </div>
                </section>

                <section className="space-y-4">
                    <div className="flex flex-nowrap items-center justify-between gap-3">
                        <div className="min-w-0 flex-1">
                            <div className="flex min-w-0 items-baseline gap-2">
                                <h2 className="shrink-0 text-base font-semibold text-[var(--text-primary)]">{language === "zh" ? "任务列表" : "Task list"}</h2>
                                <div className="min-w-0 truncate text-xs text-[var(--text-tertiary)]">
                                    {language === "zh" ? `${filteredTasks.length} / ${tasks.length}` : `${filteredTasks.length} / ${tasks.length}`}
                                </div>
                            </div>
                            {runningTaskName ? (
                                <StatusBadge tone="success" className="mt-2 max-w-full px-3 py-1 text-[10px]">
                                    <span className="truncate">
                                        {language === "zh" ? `运行中：${runningTaskName}` : `Running: ${runningTaskName}`}
                                    </span>
                                </StatusBadge>
                            ) : null}
                        </div>
                        <div className="shrink-0">
                            <select
                                id="task-filter-select"
                                value={taskFilter}
                                onChange={(e) => setTaskFilter(e.target.value as TaskFilterKey)}
                                className="h-10 w-[128px] rounded-xl border border-[var(--border-secondary)] bg-[var(--bg-secondary)] px-3 text-sm text-[var(--text-primary)] outline-none transition-colors focus:border-[var(--accent)] sm:w-[190px]"
                            >
                                {taskFilterOptions.map((option) => (
                                    <option key={option.value} value={option.value}>
                                        {option.label}
                                    </option>
                                ))}
                            </select>
                        </div>
                    </div>

                    {loading && tasks.length === 0 ? (
                        <div className="w-full py-20 flex flex-col items-center justify-center text-[var(--text-tertiary)]">
                            <Spinner size={40} weight="bold" className="animate-spin mb-4" />
                            <p className="text-xs uppercase tracking-widest font-bold font-mono">{t("loading")}</p>
                        </div>
                    ) : tasks.length === 0 ? (
                        <div className="glass-panel p-5">
                            <EmptyState
                                onClick={() => {
                                    setShowEditDialog(false);
                                    setShowCreateDialog(true);
                                }}
                                icon={<Plus size={40} weight="bold" />}
                                title={t("no_tasks")}
                                description={t("no_tasks_desc")}
                            />
                        </div>
                    ) : filteredTasks.length === 0 ? (
                        <div className="glass-panel p-5">
                            <EmptyState
                                icon={<ListDashes size={40} weight="bold" />}
                                title={filteredEmptyTitle}
                                description={filteredEmptyDesc}
                                action={
                                    <Button variant="secondary" onClick={() => setTaskFilter("all")}>
                                        {isZh ? "全部" : "All"}
                                    </Button>
                                }
                            />
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                            {filteredTasks.map((task) => (
                                <TaskItem
                                    key={task.name}
                                    task={task}
                                    loading={loading}
                                    isRunning={runningTaskName === task.name}
                                    schedulerItem={schedulerMap.get(task.name)}
                                    schedulerTimezone={schedulerStatus?.timezone}
                                    onEdit={handleEditTask}
                                    onRun={handleRunTask}
                                    onToggleEnabled={handleToggleTaskEnabled}
                                    onViewLogs={handleShowTaskHistory}
                                    onCopy={handleCopyTask}
                                    onDelete={setDeleteTaskName}
                                    t={t}
                                    language={language}
                                />
                            ))}
                        </div>
                    )}
                </section>
            </div>
            </main>
            {monitorUnavailable && <div role="status" className="fixed bottom-20 left-4 right-4 z-50 rounded-xl border border-amber-500 bg-[var(--bg-secondary)] p-3 text-sm">
                {isZh ? "暂时无法确认任务状态，正在重试连接；任务可能仍在后台运行。" : "Task status unavailable. Reconnecting; the task may still be running."}
            </div>}
            <AppFooter />
            {toasts && removeToast ? <ToastContainer toasts={toasts} removeToast={removeToast} /> : null}

            <ModalShell
                open={showCreateDialog || showEditDialog}
                title={showCreateDialog ? t("create_task") : `${t("edit_task")}: ${editingTaskName}`}
                description={language === "zh" ? "统一编辑任务的基本信息、调度方式、目标 chat 与动作序列。" : "Edit task basics, scheduling, target chat, and action sequence in one place."}
                onClose={() => {
                    setShowCreateDialog(false);
                    setShowEditDialog(false);
                }}
                className="max-w-xl"
                contentClassName="max-h-[78vh] overflow-y-auto p-5 custom-scrollbar"
                footer={
                    <div className="flex gap-3">
                        <Button
                            variant="secondary"
                            className="flex-1"
                            onClick={() => {
                                setShowCreateDialog(false);
                                setShowEditDialog(false);
                            }}
                        >
                            {t("cancel")}
                        </Button>
                        <Button
                            className="flex-1"
                            onClick={showCreateDialog ? handleCreateTask : handleSaveEdit}
                            disabled={dialogActionsDisabled}
                        >
                            {loading ? <Spinner className="animate-spin" /> : showCreateDialog ? t("add_task") : t("save_changes")}
                        </Button>
                    </div>
                }
            >
                <div className="space-y-5">
                    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                        {showCreateDialog ? (
                            <FormField label={t("task_name")} htmlFor="task-name-input">
                                <Input
                                    id="task-name-input"
                                    placeholder={taskNamePlaceholder}
                                    value={newTask.name}
                                    onChange={(e) => setNewTask({ ...newTask, name: e.target.value })}
                                />
                            </FormField>
                        ) : (
                            <FormField label={t("task_name")} htmlFor="editing-task-name-input">
                                <Input
                                    id="editing-task-name-input"
                                    value={editingTaskName}
                                    readOnly
                                    aria-readonly="true"
                                />
                            </FormField>
                        )}

                        <div className="space-y-2">
                            <label className={fieldLabelClass}>{t("scheduling_mode")}</label>
                            <select
                                className={selectClassName}
                                value={showCreateDialog ? newTask.execution_mode : editTask.execution_mode}
                                onChange={(e) => {
                                    const mode = e.target.value as "fixed" | "range";
                                    if (showCreateDialog) {
                                        setNewTask({ ...newTask, execution_mode: mode });
                                    } else {
                                        setEditTask({ ...editTask, execution_mode: mode });
                                    }
                                }}
                            >
                                <option value="range">{t("random_range_recommend")}</option>
                                <option value="fixed">{t("fixed_time_cron")}</option>
                            </select>
                        </div>

                        <FormField label={t("retry_count")} htmlFor="task-retry-count">
                            <Input
                                id="task-retry-count"
                                type="text"
                                value={showCreateDialog ? newTask.retry_count : editTask.retry_count}
                                onChange={(e) => {
                                    const raw = parseInt(e.target.value);
                                    const val = Number.isNaN(raw) ? 0 : Math.max(0, raw);
                                    if (showCreateDialog) {
                                        setNewTask({ ...newTask, retry_count: val });
                                    } else {
                                        setEditTask({ ...editTask, retry_count: val });
                                    }
                                }}
                            />
                        </FormField>

                        <div className="space-y-2">
                            {(showCreateDialog ? newTask.execution_mode : editTask.execution_mode) === "fixed" ? (
                                <>
                                    <label className={fieldLabelClass}>{t("sign_time_cron")}</label>
                                    <Input
                                        placeholder="0 6 * * *"
                                        value={showCreateDialog ? newTask.sign_at : editTask.sign_at}
                                        onChange={(e) => {
                                            if (showCreateDialog) {
                                                setNewTask({ ...newTask, sign_at: e.target.value });
                                            } else {
                                                setEditTask({ ...editTask, sign_at: e.target.value });
                                            }
                                        }}
                                    />
                                    <div className="mt-1 text-[10px] italic text-[var(--text-tertiary)]">{t("cron_example")}</div>
                                </>
                            ) : (
                                <>
                                    <label className={fieldLabelClass}>{t("time_range")}</label>
                                    <div className="grid grid-cols-2 gap-2">
                                        <Input
                                            type="time"
                                            aria-label={t("start_label")}
                                            title={t("start_label")}
                                            value={showCreateDialog ? newTask.range_start : editTask.range_start}
                                            onChange={(e) => {
                                                if (showCreateDialog) {
                                                    setNewTask({ ...newTask, range_start: e.target.value });
                                                } else {
                                                    setEditTask({ ...editTask, range_start: e.target.value });
                                                }
                                            }}
                                        />
                                        <Input
                                            type="time"
                                            aria-label={t("end_label")}
                                            title={t("end_label")}
                                            value={showCreateDialog ? newTask.range_end : editTask.range_end}
                                            onChange={(e) => {
                                                if (showCreateDialog) {
                                                    setNewTask({ ...newTask, range_end: e.target.value });
                                                } else {
                                                    setEditTask({ ...editTask, range_end: e.target.value });
                                                }
                                            }}
                                        />
                                    </div>
                                    <div className="mt-1 text-[10px] italic text-[var(--text-tertiary)]">{t("random_time_hint")}</div>
                                </>
                            )}
                        </div>
                    </div>

                    {showEditDialog && editingChats.length > 1 && (
                        <FormField label={isZh ? "编辑目标会话" : "Edit target chat"} htmlFor="editing-chat-index">
                            <select id="editing-chat-index" className={selectClassName} value={editingChatIndex}
                                onChange={event => {
                                    try {
                                        const drafts = replaceEditedChat(editingChats, editingChatIndex, editTask);
                                        const index = Number(event.target.value);
                                        setEditingChats(drafts);
                                        setEditingChatIndex(index);
                                        setEditTask(prev => ({ ...prev, ...chatToForm(drafts[index]) }));
                                    } catch (error) { addToast((error as Error).message, "error"); }
                                }}>
                                {editingChats.map((chat, index) => <option key={index} value={index}>{index + 1}. {chat.name || chat.chat_id}</option>)}
                            </select>
                            <p className="mt-2 text-xs text-[var(--text-secondary)]">{isZh ? "保存会保留所有会话，可切换后分别编辑。" : "All chats are preserved. Switch to edit each one."}</p>
                        </FormField>
                    )}
                    <div className="glass-panel !bg-[var(--bg-tertiary)] space-y-4 border-[var(--border-secondary)] p-4">
                        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                            <div className="space-y-2 min-w-0">
                                <div className="flex min-h-7 items-center">
                                    <label className="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)]">{t("search_chat")}</label>
                                </div>
                                <Input
                                    placeholder={t("search_chat_placeholder")}
                                    value={chatSearch}
                                    onChange={(e) => setChatSearch(e.target.value)}
                                />
                                <div className="min-h-[12rem] rounded-lg border border-[var(--border-secondary)] bg-[var(--bg-secondary)]">
                                    {chatSearch.trim() ? (
                                        <div className="max-h-48 overflow-y-auto">
                                            {chatSearchLoading ? (
                                                <div className="px-3 py-2 text-xs text-[var(--text-tertiary)]">{t("searching")}</div>
                                            ) : chatSearchResults.length > 0 ? (
                                                <div className="flex flex-col">
                                                    {chatSearchResults.map((chat) => {
                                                        const title = chat.title || chat.username || String(chat.id);
                                                        return (
                                                            <button
                                                                key={chat.id}
                                                                type="button"
                                                                className="border-b border-[var(--border-secondary)] px-3 py-2 text-left transition-colors hover:bg-[var(--bg-primary)] last:border-b-0"
                                                                onClick={() => {
                                                                    applyChatSelection(chat.id, title);
                                                                    setChatSearch("");
                                                                    setChatSearchResults([]);
                                                                }}
                                                            >
                                                                <div className="truncate text-sm font-semibold">{title}</div>
                                                                <div className="truncate font-mono text-[10px] text-[var(--text-tertiary)]">
                                                                    {chat.id}{chat.username ? ` · @${chat.username}` : ""}
                                                                </div>
                                                            </button>
                                                        );
                                                    })}
                                                </div>
                                            ) : (
                                                <div className="px-3 py-2 text-xs text-[var(--text-tertiary)]">{t("search_no_results")}</div>
                                            )}
                                        </div>
                                    ) : (
                                        <div className="flex h-full min-h-[12rem] items-center justify-center px-4 text-center text-xs text-[var(--text-tertiary)]">
                                            {t("search_chat_placeholder")}
                                        </div>
                                    )}
                                </div>
                            </div>

                            <div className="space-y-2 min-w-0">
                                <div className="flex min-h-7 items-center justify-between gap-2">
                                    <label className="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)]">{t("select_from_list")}</label>
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        size="sm"
                                        onClick={handleRefreshChats}
                                        disabled={refreshingChats}
                                        className="h-7 shrink-0 px-2 text-[10px] font-bold uppercase tracking-tighter text-[var(--accent)] hover:text-[var(--accent-hover)]"
                                        title={t("refresh_chat_title")}
                                    >
                                        {refreshingChats ? (
                                            <div className="h-3 w-3 animate-spin rounded-full border-2 border-[var(--accent)] border-t-transparent"></div>
                                        ) : (
                                            <ArrowClockwise weight="bold" size={12} />
                                        )}
                                        {t("refresh_list")}
                                    </Button>
                                </div>
                                <select
                                    className={selectClassName}
                                    value={showCreateDialog ? newTask.chat_id : editTask.chat_id}
                                    onChange={(e) => {
                                        const id = parseInt(e.target.value);
                                        const chat = chats.find((c) => c.id === id);
                                        const chatName = chat?.title || chat?.username || "";
                                        applyChatSelection(id, chatName);
                                    }}
                                >
                                    <option value={0}>{t("select_from_list")}</option>
                                    {chats.map((chat) => (
                                        <option key={chat.id} value={chat.id}>
                                            {chat.title || chat.username || chat.id}
                                        </option>
                                    ))}
                                </select>
                                <div className="min-h-[12rem] rounded-lg border border-[var(--border-secondary)] bg-[var(--bg-secondary)] p-2">
                                    <div className="max-h-44 overflow-y-auto rounded-md">
                                        {chats.length > 0 ? (
                                            <div className="flex flex-col">
                                                {chats.map((chat) => {
                                                    const title = chat.title || chat.username || String(chat.id);
                                                    const selectedChatId = showCreateDialog ? newTask.chat_id : editTask.chat_id;
                                                    const isSelected = selectedChatId === chat.id;
                                                    return (
                                                        <button
                                                            key={chat.id}
                                                            type="button"
                                                            className={cn(
                                                                "rounded-md px-3 py-2 text-left transition-colors",
                                                                isSelected ? "bg-[var(--bg-tertiary)]" : "hover:bg-[var(--bg-primary)]"
                                                            )}
                                                            onClick={() => applyChatSelection(chat.id, title)}
                                                        >
                                                            <div className="truncate text-sm font-semibold text-[var(--text-primary)]">{title}</div>
                                                            <div className="truncate font-mono text-[10px] text-[var(--text-tertiary)]">
                                                                {chat.id}{chat.username ? ` · @${chat.username}` : ""}
                                                            </div>
                                                        </button>
                                                    );
                                                })}
                                            </div>
                                        ) : (
                                            <div className="flex h-full min-h-[11rem] items-center justify-center px-4 text-center text-xs text-[var(--text-tertiary)]">
                                                {t("select_from_list")}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>

                            <div className="space-y-2 md:col-span-2">
                                {chatCacheMeta ? (
                                    <div className="px-1 text-[10px] leading-4 text-[var(--text-tertiary)]/80">
                                        上次缓存：{chatCacheMeta.last_cached_at ? new Date(chatCacheMeta.last_cached_at).toLocaleString() : "未缓存"} · TTL {chatCacheMeta.cache_ttl_minutes} 分钟
                                    </div>
                                ) : null}
                            </div>

                            <div className="space-y-2">
                                <label className="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)]">{t("manual_chat_id")}</label>
                                <Input
                                    placeholder={t("manual_id_placeholder")}
                                    value={showCreateDialog ? newTask.chat_id_manual : editTask.chat_id_manual}
                                    onChange={(e) => {
                                        if (showCreateDialog) {
                                            setNewTask({ ...newTask, chat_id_manual: e.target.value, chat_id: 0 });
                                        } else {
                                            setEditTask({ ...editTask, chat_id_manual: e.target.value, chat_id: 0 });
                                        }
                                    }}
                                />
                            </div>

                            <div className="space-y-2">
                                <label className="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)]">{t("delete_after")}</label>
                                <Input
                                    type="text"
                                    inputMode="numeric"
                                    placeholder={t("delete_after_placeholder")}
                                    value={showCreateDialog ? newTask.delete_after ?? "" : editTask.delete_after ?? ""}
                                    onChange={(e) => {
                                        const cleaned = e.target.value.replace(/[^0-9]/g, "");
                                        const val = cleaned === "" ? undefined : Number(cleaned);
                                        if (showCreateDialog) {
                                            setNewTask({ ...newTask, delete_after: val });
                                        } else {
                                            setEditTask({ ...editTask, delete_after: val });
                                        }
                                    }}
                                />
                            </div>
                        </div>
                    </div>

                    <div className="space-y-4">
                        <div className="flex items-center justify-between">
                            <h3 className="flex items-center gap-2 text-sm font-bold uppercase tracking-widest text-[var(--text-tertiary)]">
                                <DotsThreeVertical weight="bold" />
                                {t("action_sequence")}
                            </h3>
                            <Button
                                type="button"
                                variant="secondary"
                                size="sm"
                                onClick={showCreateDialog ? handleAddAction : handleEditAddAction}
                            >
                                + {t("add_action")}
                            </Button>
                        </div>

                        <div className="flex flex-col gap-3">
                            {(showCreateDialog ? newTask.actions : editTask.actions).map((action, index) => (
                                <div key={index} className="flex items-center gap-3 animate-scale-in">
                                    <div className="flex h-10 w-6 shrink-0 items-center justify-center border-r border-[var(--border-secondary)] font-mono text-[10px] font-bold text-[var(--text-tertiary)]">
                                        {index + 1}
                                    </div>
                                    <select
                                        className={cn(selectClassName, "w-[170px] shrink-0")}
                                        value={toActionTypeOption(action)}
                                        onChange={(e) => {
                                            const selectedType = e.target.value as ActionTypeOption;
                                            updateCurrentDialogAction(index, (currentAction) => {
                                                const currentActionId = Number(currentAction.action);
                                                const currentText = "text" in currentAction ? currentAction.text : "";
                                                const currentDice = "dice" in currentAction ? currentAction.dice : DICE_OPTIONS[0];
                                                const currentKeywords = "keywords" in currentAction ? currentAction.keywords : [];
                                                const currentRawInput = isSuccessAssertionAction(currentAction)
                                                    ? currentAction.raw_input
                                                    : currentKeywords.join(" # ");
                                                if (selectedType === "1") {
                                                    return { action: 1, text: currentText };
                                                }
                                                if (selectedType === "3") {
                                                    return { action: 3, text: currentText };
                                                }
                                                if (selectedType === "2") {
                                                    return { action: 2, dice: currentDice };
                                                }
                                                if (selectedType === "ai_vision") {
                                                    const nextActionId = currentActionId === 4 || currentActionId === 6 ? currentActionId : 6;
                                                    if (nextActionId === 6) {
                                                        return {
                                                            action: 6,
                                                            caption_pattern: currentActionId === 6 ? (currentAction as any).caption_pattern || "" : "",
                                                            captcha_lengths: currentActionId === 6 ? (currentAction as any).captcha_lengths || [] : [],
                                                            captcha_charset: currentActionId === 6 ? (currentAction as any).captcha_charset || "" : "",
                                                            captcha_case: currentActionId === 6 ? (currentAction as any).captcha_case || "preserve" : "preserve",
                                                            reply_to_message: currentActionId === 6 ? Boolean((currentAction as any).reply_to_message) : false,
                                                        };
                                                    }
                                                    return { action: 4 };
                                                }
                                                if (selectedType === "ai_poetry") {
                                                    return { action: 8 };
                                                }
                                                if (selectedType === "assert_success") {
                                                    return {
                                                        action: 9,
                                                        keywords: currentKeywords,
                                                        raw_input: currentRawInput,
                                                    };
                                                }
                                                const nextActionId = currentActionId === 5 || currentActionId === 7 ? currentActionId : 5;
                                                return { action: nextActionId as 5 | 7 };
                                            });
                                        }}
                                    >
                                        <option value="1">{sendTextLabel}</option>
                                        <option value="3">{clickTextButtonLabel}</option>
                                        <option value="2">{sendDiceLabel}</option>
                                        <option value="ai_vision">{aiVisionLabel}</option>
                                        <option value="ai_logic">{aiCalcLabel}</option>
                                        <option value="ai_poetry">{aiPoetryLabel}</option>
                                        <option value="assert_success">{assertSuccessLabel}</option>
                                    </select>

                                    <div className="min-w-0 flex-1">
                                        {action.action === 1 || action.action === 3 ? (
                                            <Input
                                                placeholder={action.action === 1 ? sendTextPlaceholder : clickButtonPlaceholder}
                                                className="h-10"
                                                value={action.text || ""}
                                                onChange={(e) => {
                                                    updateCurrentDialogAction(index, (currentAction) => ({
                                                        ...currentAction,
                                                        text: e.target.value,
                                                    }));
                                                }}
                                            />
                                        ) : null}

                                        {action.action === 2 ? (
                                            <div className="flex items-center gap-2 overflow-x-auto">
                                                {DICE_OPTIONS.map((d) => (
                                                    <Button
                                                        key={d}
                                                        type="button"
                                                        variant="secondary"
                                                        className={cn(
                                                            "h-10 w-10 shrink-0 rounded-xl px-0 text-lg",
                                                            ((action as any).dice === d)
                                                                ? "border-[var(--accent)] bg-[var(--accent-muted)] text-[var(--accent)] hover:bg-[var(--accent-muted)]"
                                                                : ""
                                                        )}
                                                        onClick={() => {
                                                            updateCurrentDialogAction(index, (currentAction) => ({
                                                                ...currentAction,
                                                                dice: d,
                                                            }));
                                                        }}
                                                    >
                                                        {d}
                                                    </Button>
                                                ))}
                                            </div>
                                        ) : null}

                                        {action.action === 4 || action.action === 6 ? (
                                            <div className="flex h-10 items-center gap-2 rounded-xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] px-3">
                                                <Robot weight="fill" size={16} className="text-[#8183ff]" />
                                                <select
                                                    className={cn(selectClassName, "h-10 w-[220px] max-w-full py-0 text-xs")}
                                                    value={action.action === 4 ? "click" : "send"}
                                                    onChange={(e) => {
                                                        const nextActionId = e.target.value === "click" ? 4 : 6;
                                                        updateCurrentDialogAction(index, (currentAction) => {
                                                            if (nextActionId === 6) {
                                                                return {
                                                                    action: 6,
                                                                    caption_pattern: currentAction.action === 6 ? currentAction.caption_pattern || "" : "",
                                                                    captcha_lengths: currentAction.action === 6 ? currentAction.captcha_lengths || [] : [],
                                                                    captcha_charset: currentAction.action === 6 ? currentAction.captcha_charset || "" : "",
                                                                    captcha_case: currentAction.action === 6 ? currentAction.captcha_case || "preserve" : "preserve",
                                                                    reply_to_message: currentAction.action === 6 ? Boolean(currentAction.reply_to_message) : false,
                                                                };
                                                            }
                                                            return { action: 4 };
                                                        });
                                                    }}
                                                >
                                                    <option value="send">{aiVisionSendModeLabel}</option>
                                                    <option value="click">{aiVisionClickModeLabel}</option>
                                                </select>
                                            </div>
                                        ) : null}

                                        {action.action === 6 ? (
                                            <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1fr)_120px]">
                                                <Input
                                                    className="h-9 text-xs"
                                                    placeholder={aiVisionCaptionPatternPlaceholder}
                                                    value={action.caption_pattern || ""}
                                                    onChange={(e) => {
                                                        updateCurrentDialogAction(index, (currentAction) => ({
                                                            action: 6,
                                                            caption_pattern: e.target.value,
                                                            captcha_lengths: currentAction.action === 6 ? currentAction.captcha_lengths || [] : [],
                                                            captcha_charset: currentAction.action === 6 ? currentAction.captcha_charset || "" : "",
                                                            captcha_case: currentAction.action === 6 ? currentAction.captcha_case || "preserve" : "preserve",
                                                            reply_to_message: currentAction.action === 6 ? Boolean(currentAction.reply_to_message) : false,
                                                        }));
                                                    }}
                                                />
                                                <Input
                                                    className="h-9 text-xs"
                                                    inputMode="numeric"
                                                    placeholder={aiVisionCaptchaLengthsPlaceholder}
                                                    value={(action.captcha_lengths || []).join(",")}
                                                    onChange={(e) => {
                                                        const lengths = e.target.value
                                                            .split(/[,#\s]+/)
                                                            .map((item) => parseInt(item, 10))
                                                            .filter((item) => Number.isInteger(item) && item > 0);
                                                        updateCurrentDialogAction(index, (currentAction) => ({
                                                            action: 6,
                                                            caption_pattern: currentAction.action === 6 ? currentAction.caption_pattern || "" : "",
                                                            captcha_lengths: lengths,
                                                            captcha_charset: currentAction.action === 6 ? currentAction.captcha_charset || "" : "",
                                                            captcha_case: currentAction.action === 6 ? currentAction.captcha_case || "preserve" : "preserve",
                                                            reply_to_message: currentAction.action === 6 ? Boolean(currentAction.reply_to_message) : false,
                                                        }));
                                                    }}
                                                />
                                                <Input
                                                    className="h-9 text-xs"
                                                    placeholder={aiVisionCaptchaCharsetPlaceholder}
                                                    value={action.captcha_charset || ""}
                                                    onChange={(e) => {
                                                        updateCurrentDialogAction(index, (currentAction) => ({
                                                            action: 6,
                                                            caption_pattern: currentAction.action === 6 ? currentAction.caption_pattern || "" : "",
                                                            captcha_lengths: currentAction.action === 6 ? currentAction.captcha_lengths || [] : [],
                                                            captcha_charset: e.target.value,
                                                            captcha_case: currentAction.action === 6 ? currentAction.captcha_case || "preserve" : "preserve",
                                                            reply_to_message: currentAction.action === 6 ? Boolean(currentAction.reply_to_message) : false,
                                                        }));
                                                    }}
                                                />
                                                <select
                                                    className={cn(selectClassName, "h-9 py-0 text-xs")}
                                                    value={action.captcha_case || "preserve"}
                                                    onChange={(e) => {
                                                        const captchaCase = e.target.value as "preserve" | "upper" | "lower";
                                                        updateCurrentDialogAction(index, (currentAction) => ({
                                                            action: 6,
                                                            caption_pattern: currentAction.action === 6 ? currentAction.caption_pattern || "" : "",
                                                            captcha_lengths: currentAction.action === 6 ? currentAction.captcha_lengths || [] : [],
                                                            captcha_charset: currentAction.action === 6 ? currentAction.captcha_charset || "" : "",
                                                            captcha_case: captchaCase,
                                                            reply_to_message: currentAction.action === 6 ? Boolean(currentAction.reply_to_message) : false,
                                                        }));
                                                    }}
                                                >
                                                    <option value="preserve">{isZh ? "保持大小写" : "Preserve case"}</option>
                                                    <option value="upper">{isZh ? "转大写" : "Uppercase"}</option>
                                                    <option value="lower">{isZh ? "转小写" : "Lowercase"}</option>
                                                </select>
                                                <label className="flex h-9 items-center gap-2 rounded-xl border border-[var(--border-secondary)] bg-[var(--bg-secondary)] px-3 text-xs text-[var(--text-secondary)] sm:col-span-2">
                                                    <input
                                                        type="checkbox"
                                                        className="h-4 w-4 accent-primary"
                                                        checked={Boolean(action.reply_to_message)}
                                                        onChange={(e) => {
                                                            updateCurrentDialogAction(index, (currentAction) => ({
                                                                action: 6,
                                                                caption_pattern: currentAction.action === 6 ? currentAction.caption_pattern || "" : "",
                                                                captcha_lengths: currentAction.action === 6 ? currentAction.captcha_lengths || [] : [],
                                                                captcha_charset: currentAction.action === 6 ? currentAction.captcha_charset || "" : "",
                                                                captcha_case: currentAction.action === 6 ? currentAction.captcha_case || "preserve" : "preserve",
                                                                reply_to_message: e.target.checked,
                                                            }));
                                                        }}
                                                    />
                                                    {isZh ? "回复到验证码图片消息" : "Reply to captcha image"}
                                                </label>
                                            </div>
                                        ) : null}

                                        {action.action === 5 || action.action === 7 ? (
                                            <div className="flex h-10 items-center gap-2 rounded-xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] px-3">
                                                <MathOperations weight="fill" size={16} className="text-amber-400" />
                                                <select
                                                    className={cn(selectClassName, "h-10 w-[220px] max-w-full py-0 text-xs")}
                                                    value={action.action === 7 ? "click" : "send"}
                                                    onChange={(e) => {
                                                        const nextActionId = e.target.value === "click" ? 7 : 5;
                                                        updateCurrentDialogAction(index, (currentAction) => ({
                                                            ...currentAction,
                                                            action: nextActionId,
                                                        }));
                                                    }}
                                                >
                                                    <option value="send">{aiCalcSendModeLabel}</option>
                                                    <option value="click">{aiCalcClickModeLabel}</option>
                                                </select>
                                            </div>
                                        ) : null}

                                        {action.action === 8 ? (
                                            <div className="flex h-10 items-center gap-2 rounded-xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] px-3">
                                                <Robot weight="fill" size={16} className="text-fuchsia-300" />
                                                <div className="text-xs font-medium text-fuchsia-200">{aiPoetryClickModeLabel}</div>
                                            </div>
                                        ) : null}

                                        {action.action === 9 ? (
                                            <div className="grid grid-cols-1 gap-2">
                                                <Input
                                                    placeholder={assertSuccessPlaceholder}
                                                    className="h-10"
                                                    value={action.raw_input}
                                                    onChange={(e) => {
                                                        const rawInput = e.target.value;
                                                        updateCurrentDialogAction(index, (currentAction) => ({
                                                            ...(isSuccessAssertionAction(currentAction) ? currentAction : { action: 9, keywords: [], raw_input: "" }),
                                                            action: 9,
                                                            raw_input: rawInput,
                                                            keywords: toSuccessKeywords(rawInput),
                                                        }));
                                                    }}
                                                />
                                            </div>
                                        ) : null}
                                    </div>

                                    <IconButton
                                        type="button"
                                        onClick={() => (showCreateDialog ? handleRemoveAction(index) : handleEditRemoveAction(index))}
                                        activeTone="danger"
                                        className="shrink-0 !h-10 !w-10 bg-[var(--danger-muted)]"
                                        aria-label={t("delete")}
                                        title={t("delete")}
                                    >
                                        <Trash weight="bold" size={16} />
                                    </IconButton>
                                </div>
                            ))}
                        </div>
                    </div>
                <TaskAdvancedSettings value={showCreateDialog ? newTask : editTask} isZh={isZh}
                        onChange={patch => showCreateDialog ? setNewTask(prev => ({ ...prev, ...patch })) : setEditTask(prev => ({ ...prev, ...patch }))} />
                </div>
            </ModalShell>

            <ModalShell
                open={Boolean(copyTaskDialog)}
                title={copyTaskDialog ? `${copyTaskDialogTitle}: ${copyTaskDialog.taskName}` : copyTaskDialogTitle}
                description={copyTaskDialogDesc}
                onClose={closeCopyTaskDialog}
                className="max-w-3xl"
                footer={
                    <div className="flex gap-3">
                        <Button variant="secondary" className="flex-1" onClick={closeCopyTaskDialog} disabled={copyingConfig}>
                            {t("close")}
                        </Button>
                        <Button className="flex-1" onClick={handleCopyTaskConfig} disabled={copyingConfig}>
                            {copyingConfig ? <Spinner className="animate-spin" /> : copyConfigAction}
                        </Button>
                    </div>
                }
            >
                <textarea
                    className={cn(textareaClassName, "h-72 font-mono text-xs")}
                    value={copyTaskDialog?.config || ""}
                    readOnly
                />
            </ModalShell>

            <ModalShell
                open={showPasteDialog}
                title={pasteTaskDialogTitle}
                description={pasteTaskDialogDesc}
                onClose={closePasteTaskDialog}
                className="max-w-3xl"
                footer={
                    <div className="flex gap-3">
                        <Button variant="secondary" className="flex-1" onClick={closePasteTaskDialog} disabled={importingPastedConfig || loading}>
                            {t("cancel")}
                        </Button>
                        <Button className="flex-1" onClick={handlePasteDialogImport} disabled={importingPastedConfig || loading}>
                            {importingPastedConfig ? <Spinner className="animate-spin" /> : importTaskAction}
                        </Button>
                    </div>
                }
            >
                <textarea
                    className={cn(textareaClassName, "h-72 font-mono text-xs")}
                    placeholder={pasteTaskDialogPlaceholder}
                    value={pasteTaskConfigInput}
                    onChange={(e) => setPasteTaskConfigInput(e.target.value)}
                />
            </ModalShell>

            <ModalShell
                open={Boolean(deleteTaskName)}
                title={t("delete")}
                description={deleteTaskName ? t("confirm_delete").replace("{name}", deleteTaskName) : t("confirm_delete")}
                onClose={() => {
                    if (!loading) {
                        setDeleteTaskName(null);
                    }
                }}
                className="max-w-md"
                footer={
                    <div className="flex gap-3">
                        <Button variant="secondary" className="flex-1" onClick={() => setDeleteTaskName(null)} disabled={loading}>
                            {t("cancel")}
                        </Button>
                        <Button className="flex-1" onClick={() => deleteTaskName && handleDeleteTask(deleteTaskName)} disabled={loading || !deleteTaskName}>
                            {loading ? <Spinner className="animate-spin" /> : t("delete")}
                        </Button>
                    </div>
                }
            >
                <div className="text-sm text-[var(--text-secondary)]">{deleteTaskName ? `${accountName} · ${deleteTaskName}` : ""}</div>
            </ModalShell>

            <ModalShell
                open={Boolean(historyTaskName)}
                title={historyTaskName ? t("task_history_logs_title").replace("{name}", historyTaskName) : t("task_history_logs")}
                description={historyTaskName ? `${accountName} · ${historyLogs.length} ${language === "zh" ? "条记录" : "records"}` : undefined}
                onClose={() => setHistoryTaskName(null)}
                className="flex h-[94dvh] max-w-[78rem] flex-col sm:h-[88vh]"
                contentClassName="min-h-0 flex-1 max-h-none overflow-hidden bg-[var(--bg-secondary)] p-0"
            >
                {historyLoading ? (
                    <div className="m-4 flex min-h-[260px] flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-[var(--border-secondary)] bg-[var(--bg-secondary)] px-6 text-center text-[var(--text-tertiary)]">
                        <Spinner className="animate-spin" size={16} />
                        <div className="text-sm font-medium text-[var(--text-primary)]">{t("loading")}</div>
                    </div>
                ) : historyLogs.length === 0 ? (
                    <div className="m-4 flex min-h-[260px] items-center justify-center rounded-2xl border border-dashed border-[var(--border-secondary)] bg-[var(--bg-secondary)] px-6 text-center text-sm text-[var(--text-tertiary)]">{t("task_history_empty")}</div>
                ) : selectedHistoryLog ? (
                    <div className="grid h-full min-h-0 grid-cols-1 grid-rows-[auto,minmax(0,1fr)] lg:grid-cols-[18rem,minmax(0,1fr)] lg:grid-rows-1">
                        <aside className="flex min-h-0 flex-col border-b border-[var(--border-secondary)] bg-[var(--bg-tertiary)] p-2 lg:border-b-0 lg:border-r lg:p-3">
                            <div className="mb-2 hidden lg:block">
                                <div className="text-xs font-bold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">{isZh ? "历史运行" : "Runs"}</div>
                                <div className="mt-1 text-sm font-semibold text-[var(--text-primary)]">{historyLogs.length} {isZh ? "条记录" : "records"}</div>
                            </div>
                            <div className="flex gap-2 overflow-x-auto custom-scrollbar pb-1 lg:min-h-0 lg:flex-1 lg:flex-col lg:space-y-2 lg:overflow-x-visible lg:overflow-y-auto lg:pb-0 lg:pr-1">
                                {historyLogs.map((log, index) => {
                                    const diagnostics = getHistoryDiagnostics(log, isZh);
                                    const summaryParts = compactRunSummaryParts(log.run_summary, isZh);
                                    const active = index === selectedHistoryIndex;
                                    return (
                                        <button
                                            key={`${log.time}-${index}`}
                                            type="button"
                                            onClick={() => setSelectedHistoryIndex(index)}
                                            className={cn(
                                                "w-[220px] shrink-0 rounded-2xl border px-3 py-2 text-left transition-colors lg:w-full lg:py-2.5",
                                                active ? "border-[var(--accent)] bg-[var(--accent-muted)]" : "border-[var(--border-secondary)] bg-[var(--bg-primary)] hover:border-[var(--text-tertiary)]"
                                            )}
                                        >
                                            <div className="flex items-center justify-between gap-2">
                                                <span className="font-mono text-xs text-[var(--text-primary)]">{formatFlowDateTime(log.time, language)}</span>
                                                <StatusBadge tone={runSummaryTone(log.run_summary, log.success) as any}>
                                                    {log.run_summary ? runSummaryStatusLabel(log.run_summary, isZh) : (log.success ? t("success") : t("failure"))}
                                                </StatusBadge>
                                            </div>
                                            <div className="mt-1.5 line-clamp-1 text-xs leading-5 text-[var(--text-secondary)] lg:mt-2 lg:line-clamp-2">
                                                {log.message || diagnostics.directReason || (isZh ? "无结果消息" : "No result message")}
                                            </div>
                                            <div className="mt-1.5 text-[10px] text-[var(--text-tertiary)] lg:mt-2">
                                                {diagnostics.completedSteps}/{diagnostics.totalSteps || "-"} {isZh ? "步骤" : "steps"} · {diagnostics.duration}
                                            </div>
                                            {summaryParts.length > 0 ? (
                                                <div className="hidden lg:mt-2 lg:line-clamp-2 lg:block lg:text-[10px] lg:text-[var(--text-tertiary)]">
                                                    {summaryParts.slice(0, 3).join(" · ")}
                                                </div>
                                            ) : null}
                                        </button>
                                    );
                                })}
                            </div>
                        </aside>

                        <section className="flex min-h-0 min-w-0 flex-col">
                            <div className="mx-3 mt-3 flex shrink-0 flex-col gap-2 rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-primary)] p-2 md:mx-5 md:mt-5 md:flex-row md:items-center md:justify-between md:p-3">
                                <div className="flex flex-nowrap gap-1 overflow-x-auto custom-scrollbar pb-0.5 md:flex-wrap md:gap-2 md:overflow-visible md:pb-0">
                                    {([
                                        ["read", isZh ? "阅读视图" : "Read"],
                                        ["ai", isZh ? "AI 排查视图" : "AI Debug"],
                                        ["json", isZh ? "原始 JSON" : "Raw JSON"],
                                    ] as Array<[HistoryLogView, string]>).map(([view, label]) => (
                                        <Button key={view} size="sm" variant={historyLogView === view ? "default" : "ghost"} onClick={() => setHistoryLogView(view)}>
                                            {label}
                                        </Button>
                                    ))}
                                </div>
                                <div className="flex flex-nowrap gap-1 overflow-x-auto custom-scrollbar pb-0.5 md:flex-wrap md:gap-2 md:overflow-visible md:pb-0">
                                    {historyLogView === "read" ? (
                                        <>
                                            <Button size="sm" variant={historyFailureOnly ? "default" : "secondary"} onClick={() => setHistoryFailureOnly((value) => !value)}>
                                                {isZh ? "仅看失败点" : "Failures only"}
                                            </Button>
                                            <Button size="sm" variant="secondary" onClick={() => {
                                                setHistoryFailureOnly(false);
                                                setHistoryExpandDetails((value) => !value);
                                            }}>
                                                {historyExpandDetails ? (isZh ? "折叠详情" : "Collapse") : (isZh ? "展开全部" : "Expand all")}
                                            </Button>
                                        </>
                                    ) : historyLogView === "ai" ? (
                                        <Button
                                            size="sm"
                                            onClick={() => historyTaskName && handleCopyHistoryText(formatHistoryForAi({ log: selectedHistoryLog, accountName, taskName: historyTaskName, language, isZh }), isZh ? "AI 排查日志" : "AI debug log")}
                                        >
                                            <Copy weight="bold" size={14} />
                                            {isZh ? "复制 AI 排查日志" : "Copy AI Log"}
                                        </Button>
                                    ) : (
                                        <Button
                                            size="sm"
                                            onClick={() => historyTaskName && handleCopyHistoryText(formatHistoryRawJson(selectedHistoryLog, accountName, historyTaskName), isZh ? "原始日志" : "raw log")}
                                        >
                                            <Copy weight="bold" size={14} />
                                            {isZh ? "复制原始日志" : "Copy Raw"}
                                        </Button>
                                    )}
                                </div>
                            </div>

                            <div className="min-h-0 flex-1 overflow-y-auto p-3 custom-scrollbar md:p-5">
                                {historyLogView === "read" ? (
                                <div className="space-y-4">
                                    {selectedHistoryLog.run_summary ? (
                                        <div className="rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-primary)] px-4 py-3">
                                            <div className="flex flex-wrap items-center gap-2">
                                                <StatusBadge tone={runSummaryTone(selectedHistoryLog.run_summary, selectedHistoryLog.success) as any}>
                                                    {runSummaryStatusLabel(selectedHistoryLog.run_summary, isZh)}
                                                </StatusBadge>
                                                <span className="text-sm font-semibold text-[var(--text-primary)]">
                                                    {isZh ? "运行细节" : "Run details"}
                                                </span>
                                            </div>
                                            <div className="mt-3 flex flex-wrap gap-2">
                                                {compactRunSummaryParts(selectedHistoryLog.run_summary, isZh).map((part) => (
                                                    <span key={part} className="rounded-lg border border-[var(--border-secondary)] bg-[var(--bg-secondary)] px-2 py-1 text-xs text-[var(--text-secondary)]">
                                                        {part}
                                                    </span>
                                                ))}
                                                {compactRunSummaryParts(selectedHistoryLog.run_summary, isZh).length === 0 ? (
                                                    <span className="text-xs text-[var(--text-tertiary)]">{isZh ? "暂无额外计数" : "No extra counters"}</span>
                                                ) : null}
                                            </div>
                                        </div>
                                    ) : null}
                                    {selectedHistoryLog.message ? (
                                        <div className="rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-primary)] px-4 py-3 text-sm text-[var(--text-secondary)] break-words">
                                            <span className="font-semibold text-[var(--text-primary)]">{isZh ? "机器人消息：" : "Bot message: "}</span>{selectedHistoryLog.message}
                                        </div>
                                    ) : null}
                                    {selectedHistoryLog.flow_items && selectedHistoryLog.flow_items.length > 0 ? (
                                        <HistoryFlowGroups
                                            flowItems={selectedHistoryLog.flow_items}
                                            isZh={isZh}
                                            language={language}
                                            t={t}
                                            failureOnly={historyFailureOnly}
                                            expandDetails={historyExpandDetails}
                                        />
                                    ) : selectedHistoryLog.flow_logs && selectedHistoryLog.flow_logs.length > 0 ? (
                                        <pre className="whitespace-pre-wrap rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-primary)] p-4 font-mono text-xs leading-6 text-[var(--text-primary)]">
                                            {selectedHistoryLog.flow_logs.join("\n")}
                                        </pre>
                                    ) : (
                                        <div className="rounded-2xl border border-dashed border-[var(--border-secondary)] bg-[var(--bg-primary)] px-4 py-4 text-sm text-[var(--text-secondary)]">
                                            {selectedHistoryLog.message || t("task_history_no_flow")}
                                        </div>
                                    )}
                                    {selectedHistoryLog.flow_truncated && (
                                        <div className="rounded-2xl border border-amber-500/20 bg-[var(--bg-tertiary)] px-4 py-3 text-xs text-amber-300">
                                            {t("task_history_truncated").replace("{count}", String(selectedHistoryLog.flow_line_count || 0))}
                                        </div>
                                    )}
                                </div>
                            ) : historyLogView === "ai" ? (
                                <pre className="whitespace-pre-wrap rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-primary)] p-4 font-mono text-xs leading-6 text-[var(--text-primary)]">
                                    {historyTaskName ? formatHistoryForAi({ log: selectedHistoryLog, accountName, taskName: historyTaskName, language, isZh }) : ""}
                                </pre>
                            ) : (
                                <pre className="whitespace-pre-wrap rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-primary)] p-4 font-mono text-xs leading-6 text-[var(--text-primary)]">
                                    {historyTaskName ? formatHistoryRawJson(selectedHistoryLog, accountName, historyTaskName) : ""}
                                </pre>
                            )}
                            </div>
                        </section>
                    </div>
                ) : null}
            </ModalShell>

        </div>
    );
}
