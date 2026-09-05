import type { SignTaskAction, SignTaskChat } from "../../../lib/api";

export type ActionTypeOption = "1" | "2" | "3" | "ai_vision" | "ai_logic" | "ai_poetry" | "assert_success";

export type SuccessAssertionFormAction = {
    action: 9;
    keywords: string[];
    raw_input: string;
};
export type TaskFormAction = Exclude<SignTaskAction, { action: 9; keywords: string[] }> | SuccessAssertionFormAction;

export const isSuccessAssertionAction = (action: TaskFormAction | SignTaskAction | null | undefined): action is SuccessAssertionFormAction | { action: 9; keywords: string[] } => {
    return Number(action?.action) === 9;
};

export type TaskFormState = {
    name?: string;
    sign_at: string;
    random_minutes: number;
    retry_count: number;
    chat_id: number;
    chat_id_manual: string;
    chat_name: string;
    actions: TaskFormAction[];
    delete_after: number | undefined;
    event_timeout: number | undefined;
    event_retries: number | undefined;
    event_retry_wait: number | undefined;
    event_history_limit: number | undefined;
    event_history_failure_threshold: number | undefined;
    event_history_rescue_interval: number | undefined;
    event_history_rpc_timeout: number | undefined;
    event_history_result_max_age: number | undefined;
    event_action_timeout: number | undefined;
    event_send_timeout: number | undefined;
    event_media_timeout: number | undefined;
    event_ai_timeout: number | undefined;
    event_callback_timeout: number | undefined;
    event_callback_retries: number | undefined;
    event_ai_fallback: boolean | undefined;
    execution_mode: "fixed" | "range";
    range_start: string;
    range_end: string;
};

export const defaultTaskAction = (): TaskFormAction => ({ action: 1, text: "" });
export const toSuccessKeywords = (value: string) => value.split("#").map((item) => item.trim()).filter(Boolean);
export const normalizeTaskActions = (actions: TaskFormAction[]): SignTaskAction[] => actions.map((action) => {
    if (isSuccessAssertionAction(action)) {
        return {
            action: 9,
            keywords: toSuccessKeywords(action.raw_input),
        };
    }
    if (action.action === 6) {
        const captionPattern = action.caption_pattern?.trim();
        const captchaLengths = (action.captcha_lengths || []).filter((item) => Number.isInteger(item) && item > 0);
        const captchaCharset = action.captcha_charset?.trim();
        return {
            action: 6,
            ...(captionPattern ? { caption_pattern: captionPattern } : {}),
            ...(captchaLengths.length > 0 ? { captcha_lengths: captchaLengths } : {}),
            ...(captchaCharset ? { captcha_charset: captchaCharset } : {}),
            ...(action.captcha_case && action.captcha_case !== "preserve" ? { captcha_case: action.captcha_case } : {}),
            ...(action.reply_to_message ? { reply_to_message: true } : {}),
        };
    }
    return action;
});
export const toTaskFormAction = (action: SignTaskAction): TaskFormAction => {
    if (isSuccessAssertionAction(action)) {
        return {
            ...action,
            raw_input: action.keywords.join(" # "),
        };
    }
    if (action.action === 6) {
        return {
            action: 6,
            caption_pattern: action.caption_pattern || "",
            captcha_lengths: action.captcha_lengths || [],
            captcha_charset: action.captcha_charset || "",
            captcha_case: action.captcha_case || "preserve",
            reply_to_message: Boolean(action.reply_to_message),
        };
    }
    return action;
};

export const DICE_OPTIONS = [
    "\uD83C\uDFB2",
    "\uD83C\uDFAF",
    "\uD83C\uDFC0",
    "\u26BD",
    "\uD83C\uDFB3",
    "\uD83C\uDFB0",
] as const;


export const CHAT_OPTION_FIELDS = ["event_timeout", "event_retries", "event_retry_wait", "event_history_limit", "event_history_failure_threshold", "event_history_rescue_interval", "event_history_rpc_timeout", "event_history_result_max_age", "event_action_timeout", "event_send_timeout", "event_media_timeout", "event_ai_timeout", "event_callback_timeout", "event_callback_retries", "event_ai_fallback", "delete_after"] as const;

export function chatToForm(chat: SignTaskChat): Partial<TaskFormState> {
    return {
        ...Object.fromEntries(CHAT_OPTION_FIELDS.map(key => [key, chat[key]])),
        chat_id: chat.chat_id,
        chat_id_manual: String(chat.chat_id),
        chat_name: chat.name || "",
        actions: chat.actions.map(toTaskFormAction),
    };
}

export function formToChat(form: TaskFormState, original?: SignTaskChat): SignTaskChat {
    const rawId = form.chat_id_manual.trim();
    const chatId = rawId ? Number(rawId) : form.chat_id;
    if (!Number.isSafeInteger(chatId) || chatId === 0) throw new Error("Chat ID 必须为非零整数 / Chat ID must be a nonzero integer");
    return {
        ...original,
        ...Object.fromEntries(CHAT_OPTION_FIELDS.map(key => [key, form[key]])),
        chat_id: chatId,
        name: form.chat_name,
        actions: normalizeTaskActions(form.actions),
    };
}

export function replaceEditedChat(chats: SignTaskChat[], index: number, form: TaskFormState): SignTaskChat[] {
    return chats.map((chat, i) => i === index ? formToChat(form, chat) : chat);
}

export function findInvalidChatIndex(chats: SignTaskChat[]): number {
    return chats.findIndex(chat => !chat.actions.length || chat.actions.some(action => {
        if (action.action === 1 || action.action === 3) return !action.text?.trim();
        if (action.action === 2) return !action.dice?.trim();
        if (action.action === 9) return !action.keywords?.some(keyword => keyword.trim());
        return ![4, 5, 6, 7, 8].includes(Number(action.action));
    }));
}
