"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAuth } from "@/context/AuthContext";

export default function Navbar() {
  const { user, logout } = useAuth();
  const router = useRouter();

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  const initials = user?.full_name?.charAt(0).toUpperCase() ?? "?";

  return (
    <header className="bg-white border-b border-slate-200 shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-8 h-8 bg-indigo-700 rounded">
              <svg
                className="w-5 h-5 text-white"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                />
              </svg>
            </div>
            <span className="text-xl font-semibold text-slate-900 tracking-tight">CaseVault</span>
          </div>

          {/* Nav links */}
          <nav className="hidden md:flex items-center gap-6">
            <Link
              href="/"
              className="text-sm font-medium text-slate-500 hover:text-slate-900 transition-colors"
            >
              Dashboard
            </Link>
            <Link
              href="/cases"
              className="text-sm font-medium text-slate-500 hover:text-slate-900 transition-colors"
            >
              Cases
            </Link>
            <Link
              href="/clients"
              className="text-sm font-medium text-slate-500 hover:text-slate-900 transition-colors"
            >
              Clients
            </Link>
            <Link
              href="/search"
              className="text-sm font-medium text-slate-500 hover:text-slate-900 transition-colors"
            >
              Search
            </Link>
            <Link
              href="/chat"
              className="text-sm font-medium text-slate-500 hover:text-slate-900 transition-colors"
            >
              Chat
            </Link>
            <Link
              href="/agent"
              className="text-sm font-medium text-slate-500 hover:text-slate-900 transition-colors"
            >
              Agent
            </Link>
          </nav>

          {/* User section */}
          <div className="flex items-center gap-3">
            {user && (
              <>
                <div className="hidden sm:block text-right">
                  <p className="text-xs font-medium text-slate-700">{user.full_name}</p>
                  <p className="text-xs text-slate-400">{user.role}</p>
                </div>
                <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-700 text-sm font-semibold">
                  {initials}
                </div>
                <button
                  onClick={handleLogout}
                  className="text-xs font-medium text-slate-500 hover:text-slate-900 transition-colors px-2 py-1 rounded hover:bg-slate-100"
                >
                  Sign out
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
