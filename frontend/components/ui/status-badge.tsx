import * as React from "react";
import { cn } from "../../lib/utils";

const toneMap = {
  neutral: "bg-[var(--bg-tertiary)] text-[var(--text-secondary)] border-[var(--border-primary)]",
  primary: "bg-[var(--accent-muted)] text-[var(--accent)] border-transparent",
  success: "bg-[var(--success-muted)] text-[var(--success)] border-transparent",
  danger: "bg-[var(--danger-muted)] text-[var(--danger)] border-transparent",
  warning: "bg-[var(--warning-muted)] text-[var(--warning)] border-transparent",
};

interface StatusBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: keyof typeof toneMap;
}

export function StatusBadge({ tone = "neutral", className, ...props }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold tracking-[0.12em] uppercase",
        toneMap[tone],
        className,
      )}
      {...props}
    />
  );
}
