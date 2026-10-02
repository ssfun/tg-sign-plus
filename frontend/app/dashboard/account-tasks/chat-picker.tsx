"use client";

import { useEffect, useRef, useState } from "react";
import { ChatCacheResponse, ChatInfo, getAccountChats, refreshAccountChats, searchAccountChats } from "../../../lib/api";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { useLanguage } from "../../../context/LanguageContext";
import { cn } from "../../../lib/utils";

const PAGE_SIZE = 50;

export function ChatPicker({ accountName, selectedId, onSelect, onBusyChange, onError }: {
    accountName: string;
    selectedId: number;
    onSelect: (id: number, title: string) => void;
    onBusyChange: (busy: boolean) => void;
    onError: (error: unknown) => void;
}) {
    const { t, language } = useLanguage();
    const isZh = language === "zh";
    const [query, setQuery] = useState("");
    const [offset, setOffset] = useState(0);
    const [refresh, setRefresh] = useState(0);
    const [meta, setMeta] = useState<ChatCacheResponse | null>(null);
    const [items, setItems] = useState<ChatInfo[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(true);
    const [failed, setFailed] = useState(false);
    const [retry, setRetry] = useState(0);
    const pageController = useRef<AbortController | null>(null);
    const errorRef = useRef(onError);
    useEffect(() => { errorRef.current = onError; }, [onError]);

    useEffect(() => {
        const controller = new AbortController();
        onBusyChange(true);
        void (async () => {
            try {
                const result = refresh > 0
                    ? await refreshAccountChats(accountName, false, controller.signal)
                    : await getAccountChats(accountName, {
                        autoRefreshIfExpired: true, ensureExists: true, includeItems: false,
                    }, controller.signal);
                if (!controller.signal.aborted) setMeta(result);
            } catch (error) {
                if (!controller.signal.aborted) errorRef.current(error);
            } finally {
                if (!controller.signal.aborted) {
                    setRefreshing(false);
                    onBusyChange(false);
                }
            }
        })();
        return () => {
            controller.abort();
            onBusyChange(false);
        };
    }, [accountName, refresh, onBusyChange]);

    useEffect(() => {
        if (!meta) return;
        const controller = new AbortController();
        pageController.current = controller;
        const timer = setTimeout(() => {
            void (async () => {
                try {
                    const result = await searchAccountChats(accountName, query.trim(), PAGE_SIZE, offset, controller.signal);
                    if (controller.signal.aborted) return;
                    if (offset > 0 && offset >= result.total) {
                        setOffset(Math.max(0, Math.ceil(result.total / PAGE_SIZE) - 1) * PAGE_SIZE);
                        return;
                    }
                    setItems(result.items);
                    setTotal(result.total);
                } catch (error) {
                    if (!controller.signal.aborted) {
                        setFailed(true);
                        errorRef.current(error);
                    }
                } finally {
                    if (!controller.signal.aborted) setLoading(false);
                }
            })();
        }, query.trim() ? 300 : 0);
        return () => { clearTimeout(timer); controller.abort(); };
    }, [accountName, meta, query, offset, retry]);

    const changePage = (next: number) => {
        pageController.current?.abort();
        setOffset(next);
        setItems([]);
        setLoading(true);
        setFailed(false);
    };

    return <div className="space-y-2 md:col-span-2" data-chat-picker>
        <div className="flex items-center justify-between gap-2">
            <label htmlFor="chat-picker-search" className="text-xs text-[var(--text-tertiary)]">{t("search_chat")}</label>
            <Button type="button" variant="ghost" size="sm" disabled={refreshing} onClick={() => {
                changePage(0);
                setMeta(null);
                setRefreshing(true);
                setRefresh(value => value + 1);
            }}>{refreshing ? t("loading") : t("refresh_list")}</Button>
        </div>
        <Input id="chat-picker-search" placeholder={t("search_chat_placeholder")} value={query}
            onChange={event => {
                if (event.target.value === query) return;
                changePage(0);
                setQuery(event.target.value);
            }} />
        <div className="max-h-48 min-h-32 overflow-y-auto rounded-lg border border-[var(--border-secondary)]" aria-busy={refreshing || (Boolean(meta) && loading)}>
            {refreshing || (meta && loading) ? <p className="p-3 text-xs">{t("searching")}</p>
                : !meta ? <p className="p-3 text-xs">{isZh ? "聊天缓存读取失败，请刷新重试" : "Could not load chats. Refresh to retry."}</p>
                    : failed ? <Button type="button" variant="ghost" onClick={() => { changePage(offset); setRetry(value => value + 1); }}>{isZh ? "重试" : "Retry"}</Button>
                        : items.length === 0 ? <p className="p-3 text-xs">{t("search_no_results")}</p>
                            : items.map(chat => {
                                const title = chat.title || chat.username || String(chat.id);
                                return <button key={chat.id} type="button" data-chat-id={chat.id} aria-pressed={selectedId === chat.id}
                                    className={cn("block w-full px-3 py-2 text-left hover:bg-[var(--bg-primary)]", selectedId === chat.id && "bg-[var(--bg-tertiary)]")}
                                    onClick={() => onSelect(chat.id, title)}>
                                    <div className="truncate text-sm font-semibold">{title}</div>
                                    <div className="truncate font-mono text-xs text-[var(--text-tertiary)]">{chat.id}{chat.username ? ` · @${chat.username}` : ""}</div>
                                </button>;
                            })}
        </div>
        {meta && <div className="flex items-center justify-between gap-2 text-xs">
            <Button type="button" variant="ghost" size="sm" disabled={loading || failed || offset === 0}
                onClick={() => changePage(Math.max(0, offset - PAGE_SIZE))}>{isZh ? "上一页" : "Previous"}</Button>
            <span>{loading ? "…" : `${total ? offset + 1 : 0}–${offset + items.length} / ${total}`}</span>
            <Button type="button" variant="ghost" size="sm" disabled={loading || failed || offset + PAGE_SIZE >= total}
                onClick={() => changePage(offset + PAGE_SIZE)}>{isZh ? "下一页" : "Next"}</Button>
        </div>}
        {meta && <p className="text-xs text-[var(--text-tertiary)]">
            {isZh ? "上次缓存：" : "Last cached: "}{meta.last_cached_at ? new Date(meta.last_cached_at).toLocaleString() : "—"}
            {` · TTL ${meta.cache_ttl_minutes} ${isZh ? "分钟" : "min"}`}
        </p>}
    </div>;
}
