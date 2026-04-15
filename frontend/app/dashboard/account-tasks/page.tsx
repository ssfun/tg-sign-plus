"use client";

import { Suspense } from "react";
import AccountTasksContent from "./AccountTasksContent";
import { PageLoading } from "../../../components/ui/page-loading";
import { useLanguage } from "../../../context/LanguageContext";

export default function AccountTasksPage() {
    const { t } = useLanguage();
    return (
        <Suspense fallback={<PageLoading fullScreen message={t("loading")} />}>
            <AccountTasksContent />
        </Suspense>
    );
}
