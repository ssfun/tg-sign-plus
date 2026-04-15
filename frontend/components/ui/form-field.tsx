import * as React from "react";
import { Label } from "./label";
import { cn } from "../../lib/utils";

interface FormFieldProps {
  label: React.ReactNode;
  htmlFor?: string;
  hint?: React.ReactNode;
  error?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}

export function FormField({ label, htmlFor, hint, error, className, children }: FormFieldProps) {
  return (
    <div className={cn("space-y-2", className)}>
      <Label htmlFor={htmlFor} className="mb-0 text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--text-secondary)]">
        {label}
      </Label>
      {children}
      {error ? <p className="text-xs text-[var(--danger)]">{error}</p> : null}
      {!error && hint ? <p className="text-xs text-[var(--text-tertiary)]">{hint}</p> : null}
    </div>
  );
}
