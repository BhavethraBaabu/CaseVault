"use client";

/**
 * Dashboard page — requires authentication.
 *
 * Security note:
 *   The redirect to /login here is a UX convenience only.
 *   All data access is protected by the backend independently.
 *   Frontend route protection ≠ security — it is purely for user experience.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import Navbar from "@/components/Navbar";
import HealthStatus from "@/components/HealthStatus";
import { useAuth } from "@/context/AuthContext";

const stats = [
  { label: "Active Cases", value: "—", note: "Coming in Day 3" },
  { label: "Documents", value: "—", note: "Coming in Day 4" },
  { label: "Clients", value: "—", note: "Coming in Day 3" },
  { label: "AI Searches", value: "—", note: "Coming in Day 5" },
];

const upcomingFeatures = [
  { icon: "📁", title: "Case Management", day: "Day 3" },
  { icon: "📄", title: "Document Upload & Processing", day: "Day 4" },
  { icon: "🤖", title: "AI-Powered RAG Search", day: "Day 5" },
  { icon: "💬", title: "AI Chat Interface", day: "Day 6" },
];

const ROLE_LABELS: Record<string, string> = {
  ADMIN: "Administrator",
  LAWYER: "Lawyer",
  RESTRICTED_LAWYER: "Restricted Lawyer",
};

export default function DashboardPage() {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !user) {
      router.push("/login");
    }
  }, [isLoading, user, router]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="text-sm text-slate-500">Loading…</div>
      </div>
    );
  }

  if (!user) return null; // Redirect is in flight

  return (
    <div className="min-h-screen flex flex-col">
      <Navbar />

      <main className="flex-1 max-w-7xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-10">
        {/* Header */}
        <div className="mb-8 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Dashboard</h1>
            <p className="mt-1 text-sm text-slate-500">
              Welcome back, {user.full_name}
            </p>
          </div>
          <HealthStatus />
        </div>

        {/* User info card */}
        <div className="mb-8 bg-indigo-50 border border-indigo-100 rounded-lg p-5 flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="flex items-center justify-center w-12 h-12 rounded-full bg-indigo-700 text-white text-lg font-bold shrink-0">
            {user.full_name.charAt(0).toUpperCase()}
          </div>
          <div className="flex-1">
            <p className="text-base font-semibold text-slate-900">{user.full_name}</p>
            <p className="text-sm text-slate-600">{user.email}</p>
          </div>
          <div className="text-right">
            <span className="inline-block px-3 py-1 rounded-full text-xs font-semibold bg-indigo-100 text-indigo-800">
              {ROLE_LABELS[user.role] ?? user.role}
            </span>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 mb-10">
          {stats.map((stat) => (
            <div
              key={stat.label}
              className="bg-white rounded-lg border border-slate-200 shadow-sm p-6"
            >
              <p className="text-sm font-medium text-slate-500">{stat.label}</p>
              <p className="mt-2 text-3xl font-bold text-slate-900">{stat.value}</p>
              <p className="mt-1 text-xs text-slate-400">{stat.note}</p>
            </div>
          ))}
        </div>

        {/* Two-column layout */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* About */}
          <div className="lg:col-span-2 bg-white rounded-lg border border-slate-200 shadow-sm p-6">
            <h2 className="text-base font-semibold text-slate-900 mb-3">About CaseVault</h2>
            <p className="text-sm text-slate-600 leading-relaxed mb-4">
              CaseVault is an enterprise legal case management platform for law firms and legal
              teams. It combines structured case organization with AI-powered document retrieval,
              enabling attorneys to surface relevant precedents and case facts instantly.
            </p>
            <div className="grid grid-cols-2 gap-3">
              {[
                ["Backend", "FastAPI + Python"],
                ["Frontend", "Next.js + TypeScript"],
                ["Database", "PostgreSQL + pgvector"],
                ["Infrastructure", "Docker Compose"],
              ].map(([k, v]) => (
                <div key={k} className="text-xs">
                  <span className="font-medium text-slate-700">{k}:</span>{" "}
                  <span className="text-slate-500">{v}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Roadmap */}
          <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-6">
            <h2 className="text-base font-semibold text-slate-900 mb-3">Feature Roadmap</h2>
            <ul className="space-y-3">
              {upcomingFeatures.map((f) => (
                <li key={f.title} className="flex items-start gap-3">
                  <span className="text-base leading-tight">{f.icon}</span>
                  <div>
                    <p className="text-sm font-medium text-slate-700">{f.title}</p>
                    <p className="text-xs text-slate-400">{f.day}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Day 2 status */}
        <div className="mt-6 bg-indigo-50 border border-indigo-200 rounded-lg p-4">
          <p className="text-sm font-semibold text-indigo-800">Day 2 — Authentication Complete</p>
          <p className="text-xs text-indigo-600 mt-1">
            JWT authentication, role-based authorization, and protected routes are active.
            Case management and AI features will be added in upcoming days.
          </p>
        </div>
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <p className="text-xs text-slate-400 text-center">
            CaseVault &mdash; Legal Intelligence Platform &mdash; Day 2 Foundation
          </p>
        </div>
      </footer>
    </div>
  );
}
