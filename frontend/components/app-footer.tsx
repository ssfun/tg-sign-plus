import Link from "next/link";

export function AppFooter() {
  return (
    <footer className="border-t border-[var(--border-primary)] bg-[var(--bg-secondary)]/80 px-4 py-4 text-center text-xs text-[var(--text-tertiary)] backdrop-blur-sm">
      <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-center gap-x-1 gap-y-1">
        <span>© 2026 TG Sign Plus</span>
        <span>|</span>
        <Link
          href="https://github.com/ssfun/tg-sign-plus"
          target="_blank"
          rel="noreferrer"
          className="transition-colors hover:text-[var(--text-primary)]"
        >
          @sfun
        </Link>
      </div>
    </footer>
  );
}
