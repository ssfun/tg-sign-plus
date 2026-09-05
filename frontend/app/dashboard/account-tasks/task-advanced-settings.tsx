import { FormField } from "../../../components/ui/form-field";
import { Input } from "../../../components/ui/input";
import type { TaskFormState } from "./task-form";

const fields = [
  {
    "key": "event_timeout",
    "zh": "事件总等待秒数",
    "en": "Event timeout",
    "id": "task-event-timeout",
    "placeholder": "120",
    "min": 1,
    "integer": false
  },
  {
    "key": "event_retries",
    "zh": "事件内部重试",
    "en": "Event retries",
    "id": "task-event-retries",
    "placeholder": "3",
    "min": 0,
    "integer": true
  },
  {
    "key": "event_retry_wait",
    "zh": "重试等待秒数",
    "en": "Retry wait",
    "id": "task-event-retry-wait",
    "placeholder": "2",
    "min": 0,
    "integer": false
  },
  {
    "key": "event_history_limit",
    "zh": "历史救援条数",
    "en": "History scan",
    "id": "task-event-history-limit",
    "placeholder": "0",
    "min": 0,
    "integer": true
  },
  {
    "key": "event_history_failure_threshold",
    "zh": "历史失败阈值",
    "en": "History failure limit",
    "id": "task-event-history-failure-threshold",
    "placeholder": "0",
    "min": 0,
    "integer": true
  },
  {
    "key": "event_history_rescue_interval",
    "zh": "历史补漏间隔秒数",
    "en": "History rescue interval",
    "id": "task-event-history-rescue-interval",
    "placeholder": "5",
    "min": 0,
    "integer": false
  },
  {
    "key": "event_history_rpc_timeout",
    "zh": "历史 RPC 超时秒数",
    "en": "History RPC timeout",
    "id": "task-event-history-rpc-timeout",
    "placeholder": "8",
    "min": 1,
    "integer": false
  },
  {
    "key": "event_history_result_max_age",
    "zh": "历史结果最大年龄秒数",
    "en": "History result max age",
    "id": "task-event-history-result-max-age",
    "placeholder": "600",
    "min": 0,
    "integer": false
  },
  {
    "key": "event_action_timeout",
    "zh": "单动作超时秒数",
    "en": "Action timeout",
    "id": "task-event-action-timeout",
    "placeholder": "45",
    "min": 1,
    "integer": false
  },
  {
    "key": "event_send_timeout",
    "zh": "发送超时秒数",
    "en": "Send timeout",
    "id": "task-event-send-timeout",
    "placeholder": "20",
    "min": 1,
    "integer": false
  },
  {
    "key": "event_media_timeout",
    "zh": "媒体超时秒数",
    "en": "Media timeout",
    "id": "task-event-media-timeout",
    "placeholder": "30",
    "min": 1,
    "integer": false
  },
  {
    "key": "event_ai_timeout",
    "zh": "AI 超时秒数",
    "en": "AI timeout",
    "id": "task-event-ai-timeout",
    "placeholder": "45",
    "min": 1,
    "integer": false
  },
  {
    "key": "event_callback_timeout",
    "zh": "按钮回调超时秒数",
    "en": "Callback timeout",
    "id": "task-event-callback-timeout",
    "placeholder": "10",
    "min": 0,
    "integer": false
  },
  {
    "key": "event_callback_retries",
    "zh": "按钮回调重试次数",
    "en": "Callback retries",
    "id": "task-event-callback-retries",
    "placeholder": "3",
    "min": 1,
    "integer": true
  }
] as const;

export function TaskAdvancedSettings({ value, onChange, isZh }: {
    value: TaskFormState;
    onChange: (patch: Partial<TaskFormState>) => void;
    isZh: boolean;
}) {
    return <details className="rounded-xl border border-[var(--border-secondary)] p-4">
        <summary className="cursor-pointer text-sm font-semibold">{isZh ? "高级设置（可选）" : "Advanced settings (optional)"}</summary>
        <p className="my-3 text-xs text-[var(--text-secondary)]">{isZh ? "通常无需调整。留空使用默认值；仅在排查超时或机器人交互问题时修改。" : "Defaults work for most tasks. Leave blank to use defaults; adjust only when troubleshooting."}</p>
        <div className="grid grid-cols-2 gap-3">
            {fields.map(field => <FormField key={field.key} label={isZh ? field.zh : field.en} htmlFor={field.id}>
                <Input id={field.id} type="number" min={field.min} step={field.integer ? 1 : "any"}
                    placeholder={field.placeholder} value={value[field.key] ?? ""}
                    onChange={event => {
                        const raw = event.target.value;
                        const n = Number(raw);
                        onChange({ [field.key]: raw === "" || !Number.isFinite(n) ? undefined : Math.max(field.min, field.integer ? Math.trunc(n) : n) });
                    }} />
            </FormField>)}
        </div>
        <label className="mt-4 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={Boolean(value.event_ai_fallback)}
                onChange={event => onChange({ event_ai_fallback: event.target.checked })} />
            {isZh ? "未知后续交互启用 AI 兜底" : "AI fallback for unknown follow-up"}
        </label>
    </details>;
}
