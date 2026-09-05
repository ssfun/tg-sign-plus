import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getSignTaskStatus } from "../../../lib/api";
import { useTaskMonitor } from "./use-task-monitor";

vi.mock("../../../lib/api", () => ({ getSignTaskStatus: vi.fn() }));
const status = vi.mocked(getSignTaskStatus);
beforeEach(() => { vi.useFakeTimers(); status.mockReset(); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

it("keeps monitoring after an outage and reports completion only after confirmation", async () => {
    status.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({ running: true }).mockResolvedValueOnce({ running: false });
    const done = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useTaskMonitor("account", "task", done));
    await act(async () => {});
    expect(result.current).toBe(true);
    expect(done).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(result.current).toBe(false);
    expect(done).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(done).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(status).toHaveBeenCalledTimes(3);
});

it("never overlaps requests and ignores a late completion after navigation", async () => {
    let resolve!: (value: { running: boolean }) => void;
    status.mockImplementation(() => new Promise(r => { resolve = r; }));
    const done = vi.fn();
    const { unmount } = renderHook(() => useTaskMonitor("account", "task", done));
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(status).toHaveBeenCalledTimes(1);
    const signal = status.mock.calls[0][2];
    unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => { resolve({ running: false }); });
    expect(done).not.toHaveBeenCalled();
});

it("aborts a stalled request and retries with a fresh signal", async () => {
    status.mockImplementationOnce((_task, _account, signal) => new Promise((_resolve, reject) => {
        signal!.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    })).mockResolvedValueOnce({ running: false });
    const done = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useTaskMonitor("account", "task", done));
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(status.mock.calls[0][2]?.aborted).toBe(true);
    expect(result.current).toBe(true);
    expect(done).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(status.mock.calls[1][2]?.aborted).toBe(false);
    expect(done).toHaveBeenCalledTimes(1);
});
