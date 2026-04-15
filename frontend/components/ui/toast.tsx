"use client";

import { useEffect, useState } from "react";

interface ToastProps {
    message: string;
    type?: "success" | "error" | "info";
    duration?: number;
    onClose: () => void;
}

export function Toast({ message, type = "info", duration = 4000, onClose }: ToastProps) {
    const [isExiting, setIsExiting] = useState(false);

    useEffect(() => {
        const timer = setTimeout(() => {
            setIsExiting(true);
            setTimeout(onClose, 200);
        }, duration);

        return () => clearTimeout(timer);
    }, [duration, onClose]);

    const getAccentClasses = () => {
        switch (type) {
            case "success":
                return "border-[var(--success)]/20 bg-[var(--bg-secondary)]";
            case "error":
                return "border-[var(--danger)]/20 bg-[var(--bg-secondary)]";
            default:
                return "border-[var(--accent)]/20 bg-[var(--bg-secondary)]";
        }
    };

    const getIcon = () => {
        switch (type) {
            case "success":
                return (
                    <svg className="w-4 h-4 text-[var(--success)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                );
            case "error":
                return (
                    <svg className="w-4 h-4 text-[var(--danger)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                );
            default:
                return (
                    <svg className="w-4 h-4 text-[var(--accent)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                );
        }
    };

    return (
        <div
            className={`
                ${isExiting ? "toast-exit" : "toast-enter"}
                flex items-center gap-3 rounded-2xl px-4 py-3
                border ${getAccentClasses()}
                shadow-[var(--shadow-lg)]
                min-w-[280px] max-w-[400px]
            `}
        >
            <div className="shrink-0">
                {getIcon()}
            </div>
            <p className="text-sm font-medium text-[var(--text-primary)] flex-1">{message}</p>
            <button
                onClick={() => {
                    setIsExiting(true);
                    setTimeout(onClose, 200);
                }}
                className="p-1 rounded-md hover:bg-[var(--bg-tertiary)] transition-colors text-[var(--text-tertiary)] hover:text-[var(--text-primary)] shrink-0"
            >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
            </button>
        </div>
    );
}

interface ToastContainerProps {
    toasts: Array<{ id: string; message: string; type: "success" | "error" | "info" }>;
    removeToast: (id: string) => void;
}

export function ToastContainer({ toasts, removeToast }: ToastContainerProps) {
    return (
        <div className="fixed bottom-6 right-6 z-[1000] flex flex-col gap-2.5">
            {toasts.map((toast) => (
                <Toast
                    key={toast.id}
                    message={toast.message}
                    type={toast.type}
                    onClose={() => removeToast(toast.id)}
                />
            ))}
        </div>
    );
}

// Hook for managing toasts
export function useToast() {
    const [toasts, setToasts] = useState<Array<{ id: string; message: string; type: "success" | "error" | "info" }>>([]);

    const addToast = (message: string, type: "success" | "error" | "info" = "info") => {
        const id = Date.now().toString();
        setToasts((prev) => [...prev, { id, message, type }]);
    };

    const removeToast = (id: string) => {
        setToasts((prev) => prev.filter((toast) => toast.id !== id));
    };

    return { toasts, addToast, removeToast };
}
