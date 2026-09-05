import type { SignTaskFlowItem, SignTaskHistoryItem, SignTaskRunSummary } from "../../../lib/api";
import { StatusBadge } from "../../../components/ui/status-badge";
import { cn } from "../../../lib/utils";

export const flowStageLabel = (stage: string, isZh: boolean) => {
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

export type TaskHistoryStepGroup = {
    index: number;
    title: string;
    items: SignTaskFlowItem[];
};

export type HistoryLogView = "read" | "ai" | "json";

export const HISTORY_META_KEYS = new Set([
    "chat_id",
    "message_id",
    "source",
    "source_message_id",
    "timeout",
    "keyword",
    "keywords",
    "attempt",
    "total_attempts",
    "retry_count",
    "action",
    "button_text",
    "target_text",
    "option_text",
    "selected_index",
    "reply_to_message",
    "status",
    "result",
    "reason",
    "error",
    "error_type",
]);

export const getTaskHistoryStepStatus = (items: SignTaskFlowItem[]) => {
    if (items.some((item) => item.level === "error")) {
        return "failed" as const;
    }
    if (items.some((item) => item.level === "success")) {
        return "success" as const;
    }
    return "running" as const;
};

export const formatFlowDateTime = (value: string | undefined, language: string) => {
    if (!value) return "--";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString(language === "zh" ? "zh-CN" : "en-US", { hour12: false });
};

export const formatFlowTime = (value: string | undefined, language: string) => {
    if (!value) return "--:--:--";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleTimeString(language === "zh" ? "zh-CN" : "en-US", { hour12: false });
};

export const formatDuration = (start?: string, end?: string, isZh = true) => {
    if (!start || !end) return "--";
    const startMs = new Date(start).getTime();
    const endMs = new Date(end).getTime();
    if (Number.isNaN(startMs) || Number.isNaN(endMs) || endMs < startMs) return "--";
    const seconds = Math.max(1, Math.round((endMs - startMs) / 1000));
    if (seconds < 60) return isZh ? `${seconds}秒` : `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const restSeconds = seconds % 60;
    return isZh ? `${minutes}分${restSeconds}秒` : `${minutes}m ${restSeconds}s`;
};

export const cleanFlowText = (text: string | undefined) => (text || "").replace(/^账户「.*?」- 任务「.*?」:\s*/, "");

export const humanizeActionText = (raw: string | undefined, isZh: boolean) => {
    const text = (raw || "").trim();
    if (!text) return isZh ? "执行步骤" : "Run step";

    const textValue = text.match(/text='([^']*)'/)?.[1] || text.match(/text="([^"]*)"/)?.[1];
    const keywordsValue = text.match(/keywords=\[([^\]]*)\]/)?.[1];

    if (text.includes("SEND_TEXT")) {
        return isZh ? `发送文本「${textValue || "-"}」` : `Send text "${textValue || "-"}"`;
    }
    if (text.includes("CLICK_KEYBOARD_BY_TEXT")) {
        return isZh ? `点击按钮「${textValue || "-"}」` : `Click button "${textValue || "-"}"`;
    }
    if (text.includes("ASSERT_SUCCESS") || text.includes("ASSERT_SUCCESS_BY_TEXT")) {
        return isZh ? `判断成功关键字「${keywordsValue || textValue || "-"}」` : `Assert success keywords "${keywordsValue || textValue || "-"}"`;
    }
    if (text.includes("SEND_DICE")) {
        return isZh ? "发送骰子" : "Send dice";
    }
    if (text.includes("IMAGE") || text.includes("VISION")) {
        return isZh ? "识图处理" : "Image recognition";
    }
    if (text.includes("CALCULATION")) {
        return isZh ? "计算题处理" : "Calculation challenge";
    }
    if (text.includes("POETRY")) {
        return isZh ? "诗词填空处理" : "Poetry fill challenge";
    }

    return cleanFlowText(text);
};

export const formatHistoryStepTitle = (index: number, firstItem: SignTaskFlowItem, isZh: boolean) => {
    const actionText = firstItem.meta?.action;
    if (typeof actionText === "string" && actionText.trim()) {
        return `${isZh ? "步骤" : "Step"} ${index} · ${humanizeActionText(actionText, isZh)}`;
    }
    const itemText = cleanFlowText(firstItem.text).trim();
    if (itemText) {
        return `${isZh ? "步骤" : "Step"} ${index} · ${humanizeActionText(itemText, isZh)}`;
    }
    return `${isZh ? "步骤" : "Step"} ${index}`;
};

export const isVisibleFlowItem = (item: SignTaskFlowItem) => item.text_visible !== false;

export const visibleFlowItems = (items: SignTaskFlowItem[] | undefined) => (items || []).filter(isVisibleFlowItem);

export const groupHistoryFlowItemsByStep = (flowItems: SignTaskFlowItem[] | undefined, isZh: boolean): TaskHistoryStepGroup[] => {
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

export const runSummaryStatusLabel = (summary: SignTaskRunSummary | undefined, isZh: boolean) => {
    switch (summary?.status) {
        case "checked": return isZh ? "已签到" : "Checked";
        case "success": return isZh ? "成功" : "Success";
        case "failed": return isZh ? "失败" : "Failed";
        default: return summary?.success ? (isZh ? "成功" : "Success") : (isZh ? "失败" : "Failed");
    }
};

export const runSummaryTone = (summary: SignTaskRunSummary | undefined, fallbackSuccess?: boolean) => {
    if (fallbackSuccess === false || summary?.status === "failed") return "danger";
    if (summary?.status === "checked" || summary?.status === "success" || summary?.success) return "success";
    return "neutral";
};

export const compactRunSummaryParts = (summary: SignTaskRunSummary | undefined, isZh: boolean) => {
    if (!summary) return [];
    const parts: string[] = [];
    if (summary.total_attempts) {
        parts.push(`${isZh ? "尝试" : "attempt"} ${summary.attempt || 0}/${summary.total_attempts}`);
    }
    const trustedTimeouts = summary.callbacks?.trusted_timeout || 0;
    if (trustedTimeouts > 0) {
        parts.push(`${isZh ? "可信回调超时" : "trusted callbacks"} ${trustedTimeouts}`);
    }
    const callbackOuterTimeouts = summary.callbacks?.outer_timeouts || 0;
    if (callbackOuterTimeouts > trustedTimeouts) {
        parts.push(`${isZh ? "回调外层超时" : "callback outer timeouts"} ${callbackOuterTimeouts}`);
    }
    const callbackInvalidAfterTimeout = summary.callbacks?.data_invalid_after_timeout || 0;
    if (callbackInvalidAfterTimeout > 0) {
        parts.push(`${isZh ? "回调数据失效" : "callback data expired"} ${callbackInvalidAfterTimeout}`);
    }
    const historyHandled = summary.history?.messages_handled || 0;
    if (historyHandled > 0) {
        parts.push(`${isZh ? "历史补漏" : "history rescue"} ${historyHandled}`);
    }
    const duplicateMessages = (summary.messages?.skipped_duplicate || 0)
        + (summary.messages?.skipped_concurrent_duplicate || 0)
        + (summary.history?.duplicate_messages || 0);
    if (duplicateMessages > 0) {
        parts.push(`${isZh ? "重复消息" : "duplicate messages"} ${duplicateMessages}`);
    }
    const finishedSkips = summary.messages?.skipped_finished || 0;
    if (finishedSkips > 0) {
        parts.push(`${isZh ? "迟到消息" : "late messages"} ${finishedSkips}`);
    }
    const historyFailedScans = summary.history?.failed_scans || 0;
    if (historyFailedScans > 0) {
        parts.push(`${isZh ? "历史查询失败" : "history failures"} ${historyFailedScans}`);
    }
    if (summary.history?.rescue_suspended) {
        parts.push(isZh ? "历史补漏暂停" : "history rescue paused");
    }
    const retrySuppressed = summary.retry_suppressed_count || 0;
    if (retrySuppressed > 0) {
        parts.push(`${isZh ? "抑制重试" : "suppressed retries"} ${retrySuppressed}`);
    }
    if (summary.retry?.limit_exceeded) {
        parts.push(isZh ? "重试耗尽" : "retry limit exceeded");
    }
    const timeoutTotal = summary.timeouts?.timeout_count_total || 0;
    if (timeoutTotal > 0) {
        parts.push(`${isZh ? "超时" : "timeouts"} ${timeoutTotal}`);
    }
    if (summary.cleanup?.failed) {
        const timeout = summary.cleanup.timeout_seconds ? `/${summary.cleanup.timeout_seconds}s` : "";
        parts.push(`${isZh ? "清理失败" : "cleanup failed"}${timeout}`);
    }
    const lockWait = Number(summary.account_lock?.wait_seconds || 0);
    if (lockWait > 0.5) {
        parts.push(`${isZh ? "锁等待" : "lock wait"} ${lockWait}s`);
    }
    return parts;
};

export const formatInlineMeta = (meta: SignTaskFlowItem["meta"] | undefined, detailed = false, text?: string) => {
    if (!meta) return "";
    const sourceText = cleanFlowText(text || "");
    const entries = Object.entries(meta).filter(([key, value]) => {
        if (!detailed && !HISTORY_META_KEYS.has(key)) return false;
        const pair = `${key}=${String(value)}`;
        const colonPair = `${key}: ${String(value)}`;
        return !sourceText.includes(pair) && !sourceText.includes(colonPair);
    });
    return entries.map(([key, value]) => `${key}=${String(value)}`).join(" · ");
};

export const getHistoryDiagnostics = (log: SignTaskHistoryItem | undefined, isZh: boolean) => {
    const items = visibleFlowItems(log?.flow_items);
    const groups = groupHistoryFlowItemsByStep(items, isZh);
    const errorItem = [...items].reverse().find((item) => item.level === "error");
    const warningItem = [...items].reverse().find((item) => item.level === "warning");
    const failureIndex = errorItem || warningItem ? items.findIndex((item) => item === (errorItem || warningItem)) : items.length;
    const lastSuccessItem = items.slice(0, failureIndex >= 0 ? failureIndex : items.length).reverse().find((item) => item.level === "success");
    const start = items[0]?.ts;
    const end = items[items.length - 1]?.ts || log?.time;
    const completedSteps = groups.filter((group) => getTaskHistoryStepStatus(group.items) === "success").length;

    return {
        groups,
        directReason: log?.message || log?.run_summary?.error || log?.diagnostics?.summary || "",
        failedStage: log?.success ? "--" : (log?.diagnostics?.checks.find(check => check.status === "fail")?.label || (errorItem ? flowStageLabel(errorItem.stage, isZh) : "--")),
        lastSuccess: lastSuccessItem ? cleanFlowText(lastSuccessItem.text) : "--",
        duration: formatDuration(start, end, isZh),
        completedSteps,
        totalSteps: groups.length,
        errorItem,
        warningItem,
    };
};

export const formatHistoryTimelineText = (log: SignTaskHistoryItem, language: string, failureOnly = false) => {
    const items = visibleFlowItems(log.flow_items);
    const visibleItems = failureOnly ? items.filter((item) => item.level === "error" || item.level === "warning") : items;
    if (visibleItems.length > 0) {
        return visibleItems.map((item) => {
            const meta = formatInlineMeta(item.meta, false, item.text);
            return `${formatFlowTime(item.ts, language)} [${item.stage}/${item.level}] ${cleanFlowText(item.text)}${meta ? ` (${meta})` : ""}`;
        }).join("\n");
    }
    return (log.flow_logs || []).join("\n") || log.message || "";
};

export const formatHistoryForAi = ({
    log,
    accountName,
    taskName,
    language,
    isZh,
}: {
    log: SignTaskHistoryItem;
    accountName: string;
    taskName: string;
    language: string;
    isZh: boolean;
}) => {
    const diagnostics = getHistoryDiagnostics(log, isZh);
    const summary = log.run_summary;
    const summaryParts = compactRunSummaryParts(summary, isZh);
    const humanItems = visibleFlowItems(log.flow_items);
    const chatId = log.flow_items?.find((item) => item.meta?.chat_id)?.meta?.chat_id;
    const errorMeta = diagnostics.errorItem?.meta ? JSON.stringify(diagnostics.errorItem.meta, null, 2) : "{}";

    return `# TG Sign Plus 任务排查日志

## 基本信息
- 账户：${accountName}
- 任务：${taskName}
- chat_id：${chatId || "未知"}
- 执行时间：${formatFlowDateTime(log.time, language)}
- 执行结果：${log.success ? "成功" : "失败"}
- 结构化状态：${summary ? runSummaryStatusLabel(summary, isZh) : "无"}
- 结构化摘要：${summaryParts.length ? summaryParts.join("；") : "无"}
- 机器人消息：${log.message || "无"}
- 日志条数：${humanItems.length}${log.flow_items && log.flow_items.length !== humanItems.length ? `（结构化事件 ${log.flow_items.length}）` : ""}

## 失败摘要
- 失败阶段：${diagnostics.failedStage}
- 直接原因：${diagnostics.directReason || "未提取到明确原因"}
- 最后成功动作：${diagnostics.lastSuccess}
- 步骤进度：${diagnostics.completedSteps}/${diagnostics.totalSteps}
- 耗时：${diagnostics.duration}
- 事件诊断：${log.diagnostics?.summary || "未生成"}

## 分步骤时间线
${diagnostics.groups.map((group) => {
        const status = getTaskHistoryStepStatus(group.items);
        return `### ${group.title}（${status}）\n${group.items.map((item) => {
            const meta = formatInlineMeta(item.meta, false, item.text);
            return `${formatFlowTime(item.ts, language)} [${item.stage}/${item.level}] ${cleanFlowText(item.text)}${meta ? ` (${meta})` : ""}`;
        }).join("\n")}`;
    }).join("\n\n") || "无结构化步骤日志"}

## 原始错误 meta
\`\`\`json
${errorMeta}
\`\`\`

## 原始时间线
\`\`\`text
${formatHistoryTimelineText(log, language)}
\`\`\`
`;
};

export const formatHistoryRawJson = (log: SignTaskHistoryItem, accountName: string, taskName: string) => JSON.stringify({
    account_name: accountName,
    task_name: taskName,
    history: log,
}, null, 2);

export const HistoryTimeline = ({ items, isZh, language, failureOnly, expandDetails }: {
    items: SignTaskFlowItem[];
    isZh: boolean;
    language: string;
    failureOnly: boolean;
    expandDetails: boolean;
}) => {
    const humanItems = visibleFlowItems(items);
    const visibleItems = failureOnly ? humanItems.filter((item) => item.level === "error" || item.level === "warning") : humanItems;
    if (visibleItems.length === 0) {
        return <div className="rounded-2xl border border-dashed border-[var(--border-secondary)] bg-[var(--bg-primary)] px-4 py-4 text-sm text-[var(--text-tertiary)]">{isZh ? "当前筛选下没有日志" : "No logs for this filter"}</div>;
    }

    return (
        <div className="divide-y divide-[var(--border-secondary)] overflow-hidden rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-primary)]">
            {visibleItems.map((item, index) => {
                const compactMeta = formatInlineMeta(item.meta, false, item.text);
                const allMeta = formatInlineMeta(item.meta, true, item.text);
                return (
                    <details key={`${item.ts}-${index}`} open={expandDetails} className={cn("group px-3 py-2.5", item.level === "error" && "border-l-4 border-red-500 bg-red-500/8", item.level === "warning" && "border-l-4 border-amber-500 bg-amber-500/8")}>
                        <summary className="grid cursor-pointer list-none grid-cols-[70px,76px,minmax(0,1fr)] gap-2 text-[12px] leading-5 md:grid-cols-[82px,90px,minmax(0,1fr)]">
                            <span className="font-mono tabular-nums text-[var(--text-tertiary)]">{formatFlowTime(item.ts, language)}</span>
                            <span className={cn("font-semibold uppercase tracking-[0.08em]", item.level === "error" ? "text-red-300" : item.level === "warning" ? "text-amber-300" : item.level === "success" ? "text-emerald-300" : "text-[var(--text-tertiary)]")}>{flowStageLabel(item.stage, isZh)}</span>
                            <span className="min-w-0 break-words text-[var(--text-primary)]">
                                {cleanFlowText(item.text)}
                                {compactMeta ? <span className="ml-2 text-[10px] text-[var(--text-tertiary)]">{compactMeta}</span> : null}
                            </span>
                        </summary>
                        {allMeta ? <div className="mt-2 rounded-xl bg-[var(--bg-tertiary)] px-3 py-2 font-mono text-[10px] leading-5 text-[var(--text-secondary)] break-all">{allMeta}</div> : null}
                    </details>
                );
            })}
        </div>
    );
};

export const HistoryFlowGroups = ({
    flowItems,
    isZh,
    language,
    t,
    failureOnly,
    expandDetails,
}: {
    flowItems: SignTaskFlowItem[];
    isZh: boolean;
    language: string;
    t: (key: string) => string;
    failureOnly: boolean;
    expandDetails: boolean;
}) => {
    const humanItems = visibleFlowItems(flowItems);
    const stepGroups = groupHistoryFlowItemsByStep(humanItems, isZh);
    if (stepGroups.length === 0) {
        return <HistoryTimeline items={humanItems} isZh={isZh} language={language} failureOnly={failureOnly} expandDetails={expandDetails} />;
    }

    const visibleGroups = failureOnly ? stepGroups.filter((group) => getTaskHistoryStepStatus(group.items) === "failed" || group.items.some((item) => item.level === "warning")) : stepGroups;

    return (
        <div className="space-y-4">
            {visibleGroups.map((group) => {
                const status = getTaskHistoryStepStatus(group.items);
                return (
                    <section key={`step-${group.index}-${group.items[0]?.ts ?? group.index}`} className="space-y-2">
                        <div className="flex flex-col gap-2 border-b border-[var(--border-secondary)] pb-2 sm:flex-row sm:items-center sm:justify-between">
                            <div className="min-w-0">
                                <div className="break-words text-sm font-semibold text-[var(--text-primary)]">{group.title}</div>
                                <div className="mt-1 text-xs text-[var(--text-tertiary)]">{group.items.length} {isZh ? "条日志" : "events"}</div>
                            </div>
                            <StatusBadge tone={status === "failed" ? "danger" : status === "success" ? "success" : "warning"}>
                                {status === "failed" ? t("failure") : status === "success" ? t("success") : (isZh ? "进行中" : "Running")}
                            </StatusBadge>
                        </div>
                        <HistoryTimeline items={group.items} isZh={isZh} language={language} failureOnly={failureOnly} expandDetails={expandDetails} />
                    </section>
                );
            })}
        </div>
    );
};


// Compare server history timestamps, avoiding dependence on the browser clock.
// undefined means the baseline could not be read; null means history was empty.
export function getNewRunResult(logs: SignTaskHistoryItem[], baseline: string | null | undefined) {
    const latest = logs[0];
    if (baseline === undefined || !latest || !Number.isFinite(Date.parse(latest.time))) return undefined;
    if (baseline !== null && !(Date.parse(latest.time) > Date.parse(baseline))) return undefined;
    return latest;
}
