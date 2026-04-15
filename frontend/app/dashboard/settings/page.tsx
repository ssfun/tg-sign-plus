"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ensureAccessToken, logout, setToken } from "../../../lib/auth";
import {
    changePassword,
    changeUsername,
    getTOTPStatus,
    setupTOTP,
    enableTOTP,
    disableTOTP,
    exportAllConfigs,
    importAllConfigs,
    getAIConfig,
    saveAIConfig,
    testAIConnection,
    deleteAIConfig,
    AIConfig,
    getGlobalSettings,
    saveGlobalSettings,
    GlobalSettings,
    getTelegramConfig,
    saveTelegramConfig,
    resetTelegramConfig,
    TelegramConfig,
} from "../../../lib/api";
import {
    User,
    Lock,
    ShieldCheck,
    Gear,
    Cpu,
    DownloadSimple,
    Spinner,
    ArrowUDownLeft,
    FloppyDisk,
    WarningCircle,
    Trash,
    Robot as BotIcon,
    Terminal,
    SignOut,
    Lightning,
    CaretLeft,
} from "@phosphor-icons/react";
import Link from "next/link";
import { ToastContainer, useToast } from "../../../components/ui/toast";
import { PageLoading } from "../../../components/ui/page-loading";
import { IconButton } from "../../../components/ui/icon-button";
import { StatusBadge } from "../../../components/ui/status-badge";
import { ModalShell } from "../../../components/ui/modal-shell";
import { FormField } from "../../../components/ui/form-field";
import { Input } from "../../../components/ui/input";
import { Button } from "../../../components/ui/button";
import { ThemeLanguageToggle } from "../../../components/ThemeLanguageToggle";
import { AppFooter } from "../../../components/app-footer";
import { useLanguage } from "../../../context/LanguageContext";

export default function SettingsPage() {
    const router = useRouter();
    const { t, language } = useLanguage();
    const { toasts, addToast, removeToast } = useToast();
        const [userLoading, setUserLoading] = useState(false);
    const [pwdLoading, setPwdLoading] = useState(false);
    const [totpLoading, setTotpLoading] = useState(false);
    const [configLoading, setConfigLoading] = useState(false);
    const [telegramLoading, setTelegramLoading] = useState(false);

    // 用户名修改
    const [usernameForm, setUsernameForm] = useState({
        newUsername: "",
        password: "",
    });

    // 密码修改
    const [passwordForm, setPasswordForm] = useState({
        oldPassword: "",
        newPassword: "",
        confirmPassword: "",
    });

    // 2FA 状态
    const [totpEnabled, setTotpEnabled] = useState(false);
    const [totpSecret, setTotpSecret] = useState("");
    const [totpCode, setTotpCode] = useState("");
    const [disableTotpCode, setDisableTotpCode] = useState("");
    const [showTotpSetup, setShowTotpSetup] = useState(false);
    const [showDisableTotpDialog, setShowDisableTotpDialog] = useState(false);
    const [showDeleteAIDialog, setShowDeleteAIDialog] = useState(false);
    const [showResetTelegramDialog, setShowResetTelegramDialog] = useState(false);

    // 配置导入导出
    const [importConfig, setImportConfig] = useState("");
    const [overwriteConfig, setOverwriteConfig] = useState(false);

    // AI 配置
    const [aiConfig, setAIConfigState] = useState<AIConfig | null>(null);
    const [aiForm, setAIForm] = useState({
        api_key: "",
        base_url: "",
        model: "gpt-4o",
    });
    const [aiTestResult, setAITestResult] = useState<string | null>(null);
    const [aiTestStatus, setAITestStatus] = useState<"success" | "error" | null>(null);
    const [aiTesting, setAITesting] = useState(false);

    // 全局设置
    const [globalSettings, setGlobalSettings] = useState<GlobalSettings>({ sign_interval: null, log_retention_days: 7, data_dir: null });

    // Telegram API 配置
    const [telegramConfig, setTelegramConfig] = useState<TelegramConfig | null>(null);
    const [telegramForm, setTelegramForm] = useState({
        api_id: "",
        api_hash: "",
    });

    const [checking, setChecking] = useState(true);

    const formatErrorMessage = (key: string, err?: any) => {
        const base = t(key);
        const code = err?.code;
        return code ? `${base} (${code})` : base;
    };

    useEffect(() => {
        let mounted = true;

        void (async () => {
            const tokenStr = await ensureAccessToken();
            if (!mounted) return;
            if (!tokenStr) {
                router.replace("/");
                return;
            }
            setChecking(false);
            loadTOTPStatus();
            loadAIConfig();
            loadGlobalSettings();
            loadTelegramConfig();
        })();

        return () => {
            mounted = false;
        };
    }, [router]);

    const loadTOTPStatus = async () => {
        try {
            const res = await getTOTPStatus();
            setTotpEnabled(res.enabled);
        } catch (err) { }
    };

    const loadAIConfig = async () => {
        try {
            const config = await getAIConfig();
            setAIConfigState(config);
            if (config) {
                setAIForm({
                    api_key: "", // 不回填密钥
                    base_url: config.base_url || "",
                    model: config.model || "gpt-4o",
                });
            }
        } catch (err) { }
    };

    const loadGlobalSettings = async () => {
        try {
            const settings = await getGlobalSettings();
            setGlobalSettings(settings);
        } catch (err) { }
    };

    const loadTelegramConfig = async () => {
        try {
            const config = await getTelegramConfig();
            setTelegramConfig(config);
            if (config) {
                setTelegramForm({
                    api_id: config.api_id?.toString() || "",
                    api_hash: config.api_hash || "",
                });
            }
        } catch (err) { }
    };

    const handleChangeUsername = async () => {
        if (!usernameForm.newUsername || !usernameForm.password) {
            addToast(t("form_incomplete"), "error");
            return;
        }
        try {
            setUserLoading(true);
            const res = await changeUsername(usernameForm.newUsername, usernameForm.password);
            addToast(t("username_changed"), "success");
            if (res.access_token) {
                setToken(res.access_token);
            }
            setUsernameForm({ newUsername: "", password: "" });
        } catch (err: any) {
            addToast(formatErrorMessage("change_failed", err), "error");
        } finally {
            setUserLoading(false);
        }
    };

    const handleChangePassword = async () => {
        if (!passwordForm.oldPassword || !passwordForm.newPassword) {
            addToast(t("form_incomplete"), "error");
            return;
        }
        if (passwordForm.newPassword !== passwordForm.confirmPassword) {
            addToast(t("password_mismatch"), "error");
            return;
        }
        try {
            setPwdLoading(true);
            await changePassword(passwordForm.oldPassword, passwordForm.newPassword);
            addToast(t("password_changed"), "success");
            setPasswordForm({ oldPassword: "", newPassword: "", confirmPassword: "" });
        } catch (err: any) {
            addToast(formatErrorMessage("change_failed", err), "error");
        } finally {
            setPwdLoading(false);
        }
    };

    const handleSetupTOTP = async () => {
        try {
            setTotpLoading(true);
            const res = await setupTOTP();
            setTotpSecret(res.secret);
            setShowTotpSetup(true);
        } catch (err: any) {
            addToast(formatErrorMessage("setup_failed", err), "error");
        } finally {
            setTotpLoading(false);
        }
    };

    const handleEnableTOTP = async () => {
        if (!totpCode) {
            addToast(t("login_code_required"), "error");
            return;
        }
        try {
            setTotpLoading(true);
            await enableTOTP(totpCode);
            addToast(t("two_factor_enabled"), "success");
            setTotpEnabled(true);
            setShowTotpSetup(false);
            setTotpCode("");
        } catch (err: any) {
            addToast(formatErrorMessage("enable_failed", err), "error");
        } finally {
            setTotpLoading(false);
        }
    };

    const handleDisableTOTP = async () => {
        if (!disableTotpCode) {
            addToast(t("login_code_required"), "error");
            return;
        }
        try {
            setTotpLoading(true);
            await disableTOTP(disableTotpCode);
            addToast(t("two_factor_disabled"), "success");
            setTotpEnabled(false);
            setDisableTotpCode("");
            setShowDisableTotpDialog(false);
        } catch (err: any) {
            addToast(formatErrorMessage("disable_failed", err), "error");
        } finally {
            setTotpLoading(false);
        }
    };

    const handleExport = async () => {
        try {
            setConfigLoading(true);
            const config = await exportAllConfigs();
            const blob = new Blob([JSON.stringify(config, null, 2)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "tg-signer-config.json";
            a.click();
            URL.revokeObjectURL(url);
            addToast(t("export_success"), "success");
        } catch (err: any) {
            addToast(formatErrorMessage("export_failed", err), "error");
        } finally {
            setConfigLoading(false);
        }
    };

    const handleImport = async () => {
        if (!importConfig) {
            addToast(t("import_empty"), "error");
            return;
        }
        try {
            setConfigLoading(true);
            await importAllConfigs(importConfig, overwriteConfig);
            addToast(t("import_success"), "success");
            setImportConfig("");
            loadAIConfig();
            loadGlobalSettings();
            loadTelegramConfig();
        } catch (err: any) {
            addToast(formatErrorMessage("import_failed", err), "error");
        } finally {
            setConfigLoading(false);
        }
    };

    const handleSaveAI = async () => {
        try {
            setConfigLoading(true);
            const payload: { api_key?: string; base_url?: string; model?: string } = {
                base_url: aiForm.base_url.trim() || undefined,
                model: aiForm.model.trim() || undefined,
            };
            const nextApiKey = aiForm.api_key.trim();
            if (nextApiKey) {
                payload.api_key = nextApiKey;
            }
            await saveAIConfig(payload);
            addToast(t("ai_save_success"), "success");
            loadAIConfig();
        } catch (err: any) {
            addToast(formatErrorMessage("save_failed", err), "error");
        } finally {
            setConfigLoading(false);
        }
    };

    const handleTestAI = async () => {
        try {
            setAITesting(true);
            setAITestResult(null);
            setAITestStatus(null);
            const res = await testAIConnection();
            if (res.success) {
                setAITestStatus("success");
                setAITestResult(t("connect_success"));
            } else {
                setAITestStatus("error");
                setAITestResult(t("connect_failed"));
            }
        } catch (err: any) {
            setAITestStatus("error");
            setAITestResult(formatErrorMessage("test_failed", err));
        } finally {
            setAITesting(false);
        }
    };

    const handleDeleteAI = async () => {
        try {
            setConfigLoading(true);
            await deleteAIConfig();
            addToast(t("ai_delete_success"), "success");
            setAIConfigState(null);
            setAIForm({ api_key: "", base_url: "", model: "gpt-4o" });
            setShowDeleteAIDialog(false);
        } catch (err: any) {
            addToast(formatErrorMessage("delete_failed", err), "error");
        } finally {
            setConfigLoading(false);
        }
    };

    const handleSaveGlobal = async () => {
        try {
            setConfigLoading(true);
            await saveGlobalSettings(globalSettings);
            addToast(t("global_save_success"), "success");
        } catch (err: any) {
            addToast(formatErrorMessage("save_failed", err), "error");
        } finally {
            setConfigLoading(false);
        }
    };

    const handleSaveTelegram = async () => {
        if (!telegramForm.api_id || !telegramForm.api_hash) {
            addToast(t("form_incomplete"), "error");
            return;
        }
        try {
            setTelegramLoading(true);
            await saveTelegramConfig({
                api_id: telegramForm.api_id,
                api_hash: telegramForm.api_hash,
            });
            addToast(t("telegram_save_success"), "success");
            loadTelegramConfig();
        } catch (err: any) {
            addToast(formatErrorMessage("save_failed", err), "error");
        } finally {
            setTelegramLoading(false);
        }
    };

    const handleResetTelegram = async () => {
        try {
            setTelegramLoading(true);
            await resetTelegramConfig();
            addToast(t("config_reset"), "success");
            setShowResetTelegramDialog(false);
            loadTelegramConfig();
        } catch (err: any) {
            addToast(formatErrorMessage("operation_failed", err), "error");
        } finally {
            setTelegramLoading(false);
        }
    };

    if (checking) {
        return <PageLoading fullScreen message={t("loading")} />;
    }

    return (
        <div className="flex min-h-screen flex-col bg-[var(--bg-primary)] text-[var(--text-primary)]">
            <nav className="navbar">
                <div className="min-w-0 flex flex-1 items-center gap-3">
                    <span className="inline-flex h-10 w-10 items-center justify-center rounded-2xl bg-[var(--accent)] text-white shadow-sm">
                        <Lightning weight="fill" size={20} />
                    </span>
                    <span className="nav-title truncate text-lg font-bold tracking-tight">TG Sign Plus</span>
                </div>
                <div className="top-right-actions shrink-0 flex-nowrap justify-end gap-1 sm:gap-2">
                    <ThemeLanguageToggle />
                    <IconButton aria-label={t("logout")} title={t("logout")} onClick={logout} danger>
                        <SignOut weight="bold" size={18} />
                    </IconButton>
                </div>
            </nav>

            <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col px-4 pb-10 pt-4 sm:px-6 lg:px-8">
                <div className="mb-5">
                    <Link
                        href="/dashboard"
                        className="inline-flex items-center gap-2 text-sm text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)]"
                    >
                        <CaretLeft weight="bold" size={16} />
                        <span>{language === "zh" ? "返回 Dashboard" : "Back to dashboard"}</span>
                    </Link>
                </div>

                <div id="settings-view" className="space-y-6 animate-float-up">
                    <section className="glass-panel overflow-hidden">
                        <div className="flex flex-col gap-5 p-5 lg:flex-row lg:items-start lg:justify-between">
                            <div className="max-w-2xl space-y-3">
                                <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--text-tertiary)]">
                                    {t("sidebar_settings")}
                                </div>
                                <div>
                                    <h1 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)] sm:text-[30px]">
                                        {language === "zh" ? "设置工作台" : "Settings workspace"}
                                    </h1>
                                </div>
                            </div>
                            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 lg:min-w-[420px]">
                                <div className="rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] p-4">
                                    <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">2FA</div>
                                    <div className="mt-3">
                                        <StatusBadge tone={totpEnabled ? "success" : "danger"}>
                                            {totpEnabled ? t("status_enabled") : t("status_disabled")}
                                        </StatusBadge>
                                    </div>
                                </div>
                                <div className="rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] p-4">
                                    <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">AI</div>
                                    <div className="mt-3">
                                        <StatusBadge tone={aiConfig ? "success" : "neutral"}>
                                            {aiConfig ? t("status_enabled") : t("status_disabled")}
                                        </StatusBadge>
                                    </div>
                                </div>
                                <div className="rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] p-4">
                                    <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">Telegram</div>
                                    <div className="mt-3">
                                        <StatusBadge tone={telegramConfig ? "success" : "neutral"}>
                                            {telegramConfig ? t("status_enabled") : t("status_disabled")}
                                        </StatusBadge>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </section>

                    <section className="glass-panel overflow-hidden">
                        <div className="border-b border-[var(--border-secondary)] px-5 py-4">
                            <div className="flex items-start gap-3">
                                <div className="rounded-xl bg-[var(--accent-muted)] p-2 text-[var(--accent)]">
                                    <User weight="bold" size={18} />
                                </div>
                                <div>
                                    <h2 className="text-base font-semibold text-[var(--text-primary)]">
                                        {language === "zh" ? "账号身份" : "Account identity"}
                                    </h2>
                                </div>
                            </div>
                        </div>
                        <div className="grid grid-cols-1 gap-4 p-5 xl:grid-cols-2">
                            <div className="rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] p-4">
                                <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-[var(--text-primary)]">
                                    <User weight="bold" size={16} />
                                    {t("change_username")}
                                </div>
                                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                                    <FormField label={t("new_username")}>
                                        <Input
                                            placeholder={t("new_username_placeholder")}
                                            value={usernameForm.newUsername}
                                            onChange={(e) => setUsernameForm({ ...usernameForm, newUsername: e.target.value })}
                                        />
                                    </FormField>
                                    <FormField label={t("current_password")}>
                                        <Input
                                            type="password"
                                            placeholder={t("current_password_placeholder")}
                                            value={usernameForm.password}
                                            onChange={(e) => setUsernameForm({ ...usernameForm, password: e.target.value })}
                                        />
                                    </FormField>
                                </div>
                                <div className="mt-4 flex justify-end">
                                    <Button className="w-full sm:w-auto" onClick={handleChangeUsername} disabled={userLoading}>
                                        {userLoading ? <Spinner className="animate-spin" /> : t("change_username")}
                                    </Button>
                                </div>
                            </div>

                            <div className="rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] p-4">
                                <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-[var(--text-primary)]">
                                    <Lock weight="bold" size={16} />
                                    {t("change_password")}
                                </div>
                                <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                                    <FormField label={t("old_password")}>
                                        <Input
                                            type="password"
                                            value={passwordForm.oldPassword}
                                            onChange={(e) => setPasswordForm({ ...passwordForm, oldPassword: e.target.value })}
                                        />
                                    </FormField>
                                    <FormField label={t("new_password")}>
                                        <Input
                                            type="password"
                                            value={passwordForm.newPassword}
                                            onChange={(e) => setPasswordForm({ ...passwordForm, newPassword: e.target.value })}
                                        />
                                    </FormField>
                                    <FormField label={t("confirm_new_password")}>
                                        <Input
                                            type="password"
                                            value={passwordForm.confirmPassword}
                                            onChange={(e) => setPasswordForm({ ...passwordForm, confirmPassword: e.target.value })}
                                        />
                                    </FormField>
                                </div>
                                <div className="mt-4 flex justify-end">
                                    <Button variant="secondary" className="w-full sm:w-auto" onClick={handleChangePassword} disabled={pwdLoading}>
                                        {pwdLoading ? <Spinner className="animate-spin" /> : t("change_password")}
                                    </Button>
                                </div>
                            </div>
                        </div>
                    </section>

                <section className="glass-panel overflow-hidden">
                    <div className="border-b border-[var(--border-secondary)] px-5 py-4">
                        <div className="flex items-start gap-3">
                            <div className="rounded-xl bg-[var(--success-muted)] p-2 text-[var(--success)]">
                                <ShieldCheck weight="bold" size={18} />
                            </div>
                            <div>
                                <h2 className="text-base font-semibold text-[var(--text-primary)]">
                                    {language === "zh" ? "安全" : "Security"}
                                </h2>
                            </div>
                        </div>
                    </div>
                    <div className="space-y-4 p-5">
                        <div className="flex flex-col gap-4 rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] p-4 sm:flex-row sm:items-center sm:justify-between">
                            <div>
                                <div className="text-sm font-semibold text-[var(--text-primary)]">{t("2fa_settings")}</div>
                            </div>
                            <StatusBadge tone={totpEnabled ? "success" : "danger"}>
                                {totpEnabled ? t("status_enabled") : t("status_disabled")}
                            </StatusBadge>
                        </div>

                        {!totpEnabled && !showTotpSetup ? (
                            <div className="rounded-2xl border border-[var(--success)]/15 bg-[var(--success-muted)] p-4">
                                <Button variant="secondary" onClick={handleSetupTOTP} disabled={totpLoading}>
                                    {totpLoading ? <Spinner className="animate-spin" /> : t("start_setup")}
                                </Button>
                            </div>
                        ) : null}

                        {totpEnabled ? (
                            <div className="flex justify-end">
                                <Button variant="secondary" onClick={() => setShowDisableTotpDialog(true)} disabled={totpLoading} className="text-[var(--danger)] hover:bg-[var(--danger-muted)]">
                                    {totpLoading ? <Spinner className="animate-spin" /> : t("disable_2fa")}
                                </Button>
                            </div>
                        ) : null}

                        {showTotpSetup ? (
                            <div className="space-y-4 rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] p-4">
                                <div className="flex flex-col gap-4 md:flex-row md:items-start">
                                    <div className="shrink-0 rounded-lg bg-white p-2">
                                        {/* eslint-disable-next-line @next/next/no-img-element */}
                                        <img src={`/api/user/totp/qrcode`} alt={t("qr_alt")} className="h-28 w-28" />
                                    </div>
                                    <div className="space-y-3">
                                        <div>
                                            <h4 className="mb-1 text-xs font-bold text-[var(--text-primary)]">{t("scan_qr")}</h4>
                                            <p className="text-[10px] text-[var(--text-tertiary)]">{t("scan_qr_desc")}</p>
                                        </div>
                                        <FormField label={t("backup_secret")}>
                                            <Input
                                                readOnly
                                                value={totpSecret}
                                                className="cursor-text font-mono text-[10px] text-[var(--accent)]"
                                                onClick={(e) => (e.target as HTMLInputElement).select()}
                                            />
                                        </FormField>
                                    </div>
                                </div>
                                <div className="max-w-2xl space-y-3">
                                    <FormField label={t("verify_code")}>
                                        <div className="flex flex-col gap-3 sm:flex-row">
                                            <Input
                                                value={totpCode}
                                                onChange={(e) => setTotpCode(e.target.value)}
                                                placeholder={t("totp_code_placeholder")}
                                                className="h-14 flex-1 text-center text-3xl font-bold tracking-[0.5em] sm:tracking-[0.8em]"
                                            />
                                            <Button onClick={handleEnableTOTP} className="h-14 shrink-0 sm:px-6" disabled={totpLoading}>
                                                {totpLoading ? <Spinner className="animate-spin" /> : t("verify")}
                                            </Button>
                                        </div>
                                    </FormField>
                                </div>
                            </div>
                        ) : null}
                    </div>
                </section>

                <section className="glass-panel overflow-hidden">
                    <div className="border-b border-[var(--border-secondary)] px-5 py-4">
                        <div className="flex items-start gap-3">
                            <div className="rounded-xl bg-[var(--accent-muted)] p-2 text-[var(--accent)]">
                                <BotIcon weight="bold" size={18} />
                            </div>
                            <div>
                                <h2 className="text-base font-semibold text-[var(--text-primary)]">
                                    {language === "zh" ? "外部集成" : "Integrations"}
                                </h2>
                            </div>
                        </div>
                    </div>
                    <div className="grid grid-cols-1 gap-6 p-5 xl:grid-cols-2">
                        <div className="rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] p-4">
                            <div className="mb-4 flex items-center justify-between gap-3">
                                <div>
                                    <div className="flex items-center gap-2 text-sm font-semibold text-[var(--text-primary)]">
                                        <BotIcon weight="bold" size={16} />
                                        {t("ai_config")}
                                    </div>
                                    <div className="mt-2">
                                        <StatusBadge tone={aiConfig ? "success" : "neutral"}>
                                            {aiConfig ? t("status_enabled") : t("status_disabled")}
                                        </StatusBadge>
                                    </div>
                                </div>
                                {aiConfig ? (
                                    <Button variant="secondary" onClick={() => setShowDeleteAIDialog(true)} disabled={configLoading} className="text-[var(--danger)] hover:bg-[var(--danger-muted)]">
                                        <Trash weight="bold" size={16} />
                                        {t("delete_ai_config")}
                                    </Button>
                                ) : null}
                            </div>
                            <div className="mb-4 grid grid-cols-1 gap-4 md:grid-cols-2">
                                <div className="md:col-span-2">
                                    <FormField label={t("api_key")} hint={aiConfig?.api_key_masked ? t("api_key_keep_hint") : undefined}>
                                        <Input
                                            type="password"
                                            value={aiForm.api_key}
                                            onChange={(e) => setAIForm({ ...aiForm, api_key: e.target.value })}
                                            placeholder={aiConfig?.api_key_masked || t("api_key")}
                                        />
                                    </FormField>
                                </div>
                                <FormField label={t("base_url")}>
                                    <Input
                                        value={aiForm.base_url}
                                        onChange={(e) => setAIForm({ ...aiForm, base_url: e.target.value })}
                                        placeholder={t("ai_base_url_placeholder")}
                                    />
                                </FormField>
                                <FormField label={t("model")}>
                                    <Input
                                        value={aiForm.model}
                                        onChange={(e) => setAIForm({ ...aiForm, model: e.target.value })}
                                    />
                                </FormField>
                            </div>
                            <div className="flex flex-wrap gap-3">
                                <Button onClick={handleSaveAI} disabled={configLoading}>
                                    {configLoading ? <Spinner className="animate-spin" /> : t("save")}
                                </Button>
                                <Button variant="secondary" onClick={handleTestAI} disabled={aiTesting || configLoading}>
                                    {aiTesting ? <Spinner className="animate-spin" /> : t("test_connection")}
                                </Button>
                            </div>
                            {aiTestResult ? (
                                <div className={`mt-4 rounded-xl border p-3 text-[11px] ${aiTestStatus === "success"
                                    ? "border-[var(--success)]/20 bg-[var(--success-muted)] text-[var(--success)]"
                                    : "border-[var(--danger)]/20 bg-[var(--danger-muted)] text-[var(--danger)]"
                                    }`}>
                                    {aiTestResult}
                                </div>
                            ) : null}
                        </div>

                        <div className="rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] p-4">
                            <div className="mb-4 flex items-center justify-between gap-3">
                                <div>
                                    <div className="flex items-center gap-2 text-sm font-semibold text-[var(--text-primary)]">
                                        <Cpu weight="bold" size={16} />
                                        {t("tg_api_config")}
                                    </div>
                                    <div className="mt-2">
                                        <StatusBadge tone={telegramConfig ? "success" : "neutral"}>
                                            {telegramConfig ? t("status_enabled") : t("status_disabled")}
                                        </StatusBadge>
                                    </div>
                                </div>
                                {telegramConfig ? (
                                    <Button variant="secondary" onClick={() => setShowResetTelegramDialog(true)} disabled={telegramLoading}>
                                        <ArrowUDownLeft weight="bold" size={16} />
                                        {language === "zh" ? "重置 Telegram 配置" : "Reset Telegram config"}
                                    </Button>
                                ) : null}
                            </div>
                            <div className="mb-4 grid grid-cols-1 gap-4 md:grid-cols-2">
                                <FormField label={t("api_id")}>
                                    <Input
                                        value={telegramForm.api_id}
                                        onChange={(e) => setTelegramForm({ ...telegramForm, api_id: e.target.value })}
                                        placeholder={t("tg_api_id_placeholder")}
                                    />
                                </FormField>
                                <FormField label={t("api_hash")}>
                                    <Input
                                        value={telegramForm.api_hash}
                                        onChange={(e) => setTelegramForm({ ...telegramForm, api_hash: e.target.value })}
                                        placeholder={t("tg_api_hash_placeholder")}
                                    />
                                </FormField>
                            </div>
                            <Button onClick={handleSaveTelegram} disabled={telegramLoading}>
                                {telegramLoading ? <Spinner className="animate-spin" /> : t("apply_api_config")}
                            </Button>
                            <div className="mt-4 rounded-xl border border-[var(--warning)]/25 bg-[var(--warning-muted)] p-3.5 text-[10px] font-medium leading-relaxed text-[var(--warning)]">
                                <div className="mb-1.5 flex items-center gap-2">
                                    <Terminal weight="bold" className="text-[var(--warning)]" size={12} />
                                    <span className="font-bold uppercase tracking-wider text-[var(--warning)]">{t("warning_notice")}</span>
                                </div>
                                {t("tg_config_warning")}
                            </div>
                        </div>
                    </div>
                </section>

                <section className="glass-panel overflow-hidden">
                    <div className="border-b border-[var(--border-secondary)] px-5 py-4">
                        <div className="flex items-start gap-3">
                            <div className="rounded-xl bg-[var(--accent)]/10 p-2 text-[var(--accent-hover)]">
                                <Gear weight="bold" size={18} />
                            </div>
                            <div>
                                <h2 className="text-base font-semibold text-[var(--text-primary)]">
                                    {language === "zh" ? "系统与迁移" : "System & migration"}
                                </h2>
                            </div>
                        </div>
                    </div>
                    <div className="grid grid-cols-1 gap-6 p-5 xl:grid-cols-2">
                        <div className="rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] p-4">
                            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-[var(--text-primary)]">
                                <Gear weight="bold" size={16} />
                                {t("global_settings")}
                            </div>
                            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                                <FormField label={t("sign_interval")} hint={t("sign_interval_desc")}>
                                    <Input
                                        type="number"
                                        value={globalSettings.sign_interval === null ? "" : globalSettings.sign_interval}
                                        onChange={(e) => setGlobalSettings({ ...globalSettings, sign_interval: e.target.value ? parseInt(e.target.value) : null })}
                                        placeholder={t("sign_interval_placeholder")}
                                    />
                                </FormField>
                                <FormField label={t("log_retention")}>
                                    <Input
                                        type="number"
                                        value={globalSettings.log_retention_days}
                                        onChange={(e) => setGlobalSettings({ ...globalSettings, log_retention_days: parseInt(e.target.value) || 0 })}
                                    />
                                </FormField>
                                <div className="md:col-span-2">
                                    <FormField label={t("data_dir")} hint={t("data_dir_desc")}>
                                        <Input
                                            value={globalSettings.data_dir || ""}
                                            onChange={(e) => setGlobalSettings({ ...globalSettings, data_dir: e.target.value || null })}
                                            placeholder={t("data_dir_placeholder")}
                                        />
                                    </FormField>
                                    <p className="mt-1 text-[10px] text-[var(--warning)]">{t("data_dir_restart_hint")}</p>
                                </div>
                            </div>
                            <Button className="mt-4" onClick={handleSaveGlobal} disabled={configLoading}>
                                {configLoading ? <Spinner className="animate-spin" /> : t("save_global_params")}
                            </Button>
                        </div>

                        <div className="rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-tertiary)] p-4">
                            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-[var(--text-primary)]">
                                <DownloadSimple weight="bold" size={16} />
                                {t("backup_migration")}
                            </div>
                            <div className="space-y-4">
                                <div className="rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-primary)] p-4">
                                    <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">{t("export_config")}</div>
                                    <p className="mb-3 mt-1 text-[10px] leading-relaxed text-[var(--text-tertiary)]">{t("export_desc")}</p>
                                    <Button variant="secondary" className="w-full" onClick={handleExport} disabled={configLoading}>
                                        {configLoading ? <Spinner className="animate-spin" /> : <FloppyDisk weight="bold" />}
                                        {t("download_json")}
                                    </Button>
                                </div>
                                <div className="rounded-2xl border border-[var(--border-secondary)] bg-[var(--bg-primary)] p-4">
                                    <div className="mb-3 flex items-center justify-between gap-3">
                                        <div>
                                            <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">{t("import_config")}</div>
                                            <p className="mt-1 text-[10px] text-[var(--text-tertiary)]">{t("paste_json")}</p>
                                        </div>
                                        <label className="cursor-pointer text-[10px] font-bold text-[var(--accent)] hover:underline">
                                            {t("upload_json")}
                                            <input
                                                type="file"
                                                accept=".json"
                                                className="hidden"
                                                onChange={(e) => {
                                                    const file = e.target.files?.[0];
                                                    if (file) {
                                                        const reader = new FileReader();
                                                        reader.onload = (ev) => {
                                                            const content = ev.target?.result as string;
                                                            setImportConfig(content);
                                                        };
                                                        reader.readAsText(file);
                                                    }
                                                }}
                                            />
                                        </label>
                                    </div>
                                    <FormField label={t("import_config")} className="sr-only">
                                        <textarea
                                            className="custom-scrollbar w-full rounded-xl border border-[var(--border-secondary)] bg-[var(--bg-primary)] p-3 text-sm text-[var(--text-secondary)] outline-none transition-all placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent)]"
                                            placeholder={t("paste_json")}
                                            value={importConfig}
                                            onChange={(e) => setImportConfig(e.target.value)}
                                        />
                                    </FormField>
                                    <div className="group mb-4 mt-3 flex cursor-pointer items-center gap-3" onClick={() => setOverwriteConfig(!overwriteConfig)}>
                                        <div className={`relative h-7 w-12 rounded-full border-2 shadow-sm transition-all ${overwriteConfig ? "border-[var(--accent)] bg-[var(--accent)]" : "border-[var(--border-secondary)] bg-[var(--bg-primary)]"}`}>
                                            <div className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow-md transition-all ${overwriteConfig ? "left-6" : "left-0.5"}`}></div>
                                        </div>
                                        <span className={`select-none text-[13px] transition-colors ${overwriteConfig ? "font-bold text-[var(--text-primary)]" : "text-[var(--text-tertiary)]"}`}>
                                            {t("overwrite_conflict")}
                                        </span>
                                    </div>
                                    <Button className="w-full" onClick={handleImport} disabled={configLoading}>
                                        {configLoading ? <Spinner className="animate-spin" /> : t("execute_import")}
                                    </Button>
                                </div>
                            </div>
                        </div>
                    </div>
                </section>
            </div>

            <AppFooter />
            {toasts && removeToast ? <ToastContainer toasts={toasts} removeToast={removeToast} /> : null}

            <ModalShell
                open={showDisableTotpDialog}
                title={t("disable_2fa")}
                description={t("two_factor_disable_prompt")}
                onClose={() => {
                    if (!totpLoading) {
                        setShowDisableTotpDialog(false);
                        setDisableTotpCode("");
                    }
                }}
                className="max-w-md"
                footer={
                    <div className="flex gap-3">
                        <Button variant="secondary" className="flex-1" onClick={() => { setShowDisableTotpDialog(false); setDisableTotpCode(""); }} disabled={totpLoading}>{t("cancel")}</Button>
                        <Button variant="destructive" className="flex-1" onClick={handleDisableTOTP} disabled={totpLoading}>{totpLoading ? <Spinner className="animate-spin" /> : t("disable_2fa")}</Button>
                    </div>
                }
            >
                <Input
                    value={disableTotpCode}
                    onChange={(e) => setDisableTotpCode(e.target.value)}
                    placeholder={t("totp_code_placeholder")}
                    className="text-center text-2xl tracking-[0.5em]"
                />
            </ModalShell>

            <ModalShell
                open={showDeleteAIDialog}
                title={t("delete_ai_config")}
                description={t("confirm_delete_ai")}
                onClose={() => {
                    if (!configLoading) {
                        setShowDeleteAIDialog(false);
                    }
                }}
                className="max-w-md"
                footer={
                    <div className="flex gap-3">
                        <Button variant="secondary" className="flex-1" onClick={() => setShowDeleteAIDialog(false)} disabled={configLoading}>{t("cancel")}</Button>
                        <Button variant="destructive" className="flex-1" onClick={handleDeleteAI} disabled={configLoading}>{configLoading ? <Spinner className="animate-spin" /> : t("delete")}</Button>
                    </div>
                }
            >
                <div className="text-sm text-[var(--text-secondary)]">{t("ai_config")}</div>
            </ModalShell>

            <ModalShell
                open={showResetTelegramDialog}
                title={t("restore_default")}
                description={t("confirm_reset_telegram")}
                onClose={() => {
                    if (!telegramLoading) {
                        setShowResetTelegramDialog(false);
                    }
                }}
                className="max-w-md"
                footer={
                    <div className="flex gap-3">
                        <Button variant="secondary" className="flex-1" onClick={() => setShowResetTelegramDialog(false)} disabled={telegramLoading}>{t("cancel")}</Button>
                        <Button variant="secondary" className="flex-1" onClick={handleResetTelegram} disabled={telegramLoading}>{telegramLoading ? <Spinner className="animate-spin" /> : t("restore_default")}</Button>
                    </div>
                }
            >
                <div className="text-sm text-[var(--text-secondary)]">Telegram API</div>
            </ModalShell>
        </div>
        </div>
    );
}
