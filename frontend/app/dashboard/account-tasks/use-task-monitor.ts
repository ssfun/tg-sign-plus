import { useEffect, useRef, useState } from "react";
import { getSignTaskStatus } from "../../../lib/api";

// Completion monitoring only needs a small authenticated status request. Serial
// polling recovers after disconnects and avoids a second WebSocket token lifecycle.
export function useTaskMonitor(accountName: string, taskName: string | null, onDone: () => Promise<void>) {
    const [failure, setFailure] = useState<{ account: string; task: string } | null>(null);
    const onDoneRef = useRef(onDone);
    useEffect(() => { onDoneRef.current = onDone; }, [onDone]);
    useEffect(() => {
        if (!taskName) return;
        let controller: AbortController | undefined;
        let deadline: ReturnType<typeof setTimeout>;
        let timer: ReturnType<typeof setTimeout>;
        let stopped = false;
        const poll = async () => {
            controller = new AbortController();
            deadline = setTimeout(() => controller?.abort(), 10000);
            try {
                const result = await getSignTaskStatus(taskName, accountName, controller.signal);
                clearTimeout(deadline);
                if (stopped) return;
                setFailure(null);
                if (!result.running) {
                    await onDoneRef.current();
                    return;
                }
            } catch {
                if (stopped) return;
                setFailure({ account: accountName, task: taskName });
            } finally {
                clearTimeout(deadline);
            }
            if (!stopped) timer = setTimeout(poll, 2000);
        };
        void poll();
        return () => { stopped = true; controller?.abort(); clearTimeout(deadline); clearTimeout(timer); };
    }, [accountName, taskName]);
    return Boolean(taskName) && failure?.task === taskName && failure?.account === accountName;
}
