let accessToken: string | null = null;
let refreshPromise: Promise<string | null> | null = null;

const listeners = new Set<(token: string | null) => void>();

const notify = () => {
  Array.from(listeners).forEach((listener) => {
    listener(accessToken);
  });
};

export const getToken = (): string | null => accessToken;

export const setToken = (token: string | null) => {
  accessToken = token;
  notify();
};

export const clearToken = () => {
  accessToken = null;
  notify();
};

export const subscribeToken = (listener: (token: string | null) => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

export const refreshAccessToken = async (): Promise<string | null> => {
  if (refreshPromise) {
    return refreshPromise;
  }

  refreshPromise = (async () => {
    const res = await fetch("/api/auth/refresh", {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
      },
    });

    if (!res.ok) {
      clearToken();
      return null;
    }

    const data = await res.json();
    const token = typeof data?.access_token === "string" ? data.access_token : null;
    setToken(token);
    return token;
  })();

  try {
    return await refreshPromise;
  } finally {
    refreshPromise = null;
  }
};

export const ensureAccessToken = async (): Promise<string | null> => {
  if (accessToken) {
    return accessToken;
  }
  return refreshAccessToken();
};

export const logout = async () => {
  try {
    await fetch("/api/auth/logout", {
      method: "POST",
      credentials: "include",
      cache: "no-store",
    });
  } catch {
    // ignore logout errors
  }
  clearToken();
  if (typeof window !== "undefined") {
    window.location.href = "/";
  }
};

