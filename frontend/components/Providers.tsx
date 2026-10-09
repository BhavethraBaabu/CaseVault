"use client";

import { AuthProvider } from "@/context/AuthContext";

/**
 * Client-side providers wrapper.
 * Imported by the server-side RootLayout to inject React context.
 */
export default function Providers({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}
