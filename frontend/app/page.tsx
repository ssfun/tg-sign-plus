"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import LoginForm from "../components/login-form";
import { PageLoading } from "../components/ui/page-loading";
import { ensureAccessToken } from "../lib/auth";

export default function Home() {
  const router = useRouter();
  const [hasSession, setHasSession] = useState(false);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    let mounted = true;

    void (async () => {
      const token = await ensureAccessToken();
      if (!mounted) return;
      setHasSession(Boolean(token));

      if (token && window.location.pathname === "/") {
        router.replace("/dashboard");
        return;
      }

      setChecking(false);
    })();

    return () => {
      mounted = false;
    };
  }, [router]);

  if (checking || hasSession) {
    return <PageLoading fullScreen message="Redirecting..." />;
  }

  return <LoginForm />;
}

