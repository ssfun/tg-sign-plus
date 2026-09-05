import * as React from "react";
import { useEffect, useId, useRef } from "react";

import { X } from "@phosphor-icons/react";
import { Card, CardContent, CardHeader, CardTitle } from "./card";
import { IconButton } from "./icon-button";
import { cn } from "../../lib/utils";

const modalStack: HTMLElement[] = [];
let savedOverflow: { body: string; html: string } | null = null;

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
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  const titleId = useId();
  const descriptionId = useId();
  useEffect(() => { closeRef.current = onClose; }, [onClose]);
  useEffect(() => {
    if (!open || !dialogRef.current) return;
    const dialog = dialogRef.current;
    const previousFocus = document.activeElement as HTMLElement | null;
    if (modalStack.length === 0) {
      savedOverflow = { body: document.body.style.overflow, html: document.documentElement.style.overflow };
    }
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
    modalStack.push(dialog);
    const isTop = () => modalStack[modalStack.length - 1] === dialog;
    dialog.focus();
    const focusables = () => Array.from(dialog.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], summary, [tabindex]:not([tabindex="-1"])'
    )).filter(element => element.tabIndex >= 0 && !element.closest('[hidden], [inert]') && element.getClientRects().length > 0);
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!isTop()) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        closeRef.current();
      } else if (event.key === "Tab") {
        const elements = focusables();
        const first = elements[0];
        const last = elements[elements.length - 1];
        if (!first) { event.preventDefault(); dialog.focus(); }
        else if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
          event.preventDefault(); last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog)) {
          event.preventDefault(); first.focus();
        }
      }
    };
    const handleFocus = (event: FocusEvent) => {
      if (isTop() && !dialog.contains(event.target as Node)) dialog.focus();
    };
    document.addEventListener("keydown", handleKeyDown, true);
    document.addEventListener("focusin", handleFocus);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
      document.removeEventListener("focusin", handleFocus);
      const wasTop = isTop();
      modalStack.splice(modalStack.indexOf(dialog), 1);
      if (modalStack.length === 0 && savedOverflow) {
        document.body.style.overflow = savedOverflow.body;
        document.documentElement.style.overflow = savedOverflow.html;
        savedOverflow = null;
      }
      if (wasTop && previousFocus?.isConnected) previousFocus.focus();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/55 p-3 backdrop-blur-md animate-fade-in sm:p-4 md:p-6 dark:bg-black/78"
      onClick={onClose}
    >
      <Card
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={cn(
          "flex max-h-[calc(100dvh-24px)] w-full max-w-2xl flex-col overflow-hidden border border-[var(--border-primary)] bg-[var(--bg-secondary)] shadow-[var(--shadow-modal)] ring-1 ring-black/5 animate-scale-in",
          className
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <CardHeader className="flex shrink-0 flex-row items-start justify-between gap-4 border-b border-[var(--border-secondary)] bg-[var(--bg-tertiary)]">
          <div className="min-w-0 flex-1">
            <CardTitle id={titleId} className="text-base md:text-lg">{title}</CardTitle>
            {description ? <p id={descriptionId} className="mt-1.5 break-words text-sm text-[var(--text-secondary)]">{description}</p> : null}
          </div>
          <IconButton aria-label="Close modal" onClick={onClose} className="h-9 w-9 shrink-0 border-[var(--border-secondary)] bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
            <X weight="bold" />
          </IconButton>
        </CardHeader>
        <CardContent className={cn("max-h-[min(78vh,720px)] overflow-y-auto bg-[var(--bg-secondary)] p-4 md:p-5", contentClassName, "min-h-0")}>{children}</CardContent>
        {footer ? <div className="shrink-0 border-t border-[var(--border-secondary)] bg-[var(--bg-secondary)] px-4 py-4 shadow-[0_-1px_0_rgba(255,255,255,0.04)] md:px-5">{footer}</div> : null}
      </Card>
    </div>
  );
}
