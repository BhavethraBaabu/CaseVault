"use client";

/**
 * Authentication context.
 *
 * Provides: user, isLoading, login, logout, register.
 *
 * Token storage: localStorage.
 * Trade-off: localStorage is vulnerable to XSS. For production, prefer
 * httpOnly cookies managed by the backend (removes XSS token-theft risk
 * but requires CSRF protection). localStorage is acceptable for Day 2.
 *
 * IMPORTANT: frontend auth state controls UX only.
 * The backend independently enforces authentication on every request.
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { UserResponse, api } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AuthContextValue {
  user: UserResponse | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  register: (email: string, password: string, fullName: string) => Promise<UserResponse>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // On mount: check for an existing token and validate it with the backend.
  // setState calls are inside Promise callbacks (not synchronous effect body)
  // to avoid cascading re-renders on initial hydration.
  useEffect(() => {
    const init = async () => {
      const token = localStorage.getItem("access_token");
      if (!token) return;
      try {
        const u = await api.getCurrentUser();
        setUser(u);
      } catch {
        localStorage.removeItem("access_token");
      }
    };
    init().finally(() => setIsLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const { access_token } = await api.login(email, password);
    localStorage.setItem("access_token", access_token);
    const currentUser = await api.getCurrentUser();
    setUser(currentUser);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("access_token");
    setUser(null);
    // Notify the backend (best-effort; token remains valid until exp).
    api.logout().catch(() => {});
  }, []);

  const register = useCallback(
    (email: string, password: string, fullName: string) =>
      api.register(email, password, fullName),
    [],
  );

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout, register }}>
      {children}
    </AuthContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
