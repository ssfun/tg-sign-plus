import { expect, it } from "vitest";
import { getHistoryDiagnostics, runSummaryTone, getNewRunResult } from "./task-history";

it("does not turn recovered warning logs into a failed result", () => {
    const diagnostics = getHistoryDiagnostics({
        time: "2026-09-05T00:00:00Z", success: true, message: "签到成功",
        flow_items: [{ ts: "2026-09-05T00:00:00Z", level: "warning", stage: "session", event: "retry", text: "Temporary connection error" }],
    }, true);
    expect(diagnostics.directReason).toBe("签到成功");
    expect(diagnostics.failedStage).toBe("--");
    expect(runSummaryTone({ success: true, status: "success" }, false)).toBe("danger");
});

it("does not report an old result when the current history write is missing", () => {
    const old = { time: "2026-09-05T00:00:00Z", success: true };
    const current = { time: "2026-09-05T00:01:00Z", success: false };
    expect(getNewRunResult([old], old.time)).toBeUndefined();
    expect(getNewRunResult([old], undefined)).toBeUndefined();
    expect(getNewRunResult([], null)).toBeUndefined();
    expect(getNewRunResult([current], old.time)).toBe(current);
    expect(getNewRunResult([current], null)).toBe(current);
});
