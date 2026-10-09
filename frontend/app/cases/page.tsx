"use client";

/**
 * Cases page — lists accessible cases and allows creating new ones.
 *
 * Authorization note:
 *   The "Create Case" button is hidden from RESTRICTED_LAWYER (UX only).
 *   The backend independently enforces this restriction on every request.
 *   Frontend role checks are NOT security — they are user experience.
 *
 *   The case list is scoped server-side: the API only returns cases where
 *   the current user holds a CaseMembership (or all cases for ADMIN).
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import Navbar from "@/components/Navbar";
import { useAuth } from "@/context/AuthContext";
import { ApiError, CaseCreate, CaseResponse, ClientResponse, api } from "@/lib/api";

const STATUS_COLORS: Record<string, string> = {
  OPEN: "bg-green-100 text-green-800",
  CLOSED: "bg-slate-100 text-slate-600",
  ARCHIVED: "bg-yellow-100 text-yellow-800",
};

export default function CasesPage() {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  const [cases, setCases] = useState<CaseResponse[]>([]);
  const [loadingCases, setLoadingCases] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [clients, setClients] = useState<ClientResponse[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<CaseCreate>({
    client_id: "",
    case_number: "",
    title: "",
    status: "OPEN",
  });
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading && !user) router.push("/login");
  }, [isLoading, user, router]);

  useEffect(() => {
    if (!user) return;
    Promise.all([api.cases.list(), api.clients.list()])
      .then(([c, cl]) => {
        setCases(c);
        setClients(cl);
      })
      .catch(() => setError("Failed to load cases"))
      .finally(() => setLoadingCases(false));
  }, [user]);

  const canCreateCase = user?.role === "ADMIN" || user?.role === "LAWYER";

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      const created = await api.cases.create(form);
      setCases((prev) => [...prev, created]);
      setForm({ client_id: "", case_number: "", title: "", status: "OPEN" });
      setShowForm(false);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Failed to create case");
    } finally {
      setSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="text-sm text-slate-500">Loading…</div>
      </div>
    );
  }

  if (!user) return null;

  return (
    <div className="min-h-screen flex flex-col bg-slate-50">
      <Navbar />

      <main className="flex-1 max-w-5xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-10">
        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Cases</h1>
            <p className="mt-1 text-sm text-slate-500">
              {user.role === "ADMIN"
                ? "All cases in the system."
                : "Cases where you hold a membership."}
            </p>
          </div>
          {canCreateCase && (
            <button
              onClick={() => setShowForm((v) => !v)}
              className="px-4 py-2 bg-indigo-700 text-white text-sm font-medium rounded-lg hover:bg-indigo-800 transition-colors"
            >
              {showForm ? "Cancel" : "New Case"}
            </button>
          )}
        </div>

        {/* Create form */}
        {showForm && (
          <form
            onSubmit={handleCreate}
            className="mb-6 bg-white border border-slate-200 rounded-lg p-5 space-y-4"
          >
            <h2 className="text-base font-semibold text-slate-900">New Case</h2>
            {formError && (
              <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded p-3">
                {formError}
              </p>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Case Number <span className="text-red-500">*</span>
                </label>
                <input
                  required
                  value={form.case_number}
                  onChange={(e) => setForm({ ...form, case_number: e.target.value })}
                  className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  placeholder="CASE-2026-001"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Title <span className="text-red-500">*</span>
                </label>
                <input
                  required
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  placeholder="Acme v. Example"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Client <span className="text-red-500">*</span>
                </label>
                <select
                  required
                  value={form.client_id}
                  onChange={(e) => setForm({ ...form, client_id: e.target.value })}
                  className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="">Select a client…</option>
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Status</label>
                <select
                  value={form.status}
                  onChange={(e) =>
                    setForm({ ...form, status: e.target.value as CaseCreate["status"] })
                  }
                  className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="OPEN">Open</option>
                  <option value="CLOSED">Closed</option>
                  <option value="ARCHIVED">Archived</option>
                </select>
              </div>
              <div className="sm:col-span-2">
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Description
                </label>
                <textarea
                  value={form.description ?? ""}
                  onChange={(e) => setForm({ ...form, description: e.target.value || null })}
                  rows={2}
                  className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  placeholder="Brief description of the case…"
                />
              </div>
            </div>
            <div className="flex gap-3">
              <button
                type="submit"
                disabled={submitting}
                className="px-4 py-2 bg-indigo-700 text-white text-sm font-medium rounded-lg hover:bg-indigo-800 disabled:opacity-50 transition-colors"
              >
                {submitting ? "Creating…" : "Create Case"}
              </button>
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50 transition-colors"
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        {/* Case list */}
        {loadingCases ? (
          <div className="text-sm text-slate-500 py-8 text-center">Loading cases…</div>
        ) : error ? (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded p-4">
            {error}
          </div>
        ) : cases.length === 0 ? (
          <div className="text-center py-16 bg-white border border-slate-200 rounded-lg">
            <p className="text-slate-500 text-sm">No cases found.</p>
            {canCreateCase && (
              <p className="text-slate-400 text-xs mt-1">Create a case above to get started.</p>
            )}
          </div>
        ) : (
          <div className="bg-white border border-slate-200 rounded-lg divide-y divide-slate-100">
            {cases.map((c) => (
              <Link
                key={c.id}
                href={`/cases/${c.id}`}
                className="block px-5 py-4 hover:bg-slate-50 transition-colors"
              >
                <div className="flex items-center gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-semibold text-slate-900 truncate">{c.title}</p>
                      <span
                        className={`shrink-0 text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_COLORS[c.status] ?? ""}`}
                      >
                        {c.status}
                      </span>
                    </div>
                    <p className="text-xs text-slate-500 mt-0.5">
                      {c.case_number}
                      {c.description && ` · ${c.description.slice(0, 60)}${c.description.length > 60 ? "…" : ""}`}
                    </p>
                  </div>
                  <svg
                    className="w-4 h-4 text-slate-400 shrink-0"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M9 5l7 7-7 7"
                    />
                  </svg>
                </div>
              </Link>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
