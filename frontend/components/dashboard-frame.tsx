"use client";

import * as React from "react";
import Link from "next/link";
import { CaretLeft } from "@phosphor-icons/react";
import { ThemeLanguageToggle } from "./ThemeLanguageToggle";
import { ToastContainer } from "./ui/toast";
import { IconButton } from "./ui/icon-button";
import { AppFooter } from "./app-footer";

interface ToastItem {
  id: string;
  message: string;
  type: "success" | "error" | "info";
}

interface DashboardFrameProps {
  title: React.ReactNode;
  backHref?: string;
  backLabel?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  mainClassName?: string;
  toasts?: ToastItem[];
  removeToast?: (id: string) => void;
  showThemeLanguageToggle?: boolean;
}

export function DashboardFrame({
  title,
  backHref,
  backLabel,
  actions,
  children,
  className,
  mainClassName,
  toasts,
  removeToast,
  showThemeLanguageToggle = true,
}: DashboardFrameProps) {
  return (
    <div className={className ?? "w-full h-full flex flex-col bg-[var(--bg-primary)]"}>
      <nav className="navbar">
        <div className="min-w-0 flex flex-1 items-center gap-3">
          {backHref ? (
            <Link href={backHref} aria-label={backLabel ?? "Back"}>
              <IconButton aria-label={backLabel ?? "Back"} title={backLabel ?? "Back"}>
                <CaretLeft weight="bold" size={16} />
              </IconButton>
            </Link>
          ) : null}
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-base font-semibold tracking-tight text-[var(--text-primary)] md:text-[17px]">{title}</h1>
          </div>
        </div>
        <div className="top-right-actions shrink-0 flex-wrap justify-end">
          {actions}
          {showThemeLanguageToggle ? <ThemeLanguageToggle /> : null}
        </div>
      </nav>

      <main className={mainClassName ?? "main-content"}>{children}</main>
      <AppFooter />

      {toasts && removeToast ? <ToastContainer toasts={toasts} removeToast={removeToast} /> : null}
    </div>
  );
}
