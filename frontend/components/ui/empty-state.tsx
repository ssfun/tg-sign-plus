import * as React from "react";
import { Card } from "./card";
import { cn } from "../../lib/utils";

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  onClick?: () => void;
  className?: string;
}

export function EmptyState({ icon, title, description, action, onClick, className }: EmptyStateProps) {
  const content = (
    <Card className={cn("border-dashed border-[1.5px] p-10 text-center transition-all", onClick && "cursor-pointer hover:border-[var(--accent)] hover:bg-[var(--accent-muted)]", className)}>
      {icon ? (
        <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-[var(--bg-tertiary)] text-[var(--text-tertiary)]">
          {icon}
        </div>
      ) : null}
      <h3 className="mb-2 text-lg font-semibold text-[var(--text-primary)]">{title}</h3>
      {description ? <p className="text-sm text-[var(--text-secondary)]">{description}</p> : null}
      {action ? <div className="mt-5 flex justify-center">{action}</div> : null}
    </Card>
  );

  if (!onClick) return content;

  return (
    <button type="button" className="w-full text-left" onClick={onClick}>
      {content}
    </button>
  );
}
