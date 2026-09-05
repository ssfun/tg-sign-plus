import { memo, useEffect, useRef, useState } from "react";
import type { SignTask, SchedulerStatus } from "../../../lib/api";
import { ChatCircleText, Clock, Hourglass, Spinner, Play, ListDashes, DotsThreeVertical, PencilSimple, Copy, Trash } from "@phosphor-icons/react";
import { StatusBadge } from "../../../components/ui/status-badge";
import { IconButton } from "../../../components/ui/icon-button";
import { Button } from "../../../components/ui/button";

import { compactRunSummaryParts, runSummaryTone, runSummaryStatusLabel } from "./task-history";

// Memoized Task Item Component
export const TaskItem = memo(({ task, loading, isRunning, schedulerItem, schedulerTimezone, onEdit, onRun, onToggleEnabled, onViewLogs, onCopy, onDelete, t, language }: {
    task: SignTask;
    loading: boolean;
    isRunning: boolean;
    schedulerItem?: SchedulerStatus["sign_tasks"][number];
    schedulerTimezone?: string;
    onEdit: (task: SignTask) => void;
    onRun: (name: string) => void;
    onToggleEnabled: (task: SignTask) => void;
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

    const closeActions = () => {
        menuRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
        setShowActions(false);
    };
    const lastRunSummary = task.last_run?.run_summary;
    const lastRunSummaryParts = compactRunSummaryParts(lastRunSummary, language === "zh");

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
                            {task.chats.length > 1 ? `${task.chats.length} ${language === "zh" ? "个会话" : "chats"}` : task.chats[0]?.chat_id || "-"}
                        </span>
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                        <StatusBadge tone={task.enabled ? "success" : "warning"}>
                            {task.enabled ? (language === "zh" ? "自动调度" : "Auto") : (language === "zh" ? "已暂停自动" : "Paused")}
                        </StatusBadge>
                        {task.enabled ? (
                            <StatusBadge tone={schedulerItem?.job_exists ? "success" : "danger"}>
                                {schedulerItem?.job_exists ? (language === "zh" ? "已注册" : "Registered") : (language === "zh" ? "未注册" : "Missing")}
                            </StatusBadge>
                        ) : null}
                        {task.enabled && task.execution_mode === "range" && schedulerItem?.execution_job_exists && schedulerItem?.next_scheduled_at ? (
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
                            <span>~{task.random_seconds < 60 ? `${task.random_seconds}s` : `${Math.round(task.random_seconds / 60)}m`}</span>
                        </div>
                        ) : null}
                </div>

                <div className="rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] px-4 py-3">
                    <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">
                        {language === "zh" ? "下一次执行" : "Next run"}
                    </div>
                    {!task.enabled ? (
                        <div className="mt-2 text-xs text-[var(--text-tertiary)]">
                            {language === "zh" ? "已暂停，可手动运行" : "Paused; manual run available"}
                        </div>
                    ) : task.execution_mode === "range" && schedulerItem?.execution_job_exists && schedulerItem?.next_scheduled_at ? (
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
                    <div className="mt-2 space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                            <StatusBadge tone={runSummaryTone(lastRunSummary, task.last_run.success) as any}>
                                {lastRunSummary ? runSummaryStatusLabel(lastRunSummary, language === "zh") : (task.last_run.success ? t("success") : t("failure"))}
                            </StatusBadge>
                            <span className="font-mono text-[11px] text-[var(--text-tertiary)]">
                                {new Date(task.last_run.time).toLocaleString(language === "zh" ? "zh-CN" : "en-US", {
                                    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"
                                })}
                            </span>
                        </div>
                        {lastRunSummaryParts.length > 0 ? (
                            <div className="flex flex-wrap gap-1.5">
                                {lastRunSummaryParts.slice(0, 3).map((part) => (
                                    <span key={part} className="rounded-md border border-[var(--border-secondary)] bg-[var(--bg-primary)] px-1.5 py-0.5 text-[10px] text-[var(--text-tertiary)]">
                                        {part}
                                    </span>
                                ))}
                            </div>
                        ) : null}
                    </div>
                ) : (
                    <div className="mt-2">
                        <StatusBadge tone="neutral">{t("no_data")}</StatusBadge>
                    </div>
                )}
            </div>

            <div className="mt-4 flex flex-nowrap items-center gap-1.5 border-t border-[var(--border-secondary)] pt-4 sm:gap-2">
                <Button
                    size="sm"
                    onClick={() => {
                        closeActions();
                        onRun(task.name);
                    }}
                    disabled={loading || isRunning}
                    className="shrink-0 whitespace-nowrap px-2 sm:px-3"
                >
                    {isRunning ? <Spinner className="animate-spin" size={14} /> : <Play weight="fill" size={14} />}
                    {t("run")}
                </Button>

                <div className="flex min-w-0 flex-1 flex-nowrap items-center justify-end gap-1.5 sm:gap-2">
                    <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => onViewLogs(task)}
                        disabled={loading || isRunning}
                        className="shrink-0 whitespace-nowrap px-2 sm:px-3"
                    >
                        <ListDashes weight="bold" size={14} />
                        {language === "zh" ? "日志" : "Logs"}
                    </Button>
                    <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => onToggleEnabled(task)}
                        disabled={loading || isRunning}
                        className="shrink-0 whitespace-nowrap px-2 sm:px-3"
                    >
                        <Clock weight="bold" size={14} />
                        {task.enabled ? (language === "zh" ? "暂停" : "Pause") : (language === "zh" ? "恢复" : "Resume")}
                    </Button>
                    <div ref={menuRef} className="relative shrink-0">
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

                        {showActions ? (
                            <div className="absolute right-0 top-full z-20 mt-2 min-w-[180px] rounded-2xl border border-[var(--border-primary)] bg-[var(--bg-primary)] p-1.5 shadow-[var(--shadow-lg)]">
                                <button
                                    type="button"
                                    className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm text-[var(--text-primary)] transition-colors hover:bg-[var(--bg-tertiary)] disabled:cursor-not-allowed disabled:opacity-50"
                                    onClick={() => {
                                        closeActions();
                                        onEdit(task);
                                    }}
                                    disabled={loading || isRunning}
                                >
                                    <PencilSimple weight="bold" size={14} />
                                    <span>{language === "zh" ? "编辑任务" : "Edit task"}</span>
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
        </div>
    );
});

TaskItem.displayName = "TaskItem";
