"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { login } from "../lib/api";
import { setToken } from "../lib/auth";
import { Lightning, Spinner } from "@phosphor-icons/react";
import { ThemeLanguageToggle } from "./ThemeLanguageToggle";
import { FormField } from "./ui/form-field";
import { Input } from "./ui/input";
import { Button } from "./ui/button";
import { AppFooter } from "./app-footer";
import { useLanguage } from "../context/LanguageContext";

export default function LoginForm() {
  const router = useRouter();
  const { t } = useLanguage();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setErrorMsg("");
    try {
      const res = await login({ username, password, totp_code: totp || undefined });
      setToken(res.access_token);
      router.push("/dashboard");
    } catch (err: any) {
      const msg = err?.message || "";
      let displayMsg = t("login_failed");
      const lowerMsg = msg.toLowerCase();

      if (lowerMsg.includes("totp")) {
        displayMsg = t("totp_error");
      } else if (lowerMsg.includes("invalid") || lowerMsg.includes("credentials") || lowerMsg.includes("password")) {
        displayMsg = t("user_or_pass_error");
      } else if (!msg) {
        displayMsg = t("login_failed");
      }
      setErrorMsg(displayMsg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div id="login-view" className="flex min-h-screen flex-col bg-[var(--bg-primary)] text-[var(--text-primary)]">
      <nav className="navbar px-4 py-3 sm:px-5 sm:py-0">
        <div className="min-w-0 flex flex-1 items-center gap-3">
          <div className="inline-flex h-10 w-10 items-center justify-center rounded-2xl bg-[var(--accent)] text-white shadow-sm">
            <Lightning weight="fill" size={20} />
          </div>
          <div className="min-w-0">
            <h1 className="truncate text-[15px] font-semibold tracking-tight sm:text-base md:text-[17px]">TG Sign Plus</h1>
          </div>
        </div>
        <div className="top-right-actions shrink-0 flex-nowrap justify-end gap-2">
          <ThemeLanguageToggle />
        </div>
      </nav>

      <div className="mx-auto flex w-full max-w-[1200px] flex-1 items-center px-4 py-6 sm:px-6 sm:py-10">
        <div className="grid w-full items-center gap-8 lg:grid-cols-[minmax(0,1fr)_420px] lg:gap-12">
          <section className="hidden lg:block">
            <div className="max-w-[520px]">
              <div className="inline-flex h-16 w-16 items-center justify-center rounded-[24px] bg-[var(--accent)] text-white shadow-[var(--shadow-lg)]">
                <Lightning weight="fill" size={32} />
              </div>
              <h2 className="mt-6 text-4xl font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                TG Sign Plus
              </h2>
              <p className="mt-4 max-w-[440px] text-base leading-7 text-[var(--text-secondary)]">
                Telegram 自动化管理面板。支持多账号管理、配置自动签到任务。
              </p>
            </div>
          </section>

          <section className="w-full">
            <div className="glass-panel mx-auto w-full max-w-[420px] p-5 sm:p-8">
              <div className="mb-6 lg:hidden">
                <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--accent)] text-white shadow-sm">
                  <Lightning weight="fill" size={24} />
                </div>
                <h2 className="mt-4 text-[26px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  TG Sign Plus
                </h2>
              </div>

              <form onSubmit={handleSubmit} className="space-y-5" autoComplete="off">
                <div className="space-y-4">
                  <FormField label={t("username")} htmlFor="login-username">
                    <Input
                      id="login-username"
                      type="text"
                      name="username"
                      className="h-11"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      placeholder={t("username")}
                      autoComplete="off"
                    />
                  </FormField>

                  <FormField label={t("password")} htmlFor="login-password">
                    <Input
                      id="login-password"
                      type="password"
                      name="password"
                      className="h-11"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder={t("password")}
                      autoComplete="new-password"
                    />
                  </FormField>

                  <FormField label={t("totp")} htmlFor="login-totp" hint={t("totp_placeholder")}>
                    <Input
                      id="login-totp"
                      type="text"
                      name="totp"
                      className="h-11"
                      value={totp}
                      onChange={(e) => setTotp(e.target.value)}
                      placeholder={t("totp")}
                      autoComplete="off"
                    />
                  </FormField>
                </div>

                {errorMsg ? (
                  <div className="rounded-xl border border-[var(--danger)]/20 bg-[var(--danger-muted)] p-3 text-center text-[12px] font-medium text-[var(--danger)]" role="alert">
                    {errorMsg}
                  </div>
                ) : null}

                <Button className="h-12 w-full font-semibold" type="submit" disabled={loading}>
                  {loading ? (
                    <div className="flex items-center justify-center gap-2">
                      <Spinner className="animate-spin" size={18} />
                      <span>{t("login_loading")}</span>
                    </div>
                  ) : (
                    <span className="text-sm">{t("login")}</span>
                  )}
                </Button>
              </form>
            </div>
          </section>
        </div>
      </div>

      <AppFooter />
    </div>
  );
}
