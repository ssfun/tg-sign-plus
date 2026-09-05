import { describe, expect, it } from "vitest";
import type { SignTaskChat } from "../../../lib/api";
import { chatToForm, replaceEditedChat, findInvalidChatIndex, type TaskFormState } from "./task-form";

const chats: SignTaskChat[] = [
    { chat_id: 123, name: "First", actions: [{ action: 1, text: "/sign" }, { action: 9, keywords: ["成功"] }], event_timeout: 75 },
    { chat_id: 456, name: "Second", actions: [{ action: 1, text: "/start" }], event_ai_fallback: false },
];
const edit = (chat: SignTaskChat) => chatToForm(chat) as TaskFormState;

describe("task editor round trip", () => {
    it("preserves every chat when saving without changes", () => {
        expect(JSON.parse(JSON.stringify(replaceEditedChat(chats, 0, edit(chats[0]))))).toEqual(chats);
    });
    it("keeps edits to both chats across selection changes", () => {
        const first = replaceEditedChat(chats, 0, { ...edit(chats[0]), chat_name: "Updated first" });
        const result = replaceEditedChat(first, 1, { ...edit(first[1]), chat_name: "Updated second" });
        expect(result.map(chat => chat.name)).toEqual(["Updated first", "Updated second"]);
        expect(chats[0].name).toBe("First");
        expect(result[1].event_ai_fallback).toBe(false);
    });
    it.each(["123garbage", "12.5", "0", "9007199254740992"])("rejects invalid manual chat ID %s", raw => {
        expect(() => replaceEditedChat(chats, 0, { ...edit(chats[0]), chat_id_manual: raw })).toThrow();
    });
    it("uses the edited manual ID rather than the original cached selection", () => {
        const result = replaceEditedChat(chats, 0, { ...edit(chats[0]), chat_id_manual: "-100777" });
        expect(result[0].chat_id).toBe(-100777);
    });
});

it("locates an invalid hidden chat after switching to another chat", () => {
    const drafts = replaceEditedChat(chats, 0, { ...edit(chats[0]), actions: [{ action: 1, text: " " }] });
    const saved = replaceEditedChat(drafts, 1, edit(drafts[1]));
    expect(findInvalidChatIndex(saved)).toBe(0);
    expect(findInvalidChatIndex(chats)).toBe(-1);
    expect(findInvalidChatIndex([{ ...chats[1], actions: [] }])).toBe(0);
});
