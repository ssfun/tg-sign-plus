import { ReactNode } from "react";

export interface DashboardNavbarPreset {
  title: ReactNode;
  backHref?: string;
  backLabel?: string;
}

export const dashboardNavbarPresets: Record<string, Partial<DashboardNavbarPreset>> = {
  settings: {
    title: "sidebar_settings",
    backHref: "/dashboard",
    backLabel: "sidebar_home",
  },
  accountTasks: {
    backHref: "/dashboard",
    backLabel: "sidebar_home",
  },
};

export function resolveDashboardNavbarPreset(
  t: (key: string) => string,
  preset: keyof typeof dashboardNavbarPresets,
  overrides?: Partial<DashboardNavbarPreset>
): DashboardNavbarPreset {
  const base = dashboardNavbarPresets[preset];
  const resolvedTitle = overrides?.title ?? (typeof base.title === "string" ? t(base.title) : base.title) ?? "";

  return {
    title: resolvedTitle,
    backHref: overrides?.backHref ?? base.backHref,
    backLabel: overrides?.backLabel ?? (base.backLabel ? t(base.backLabel) : undefined),
  };
}
