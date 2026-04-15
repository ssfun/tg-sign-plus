"use client";

import { Spinner } from "@phosphor-icons/react";

interface PageLoadingProps {
  message?: string;
  fullScreen?: boolean;
}

export function PageLoading({ message = "Loading...", fullScreen = false }: PageLoadingProps) {
  return (
    <div
      className={fullScreen
        ? "min-h-screen flex flex-col items-center justify-center gap-3 px-4 text-center text-[var(--text-tertiary)]"
        : "w-full py-20 flex flex-col items-center justify-center gap-3 px-4 text-center text-[var(--text-tertiary)]"
      }
      role="status"
      aria-live="polite"
    >
      <Spinner size={24} weight="bold" className="animate-spin text-[var(--accent)]" />
      <p className="text-xs font-semibold uppercase tracking-[0.15em] text-[var(--text-tertiary)]">{message}</p>
    </div>
  );
}
