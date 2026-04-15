import * as React from "react";
import { cn } from "../../lib/utils";

export interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  danger?: boolean;
  activeTone?: "default" | "primary" | "success" | "danger" | "warning";
}

const toneClassMap = {
  default: "text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]",
  primary: "text-[var(--accent)] hover:bg-[var(--accent-muted)]",
  success: "text-[var(--success)] hover:bg-[var(--success-muted)]",
  danger: "text-[var(--danger)] hover:bg-[var(--danger-muted)]",
  warning: "text-[var(--warning)] hover:bg-[var(--warning-muted)]",
};

export const IconButton = React.forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ className, danger, activeTone = "default", type = "button", ...props }, ref) => {
    const tone = danger ? "danger" : activeTone;

    return (
      <button
        ref={ref}
        type={type}
        className={cn(
          "inline-flex h-9 w-9 items-center justify-center rounded-[12px] border border-transparent transition-all duration-150 active:scale-[0.98]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/30 focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-primary)]",
          "disabled:pointer-events-none disabled:opacity-40",
          toneClassMap[tone],
          className,
        )}
        {...props}
      />
    );
  }
);

IconButton.displayName = "IconButton";
