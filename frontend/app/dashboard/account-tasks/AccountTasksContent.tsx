"use client";

import { useEffect, useState, memo, useCallback, useMemo, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ensureAccessToken, logout } from "../../../lib/auth";
import {
    listSignTasks,
    deleteSignTask,
    runSignTask,
    getSignTaskHistory,
    getAccountChats,
    refreshAccountChats,
    searchAccountChats,
    createSignTask,
    updateSignTask,
    exportSignTask,
    importSignTask,
    getSchedulerStatus,
    SignTask,
    SignTaskFlowItem,
    SignTaskHistoryItem,
    ChatInfo,
    CreateSignTaskRequest,
    SchedulerStatus,
    SignTaskAction,
} from "../../../lib/api";
import {
    Plus,
    Play,
    PencilSimple,
    Trash,
    Spinner,
    Clock,
    ChatCircleText,
    Hourglass,
    ArrowClockwise,
    ListDashes,
    DotsThreeVertical,
    Robot,
    MathOperations,
    Copy,
    ClipboardText,
    Lightning,
    CaretLeft,
    Gear,
    SignOut
} from "@phosphor-icons/react";
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

const DAY_MS = 24 * 60 * 60 * 1000;

const flowStageLabel = (stage: string, isZh: boolean) => {
    if (isZh) {
        switch (stage) {
            case "task": return "任务";
            case "session": return "会话";
            case "preheat": return "预热";
            case "action": return "动作";
            case "message": return "消息";
            case "result": return "结果";
            default: return "步骤";
        }
    }
    switch (stage) {
        case "task": return "Task";
        case "session": return "Session";
        case "preheat": return "Preheat";
        case "action": return "Action";
        case "message": return "Message";
        case "result": return "Result";
        default: return "Step";
    }
};

const flowStageTone = (stage: string) => {
    switch (stage) {
        case "preheat": return "text-violet-300 border-violet-500/20 bg-violet-500/10";
        case "action": return "text-cyan-300 border-cyan-500/20 bg-cyan-500/10";
        case "result": return "text-emerald-300 border-emerald-500/20 bg-emerald-500/10";
        case "session": return "text-sky-300 border-sky-500/20 bg-sky-500/10";
        case "message": return "text-amber-300 border-amber-500/20 bg-amber-500/10";
        default: return "text-[var(--text-tertiary)] border-[var(--border-secondary)] bg-[var(--bg-tertiary)]";
    }
};

const flowLevelTone = (level?: string) => {
    switch (level) {
        case "error": return "border-red-500/20 bg-red-500/8";
        case "warning": return "border-amber-500/20 bg-amber-500/8";
        case "success": return "border-emerald-500/20 bg-emerald-500/8";
        default: return "border-[var(--border-secondary)] bg-[var(--bg-primary)]";
    }
};

type TaskHistoryStepGroup = {
    index: number;
    title: string;
    items: SignTaskFlowItem[];
};

const getTaskHistoryStepStatus = (items: SignTaskFlowItem[]) => {
    if (items.some((item) => item.level === "error")) {
        return "failed" as const;
    }
    if (items.some((item) => item.event === "action_completed")) {
        return "success" as const;
    }
    return "running" as const;
};

const renderFlowItemList = (items: SignTaskFlowItem[], isZh: boolean, language: string) => (
    <div className="space-y-2 md:max-w-[46rem]">
        {items.map((item, lineIndex) => (
            <div key={`${item.ts}-${lineIndex}`} className={cn("grid grid-cols-[72px,78px,minmax(0,1fr)] gap-3 rounded-2xl border px-3 py-2.5", flowLevelTone(item.level))}>
                <span className="pt-1 text-[10px] font-medium tabular-nums text-[var(--text-tertiary)]">
                    {item.ts ? new Date(item.ts).toLocaleTimeString(language === "zh" ? "zh-CN" : "en-US", { hour12: false }) : "--:--:--"}
                </span>
                <span className={cn("flex h-7 items-center justify-center rounded-xl border text-[10px] font-semibold tracking-[0.08em] select-none", flowStageTone(item.stage))}>
                    {flowStageLabel(item.stage, isZh)}
                </span>
                <div className="min-w-0 space-y-1 pt-1">
                    <div className="break-all text-[var(--text-primary)]">{item.text}</div>
                    {item.meta && Object.keys(item.meta).length > 0 ? (
                        <div className="text-[10px] text-[var(--text-tertiary)]">
                            {Object.entries(item.meta).map(([key, value]) => `${key}: ${String(value)}`).join(" · ")}
                        </div>
                    ) : null}
                </div>
            </div>
        ))}
    </div>
);

const HistoryFlowGroups = ({
    flowItems,
    isZh,
    language,
    t,
}: {
    flowItems: SignTaskFlowItem[];
    isZh: boolean;
    language: string;
    t: (key: string) => string;
}) => {
    const stepGroups = groupHistoryFlowItemsByStep(flowItems, isZh);
    if (stepGroups.length === 0) {
        return renderFlowItemList(flowItems, isZh, language);
    }

    return (
        <div className="space-y-3 md:max-w-[46rem]">
            {stepGroups.map((group) => {
                const status = getTaskHistoryStepStatus(group.items);
                return (
                    <div key={`step-${group.index}-${group.items[0]?.ts ?? group.index}`} className="overflow-hidden rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-primary)]">
                        <div className="flex flex-col gap-2 border-b border-[var(--border-secondary)] bg-[var(--bg-tertiary)] px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between">
                            <div className="min-w-0 space-y-1">
                                <div className="text-[11px] font-semibold text-[var(--text-primary)] break-all">{group.title}</div>
                                <div className="text-[10px] text-[var(--text-tertiary)]">
                                    {group.items.length} {isZh ? "条日志" : "events"}
                                </div>
                            </div>
                            <StatusBadge tone={status === "failed" ? "danger" : status === "success" ? "success" : "warning"}>
                                {status === "failed"
                                    ? t("failure")
                                    : status === "success"
                                        ? t("success")
                                        : (isZh ? "进行中" : "Running")}
                            </StatusBadge>
                        </div>
                        <div className="space-y-2 p-3">
                            {renderFlowItemList(group.items, isZh, language)}
                        </div>
                    </div>
                );
            })}
        </div>
    );
};

const formatHistoryStepTitle = (index: number, firstItem: SignTaskFlowItem, isZh: boolean) => {
    const actionText = firstItem.meta?.action;
    if (typeof actionText === "string" && actionText.trim()) {
        return `${isZh ? "步骤" : "Step"} ${index} · ${actionText.trim()}`;
    }
    const itemText = firstItem.text?.trim();
    if (itemText) {
        return `${isZh ? "步骤" : "Step"} ${index} · ${itemText}`;
    }
    return `${isZh ? "步骤" : "Step"} ${index}`;
};

const groupHistoryFlowItemsByStep = (flowItems: SignTaskFlowItem[] | undefined, isZh: boolean): TaskHistoryStepGroup[] => {
    if (!flowItems || flowItems.length === 0) {
        return [];
    }

    const groups: TaskHistoryStepGroup[] = [];
    let currentGroup: TaskHistoryStepGroup | null = null;

    const finalizeCurrentGroup = () => {
        if (!currentGroup || currentGroup.items.length === 0) return;
        groups.push(currentGroup);
        currentGroup = null;
    };

    for (const item of flowItems) {
        const isActionItem = item.stage === "action" || item.event === "action_started" || item.event === "action_completed";
        if (!isActionItem) {
            continue;
        }

        if (item.event === "action_started") {
            finalizeCurrentGroup();
            const nextIndex = groups.length + 1;
            currentGroup = {
                index: nextIndex,
                title: formatHistoryStepTitle(nextIndex, item, isZh),
                items: [item],
            };
            continue;
        }

        if (!currentGroup) {
            const nextIndex = groups.length + 1;
            currentGroup = {
                index: nextIndex,
                title: formatHistoryStepTitle(nextIndex, item, isZh),
                items: [item],
            };
            continue;
        }

        currentGroup.items.push(item);
    }

    finalizeCurrentGroup();
    return groups;
};

type TaskFilterKey = "all" | "enabled" | "disabled" | "success" | "failed" | "pending" | "unregistered";

type ActionTypeOption = "1" | "2" | "3" | "ai_vision" | "ai_logic" | "ai_poetry" | "assert_success";

type SuccessAssertionFormAction = { action: 9; keywords: string[]; raw_input: string };
type TaskFormAction = Exclude<SignTaskAction, { action: 9; keywords: string[] }> | SuccessAssertionFormAction;

const isSuccessAssertionAction = (action: TaskFormAction | SignTaskAction | null | undefined): action is SuccessAssertionFormAction | { action: 9; keywords: string[] } => {
    return Number(action?.action) === 9;
};

type TaskFormState = {
    name?: string;
    sign_at: string;
    random_minutes: number;
    retry_count: number;
    chat_id: number;
    chat_id_manual: string;
    chat_name: string;
    actions: TaskFormAction[];
    delete_after: number | undefined;
    action_interval: number;
    execution_mode: "fixed" | "range";
    range_start: string;
    range_end: string;
};

const defaultTaskAction = (): TaskFormAction => ({ action: 1, text: "" });
const toSuccessKeywords = (value: string) => value.split("#").map((item) => item.trim()).filter(Boolean);
const normalizeTaskActions = (actions: TaskFormAction[]): SignTaskAction[] => actions.map((action) => {
    if (isSuccessAssertionAction(action)) {
        return { action: 9, keywords: toSuccessKeywords(action.raw_input) };
    }
    return action;
});
const toTaskFormAction = (action: SignTaskAction): TaskFormAction => {
    if (isSuccessAssertionAction(action)) {
        return { ...action, raw_input: action.keywords.join(" # ") };
    }
    return action;
};

const DICE_OPTIONS = [
    "\uD83C\uDFB2",
    "\uD83C\uDFAF",
    "\uD83C\uDFC0",
    "\u26BD",
    "\uD83C\uDFB3",
    "\uD83C\uDFB0",
] as const;

// Memoized Task Item Component
const TaskItem = memo(({ task, loading, isRunning, schedulerItem, schedulerTimezone, onEdit, onRun, onViewLogs, onCopy, onDelete, t, language }: {
    task: SignTask;
    loading: boolean;
    isRunning: boolean;
    schedulerItem?: SchedulerStatus["sign_tasks"][number];
    schedulerTimezone?: string;
    onEdit: (task: SignTask) => void;
    onRun: (name: string) => void;
    onViewLogs: (task: SignTask) => void;
    onCopy: (name: string) => void;
    onDelete: (name: string) => void;
    t: (key: string) => string;
    language: string;
}) => {
    const copyTaskTitle = language === "zh" ? "复制任务" : "Copy Task";
    const moreActionsTitle = language === "zh" ? "更多操作" : "More actions";
    const [showActions, setShowActions] = useState(false);
    const menuRef = useRef<HTMLDivElement | null>(null);

    useEffect(() => {
        if (!showActions) return;

        const handlePointerDown = (event: MouseEvent) => {
            if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
                setShowActions(false);
            }
        };

        const handleEscape = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                setShowActions(false);
            }
        };

        document.addEventListener("mousedown", handlePointerDown);
        document.addEventListener("keydown", handleEscape);
        return () => {
            document.removeEventListener("mousedown", handlePointerDown);
            document.removeEventListener("keydown", handleEscape);
        };
    }, [showActions]);

    const closeActions = () => setShowActions(false);

    return (
        <div className="glass-panel group flex h-full flex-col p-4 transition-all hover:border-[var(--accent)] md:p-5">
            <div className="min-w-0 flex items-start gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-muted)] text-[var(--accent)]">
                    <ChatCircleText weight="bold" size={20} />
                </div>
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                        <h3 className="truncate text-sm font-bold" title={task.name}>{task.name}</h3>
                        <span className="rounded border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] px-1.5 py-0.5 font-mono text-[9px] text-[var(--text-tertiary)]">
                            {task.chats[0]?.chat_id || "-"}
                        </span>
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                        <StatusBadge tone={task.enabled ? "success" : "warning"}>
                            {task.enabled ? (language === "zh" ? "启用" : "Enabled") : (language === "zh" ? "停用" : "Disabled")}
                        </StatusBadge>
                        <StatusBadge tone={schedulerItem?.job_exists ? "success" : "danger"}>
                            {schedulerItem?.job_exists ? (language === "zh" ? "已注册" : "Registered") : (language === "zh" ? "未注册" : "Missing")}
                        </StatusBadge>
                        {task.execution_mode === "range" && schedulerItem?.execution_job_exists && schedulerItem?.next_scheduled_at ? (
                            <StatusBadge tone="primary">
                                {language === "zh" ? "已调度" : "Scheduled"}
                            </StatusBadge>
                        ) : null}
                    </div>
                </div>
            </div>

            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] px-4 py-3">
                    <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">
                        {language === "zh" ? "调度" : "Schedule"}
                    </div>
                    <div className="mt-2 flex items-center gap-2 text-[var(--text-primary)]">
                        <Clock weight="bold" size={14} />
                        <span className="font-mono text-xs font-semibold uppercase tracking-wide">
                            {task.execution_mode === "range" && task.range_start && task.range_end
                                ? `${task.range_start} - ${task.range_end}`
                                : task.sign_at}
                        </span>
                    </div>
                    {task.random_seconds > 0 ? (
                        <div className="mt-2 flex items-center gap-1 text-xs text-[var(--accent)]">
                            <Hourglass weight="bold" size={12} />
                            <span>~{Math.round(task.random_seconds / 60)}m</span>
                        </div>
                    ) : null}
                </div>

                <div className="rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] px-4 py-3">
                    <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">
                        {language === "zh" ? "下一次执行" : "Next run"}
                    </div>
                    {task.execution_mode === "range" && schedulerItem?.execution_job_exists && schedulerItem?.next_scheduled_at ? (
                        <div className="mt-2 text-xs text-[var(--text-primary)]">
                            <span className="text-[var(--text-tertiary)]">
                                {language === "zh" ? "预计: " : "Scheduled: "}
                            </span>
                            <span className="font-semibold">
                                {new Date(schedulerItem.next_scheduled_at).toLocaleString(language === "zh" ? "zh-CN" : "en-US", {
                                    timeZone: schedulerTimezone || "Asia/Shanghai",
                                    month: "2-digit",
                                    day: "2-digit",
                                    hour: "2-digit",
                                    minute: "2-digit",
                                    second: "2-digit"
                                })}
                            </span>
                        </div>
                    ) : (
                        <div className="mt-2 break-words text-xs text-[var(--text-primary)]">
                            {schedulerItem?.effective_next_run
                                ? new Date(schedulerItem.effective_next_run).toLocaleString(language === "zh" ? "zh-CN" : "en-US", {
                                    timeZone: schedulerTimezone || "Asia/Shanghai"
                                })
                                : (language === "zh" ? "未计划" : "Not scheduled")}
                        </div>
                    )}
                </div>
            </div>

            <div className="mt-4 rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] px-4 py-3">
                <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">
                    {language === "zh" ? "最近执行" : "Last run"}
                </div>
                {task.last_run ? (
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                        <StatusBadge tone={task.last_run.success ? "success" : "danger"}>
                            {task.last_run.success ? t("success") : t("failure")}
                        </StatusBadge>
                        <span className="font-mono text-[11px] text-[var(--text-tertiary)]">
                            {new Date(task.last_run.time).toLocaleString(language === "zh" ? "zh-CN" : "en-US", {
                                month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"
                            })}
                        </span>
                    </div>
                ) : (
                    <div className="mt-2">
                        <StatusBadge tone="neutral">{t("no_data")}</StatusBadge>
                    </div>
                )}
            </div>

            <div className="mt-4 flex flex-col gap-3 border-t border-[var(--border-secondary)] pt-4 sm:flex-row sm:items-center sm:justify-between">
                <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => onEdit(task)}
                    disabled={loading || isRunning}
                    className="sm:self-start"
                >
                    <PencilSimple weight="bold" size={14} />
                    {t("edit")}
                </Button>

                <div ref={menuRef} className="relative self-start sm:self-auto">
                    <div className="flex items-center gap-2">
                        <Button
                            size="sm"
                            onClick={() => {
                                closeActions();
                                onRun(task.name);
                            }}
                            disabled={loading || isRunning}
                        >
                            {isRunning ? <Spinner className="animate-spin" size={14} /> : <Play weight="fill" size={14} />}
                            {t("run")}
                        </Button>
                        <IconButton
                            onClick={() => setShowActions((prev) => !prev)}
                            disabled={loading || isRunning}
                            activeTone="primary"
                            className="!h-8 !w-8"
                            title={moreActionsTitle}
                            aria-label={moreActionsTitle}
                        >
                            <DotsThreeVertical weight="bold" size={14} />
                        </IconButton>
                    </div>

                    {showActions ? (
                        <div className="absolute right-0 top-full z-20 mt-2 min-w-[180px] rounded-2xl border border-[var(--border-primary)] bg-[var(--bg-primary)] p-1.5 shadow-[var(--shadow-lg)]">
                            <button
                                type="button"
                                className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm text-[var(--text-primary)] transition-colors hover:bg-[var(--bg-tertiary)] disabled:cursor-not-allowed disabled:opacity-50"
                                onClick={() => {
                                    closeActions();
                                    onViewLogs(task);
                                }}
                                disabled={loading || isRunning}
                            >
                                <ListDashes weight="bold" size={14} />
                                <span>{t("task_history_logs")}</span>
                            </button>
                            <button
                                type="button"
                                className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm text-[var(--text-primary)] transition-colors hover:bg-[var(--bg-tertiary)] disabled:cursor-not-allowed disabled:opacity-50"
                                onClick={() => {
                                    closeActions();
                                    onCopy(task.name);
                                }}
                                disabled={loading || isRunning}
                            >
                                <Copy weight="bold" size={14} />
                                <span>{copyTaskTitle}</span>
                            </button>
                            <button
                                type="button"
                                className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm text-[var(--danger)] transition-colors hover:bg-[var(--danger-muted)] disabled:cursor-not-allowed disabled:opacity-50"
                                onClick={() => {
                                    closeActions();
                                    onDelete(task.name);
                                }}
                                disabled={loading || isRunning}
                            >
                                <Trash weight="bold" size={14} />
                                <span>{t("delete")}</span>
                            </button>
                        </div>
                    ) : null}
                </div>
            </div>
        </div>
    );
});

TaskItem.displayName = "TaskItem";

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
    const [liveMonitorTaskName, setLiveMonitorTaskName] = useState<string | null>(null);
    const [refreshingChats, setRefreshingChats] = useState(false);
    const [chatCacheMeta, setChatCacheMeta] = useState<{ last_cached_at?: string | null; cache_ttl_minutes: number; expired: boolean; count: number } | null>(null);
    const [historyTaskName, setHistoryTaskName] = useState<string | null>(null);
    const [historyLogs, setHistoryLogs] = useState<SignTaskHistoryItem[]>([]);
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
        action_interval: 1,
        execution_mode: "range",
        range_start: "09:00",
        range_end: "18:00",
    });

    // 缂傚倸鍊搁崐鎼佸磹瑜版帗鍋嬮柣鎰仛椤愯姤銇勯幇鍓佹偧妞も晝鍏橀幃褰掑炊閵娿儳绁峰銈庡亖閸婃繈骞冨Δ鍛仺婵炲牊瀵ч弫顖炴⒑娴兼瑧鐣虫俊顐㈠閵?
    const [showEditDialog, setShowEditDialog] = useState(false);
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
        action_interval: 1,
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
        { value: "enabled", label: isZh ? "启用中" : "Enabled" },
        { value: "disabled", label: isZh ? "停用中" : "Disabled" },
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
        if (!token || !historyTaskName) return;
        const timer = setInterval(async () => {
            try {
                const [logs, latestTasks, latestSchedulerStatus] = await Promise.all([
                    getSignTaskHistory(historyTaskName, accountName, 30),
                    listSignTasks(accountName),
                    getSchedulerStatus(accountName),
                ]);
                setHistoryLogs(logs);
                setTasks(latestTasks);
                setSchedulerStatus(latestSchedulerStatus);
            } catch {}
        }, 2000);
        return () => clearInterval(timer);
    }, [token, historyTaskName, accountName]);

    useEffect(() => {
        if (!token || !liveMonitorTaskName) return;
        let closedByCleanup = false;
        let completionNotified = false;
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const host = window.location.host;
        const wsParams = new URLSearchParams({ token, account_name: accountName });
        const wsUrl = `${protocol}//${host}/api/sign-tasks/ws/${liveMonitorTaskName}?${wsParams.toString()}`;
        const ws = new WebSocket(wsUrl);

        ws.onmessage = async (event) => {
            const data = JSON.parse(event.data);
            if (data.type === "done") {
                completionNotified = true;
                setRunningTaskName(null);
                setLiveMonitorTaskName(null);
                try {
                    const currentHistoryTaskName = historyTaskNameRef.current;
                    const [latestTasks, latestRunLogs, currentHistoryLogs, latestSchedulerStatus] = await Promise.all([
                        listSignTasks(accountName),
                        getSignTaskHistory(liveMonitorTaskName, accountName, 1),
                        currentHistoryTaskName ? getSignTaskHistory(currentHistoryTaskName, accountName, 30) : Promise.resolve(null),
                        getSchedulerStatus(accountName),
                    ]);
                    setTasks(latestTasks);
                    setSchedulerStatus(latestSchedulerStatus);
                    if (currentHistoryLogs) {
                        setHistoryLogs(currentHistoryLogs);
                    }
                    const latestEntry = latestRunLogs?.[0];
                    if (latestEntry) {
                        addToast(
                            latestEntry.success
                                ? (isZh ? `任务 ${liveMonitorTaskName} 执行成功` : `Task ${liveMonitorTaskName} succeeded`)
                                : (isZh ? `任务 ${liveMonitorTaskName} 执行失败` : `Task ${liveMonitorTaskName} failed`),
                            latestEntry.success ? "success" : "error"
                        );
                    } else {
                        addToast(
                            isZh ? `任务 ${liveMonitorTaskName} 已结束` : `Task ${liveMonitorTaskName} finished`,
                            "success"
                        );
                    }
                } catch {
                    addToast(
                        isZh ? `任务 ${liveMonitorTaskName} 已结束` : `Task ${liveMonitorTaskName} finished`,
                        "success"
                    );
                }
            }
        };

        ws.onerror = () => {
            if (!closedByCleanup) {
                setRunningTaskName(null);
                setLiveMonitorTaskName(null);
            }
        };

        ws.onclose = () => {
            if (!closedByCleanup && !completionNotified) {
                setRunningTaskName(null);
                setLiveMonitorTaskName(null);
            }
        };

        return () => {
            closedByCleanup = true;
            ws.close();
        };
    }, [token, liveMonitorTaskName, accountName, addToast, isZh]);

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

    const handleShowTaskHistory = async (task: SignTask) => {
        if (!token) return;
        setHistoryTaskName(task.name);
        setHistoryLogs([]);
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
                chats: [{
                    chat_id: chatId,
                    name: newTask.chat_name || t("chat_default_name").replace("{id}", String(chatId)),
                    actions: normalizeTaskActions(newTask.actions),
                    delete_after: newTask.delete_after,
                    action_interval: newTask.action_interval,
                }],
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
                action_interval: 1,
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
            action_interval: chat?.action_interval || 1,
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

            await updateSignTask(editingTaskName, {
                sign_at: editTask.sign_at,
                random_seconds: editTask.random_minutes * 60,
                retry_count: editTask.retry_count,
                chats: [{
                    chat_id: chatId,
                    name: editTask.chat_name || t("chat_default_name").replace("{id}", String(chatId)),
                    actions: normalizeTaskActions(editTask.actions),
                    delete_after: editTask.delete_after,
                    action_interval: editTask.action_interval,
                }],
                execution_mode: editTask.execution_mode,
                range_start: editTask.range_start,
                range_end: editTask.range_end,
            }, accountName);

            addToast(t("update_success"), "success");
            setShowEditDialog(false);
            await loadData();
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
                    return schedulerItem?.job_exists === false;
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
                                        <span className="ml-2">{language === "zh" ? "启用任务" : "Enabled"}</span>
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
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                        <div className="flex flex-wrap items-center gap-3">
                            <h2 className="text-base font-semibold text-[var(--text-primary)]">{language === "zh" ? "任务列表" : "Task list"}</h2>
                            <div className="text-xs text-[var(--text-tertiary)]">
                                {language === "zh" ? `当前显示 ${filteredTasks.length} / ${tasks.length}` : `Showing ${filteredTasks.length} / ${tasks.length}`}
                            </div>
                            {runningTaskName ? (
                                <StatusBadge tone="success" className="px-3 py-1 text-[10px]">
                                    {language === "zh" ? `运行中：${runningTaskName}` : `Running: ${runningTaskName}`}
                                </StatusBadge>
                            ) : null}
                        </div>
                        <div className="flex flex-nowrap items-center gap-2 self-start lg:self-center">
                            <select
                                id="task-filter-select"
                                value={taskFilter}
                                onChange={(e) => setTaskFilter(e.target.value as TaskFilterKey)}
                                className="h-10 min-w-[160px] rounded-xl border border-[var(--border-secondary)] bg-[var(--bg-secondary)] px-3 text-sm text-[var(--text-primary)] outline-none transition-colors focus:border-[var(--accent)] sm:min-w-[190px]"
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

                        <FormField label={t("action_interval")} htmlFor="task-action-interval">
                            <Input
                                id="task-action-interval"
                                type="text"
                                inputMode="numeric"
                                value={showCreateDialog ? newTask.action_interval : editTask.action_interval}
                                onChange={(e) => {
                                    const cleaned = e.target.value.replace(/[^0-9]/g, "");
                                    const raw = cleaned === "" ? 0 : parseInt(cleaned, 10);
                                    const val = Number.isNaN(raw) ? 0 : raw;
                                    if (showCreateDialog) {
                                        setNewTask({ ...newTask, action_interval: val });
                                    } else {
                                        setEditTask({ ...editTask, action_interval: val });
                                    }
                                }}
                            />
                        </FormField>

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
                                                    return { action: nextActionId as 4 | 6 };
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
                                                        updateCurrentDialogAction(index, (currentAction) => ({
                                                            ...currentAction,
                                                            action: nextActionId,
                                                        }));
                                                    }}
                                                >
                                                    <option value="send">{aiVisionSendModeLabel}</option>
                                                    <option value="click">{aiVisionClickModeLabel}</option>
                                                </select>
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
                                            <Input
                                                placeholder={assertSuccessPlaceholder}
                                                className="h-10"
                                                value={action.raw_input}
                                                onChange={(e) => {
                                                    const rawInput = e.target.value;
                                                    updateCurrentDialogAction(index, () => ({
                                                        action: 9,
                                                        raw_input: rawInput,
                                                        keywords: toSuccessKeywords(rawInput),
                                                    }));
                                                }}
                                            />
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
                className="max-w-[52rem]"
                contentClassName="max-h-[78vh] overflow-y-auto bg-[var(--bg-secondary)] p-4 font-mono text-[12px] leading-6 custom-scrollbar md:p-5"
            >
                {historyLoading ? (
                    <div className="flex min-h-[220px] flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-[var(--border-secondary)] bg-[var(--bg-secondary)] px-6 text-center text-[var(--text-tertiary)]">
                        <Spinner className="animate-spin" size={16} />
                        <div className="text-sm font-medium text-[var(--text-primary)]">{t("loading")}</div>
                    </div>
                ) : historyLogs.length === 0 ? (
                    <div className="flex min-h-[220px] items-center justify-center rounded-2xl border border-dashed border-[var(--border-secondary)] bg-[var(--bg-secondary)] px-6 text-center text-sm text-[var(--text-tertiary)]">{t("task_history_empty")}</div>
                ) : (
                    <div className="space-y-4">
                        {historyLogs.map((log, i) => (
                            <div key={`${log.time}-${i}`} className="overflow-hidden rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-secondary)] shadow-sm">
                                <div className="flex flex-col gap-3 border-b border-[var(--border-secondary)] bg-[var(--bg-tertiary)] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                                    <div className="space-y-2">
                                        <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
                                            {new Date(log.time).toLocaleString(language === "zh" ? "zh-CN" : "en-US")}
                                        </div>
                                        <div className="text-sm font-semibold text-[var(--text-primary)]">
                                            {isZh
                                                ? `任务：${historyTaskName}${log.success ? "执行成功" : "执行失败"}`
                                                : `Task: ${historyTaskName} ${log.success ? "succeeded" : "failed"}`}
                                        </div>
                                    </div>
                                    <StatusBadge tone={log.success ? "success" : "danger"}>
                                        {log.success ? t("success") : t("failure")}
                                    </StatusBadge>
                                </div>
                                <div className="space-y-3 p-4 md:p-5">
                                    {log.message ? (
                                        <div className="rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-primary)] px-3 py-2.5 text-[var(--text-secondary)] break-all md:max-w-[46rem]">
                                            {isZh ? `机器人消息：${log.message}` : `Bot message: ${log.message}`}
                                        </div>
                                    ) : null}
                                    {log.flow_items && log.flow_items.length > 0 ? (
                                        <HistoryFlowGroups
                                            flowItems={log.flow_items}
                                            isZh={isZh}
                                            language={language}
                                            t={t}
                                        />
                                    ) : log.flow_logs && log.flow_logs.length > 0 ? (
                                        <div className="space-y-2 md:max-w-[46rem]">
                                            {log.flow_logs.map((line, lineIndex) => (
                                                <div key={lineIndex} className="grid grid-cols-[40px,minmax(0,1fr)] gap-3 rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-primary)] px-3 py-2.5">
                                                    <span className="flex h-7 items-center justify-center rounded-xl bg-[var(--bg-tertiary)] text-[10px] font-semibold tracking-[0.18em] text-[var(--text-tertiary)] select-none">
                                                        {(lineIndex + 1).toString().padStart(2, "0")}
                                                    </span>
                                                    <span className="break-all pt-1 text-[var(--text-primary)]">{line}</span>
                                                </div>
                                            ))}
                                        </div>
                                    ) : (
                                        <div className="rounded-2xl border border-dashed border-[var(--border-secondary)] bg-[var(--bg-primary)] px-3 py-3 text-[var(--text-secondary)] md:max-w-[46rem]">
                                            {log.message || t("task_history_no_flow")}
                                        </div>
                                    )}
                                    {log.flow_truncated && (
                                        <div className="rounded-2xl border border-amber-500/20 bg-[var(--bg-tertiary)] px-3 py-2 text-[11px] text-amber-300 md:max-w-[46rem]">
                                            {t("task_history_truncated").replace("{count}", String(log.flow_line_count || 0))}
                                        </div>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </ModalShell>

        </div>
    );
}
