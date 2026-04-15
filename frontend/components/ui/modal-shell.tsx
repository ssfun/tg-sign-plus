import * as React from "react";
import { useEffect } from "react";
import { X } from "@phosphor-icons/react";
import { Card, CardContent, CardHeader, CardTitle } from "./card";
import { IconButton } from "./icon-button";
import { cn } from "../../lib/utils";

interface ModalShellProps {
  open: boolean;
  title: React.ReactNode;
  description?: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
  contentClassName?: string;
}

export function ModalShell({
  open,
  title,
  description,
  onClose,
  children,
  footer,
  className,
  contentClassName,
}: ModalShellProps) {
  useEffect(() => {
    if (!open) return;

    const previousBodyOverflow = document.body.style.overflow;
    const previousHtmlOverflow = document.documentElement.style.overflow;

    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousBodyOverflow;
      document.documentElement.style.overflow = previousHtmlOverflow;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/55 p-3 backdrop-blur-md animate-fade-in sm:p-4 md:p-6 dark:bg-black/78"
      onClick={onClose}
    >
      <Card
        className={cn(
          "w-full max-w-2xl overflow-hidden border border-[var(--border-primary)] bg-[var(--bg-secondary)] shadow-[var(--shadow-modal)] ring-1 ring-black/5 animate-scale-in",
          className
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <CardHeader className="flex flex-row items-start justify-between gap-4 border-b border-[var(--border-secondary)] bg-[var(--bg-tertiary)]">
          <div className="min-w-0 flex-1">
            <CardTitle className="text-base md:text-lg">{title}</CardTitle>
            {description ? <p className="mt-1.5 break-words text-sm text-[var(--text-secondary)]">{description}</p> : null}
          </div>
          <IconButton aria-label="Close modal" onClick={onClose} className="h-9 w-9 shrink-0 border-[var(--border-secondary)] bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
            <X weight="bold" />
          </IconButton>
        </CardHeader>
        <CardContent className={cn("max-h-[min(78vh,720px)] overflow-y-auto bg-[var(--bg-secondary)] p-4 md:p-5", contentClassName)}>{children}</CardContent>
        {footer ? <div className="border-t border-[var(--border-secondary)] bg-[var(--bg-secondary)] px-4 py-4 shadow-[0_-1px_0_rgba(255,255,255,0.04)] md:px-5">{footer}</div> : null}
      </Card>
    </div>
  );
}
