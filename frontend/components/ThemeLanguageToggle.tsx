"use client";

import { useTheme } from "../context/ThemeContext";
import { useLanguage } from "../context/LanguageContext";
import { Translate, Sun, Moon } from "@phosphor-icons/react";
import { IconButton } from "./ui/icon-button";

export function ThemeLanguageToggle() {
    const { theme, toggleTheme } = useTheme();
    const { language, setLanguage, t } = useLanguage();

    return (
        <div className="flex items-center gap-1">
            <IconButton
                onClick={() => setLanguage(language === 'zh' ? 'en' : 'zh')}
                title={language === 'zh' ? t("switch_to_english") : t("switch_to_chinese")}
                aria-label={language === 'zh' ? t("switch_to_english") : t("switch_to_chinese")}
            >
                <Translate weight="bold" size={18} />
            </IconButton>

            <IconButton
                onClick={toggleTheme}
                title={theme === 'dark' ? t("switch_to_light") : t("switch_to_dark")}
                aria-label={theme === 'dark' ? t("switch_to_light") : t("switch_to_dark")}
            >
                {theme === 'dark' ? <Sun weight="bold" size={18} /> : <Moon weight="bold" size={18} />}
            </IconButton>
        </div>
    );
}
