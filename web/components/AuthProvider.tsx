"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { signOut } from "firebase/auth";
import { apiFetch, type AuthSession } from "@/lib/api";
import { getIdentityPlatformAuth } from "@/lib/identityPlatform";

type AuthContextValue = {
  session: AuthSession;
  loading: boolean;
  refreshSession: () => Promise<AuthSession>;
  logout: () => Promise<void>;
};

const EMPTY_SESSION: AuthSession = {
  authenticated: false,
  user: null,
  session_expires_at: null,
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<AuthSession>(EMPTY_SESSION);
  const [loading, setLoading] = useState(true);

  const refreshSession = async () => {
    try {
      const nextSession = await apiFetch<AuthSession>("/auth/session");
      setSession(nextSession);
      return nextSession;
    } catch {
      setSession(EMPTY_SESSION);
      return EMPTY_SESSION;
    } finally {
      setLoading(false);
    }
  };

  const logout = async () => {
    try {
      await apiFetch<AuthSession>("/auth/session", { method: "DELETE" });
    } catch {
      // noop
    }

    try {
      const auth = await getIdentityPlatformAuth();
      await signOut(auth);
    } catch {
      // noop
    }

    setSession(EMPTY_SESSION);
    setLoading(false);
  };

  useEffect(() => {
    void refreshSession();
  }, []);

  const value: AuthContextValue = {
    session,
    loading,
    refreshSession,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuthSession() {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuthSession must be used within AuthProvider");
  }
  return value;
}
