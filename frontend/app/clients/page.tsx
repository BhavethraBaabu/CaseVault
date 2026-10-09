"use client";

/**
 * Clients page — lists accessible clients and allows creating new ones.
 *
 * Authorization note:
 *   The "Create Client" button is hidden from RESTRICTED_LAWYER (UX only).
 *   The backend independently enforces this restriction on every request.
 *   Frontend role checks are NOT security — they are user experience.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import Navbar from "@/components/Navbar";
import { useAuth } from "@/context/AuthContext";
import { ApiError, ClientCreate, ClientResponse, api } from "@/lib/api";

export default function ClientsPage() {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  const [clients, setClients] = useState<ClientResponse[]>([]);
  const [loadingClients, setLoadingClients] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create form state
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<ClientCreate>({ name: "" });
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading && !user) {
      router.push("/login");
    }
  }, [isLoading, user, router]);

  useEffect(() => {
    if (!user) return;
    api.clients
      .list()
      .then(setClients)
      .catch(() => setError("Failed to load clients"))
      .finally(() => setLoadingClients(false));
  }, [user]);

  const canCreateClient = user?.role === "ADMIN" || user?.role === "LAWYER";

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      const created = await api.clients.create(form);
      setClients((prev) => [...prev, created]);
      setForm({ name: "" });
      setShowForm(false);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Failed to create client");
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
            <h1 className="text-2xl font-bold text-slate-900">Clients</h1>
            <p className="mt-1 text-sm text-slate-500">
              {user.role === "ADMIN"
                ? "All clients in the system."
                : "Clients accessible through your case memberships."}
            </p>
          </div>
          {canCreateClient && (
            <button
              onClick={() => setShowForm((v) => !v)}
              className="px-4 py-2 bg-indigo-700 text-white text-sm font-medium rounded-lg hover:bg-indigo-800 transition-colors"
            >
              {showForm ? "Cancel" : "New Client"}
            </button>
          )}
        </div>

        {/* Create form */}
        {showForm && (
          <form
            onSubmit={handleCreate}
            className="mb-6 bg-white border border-slate-200 rounded-lg p-5 space-y-4"
          >
            <h2 className="text-base font-semibold text-slate-900">New Client</h2>
            {formError && (
              <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded p-3">
                {formError}
              </p>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Name <span className="text-red-500">*</span>
                </label>
                <input
                  required
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  placeholder="Client name"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Email</label>
                <input
                  type="email"
                  value={form.email ?? ""}
                  onChange={(e) => setForm({ ...form, email: e.target.value || null })}
                  className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  placeholder="contact@example.com"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Phone</label>
                <input
                  value={form.phone ?? ""}
                  onChange={(e) => setForm({ ...form, phone: e.target.value || null })}
                  className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  placeholder="555-123-4567"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Organization
                </label>
                <input
                  value={form.organization ?? ""}
                  onChange={(e) => setForm({ ...form, organization: e.target.value || null })}
                  className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  placeholder="Acme Corporation"
                />
              </div>
            </div>
            <div className="flex gap-3">
              <button
                type="submit"
                disabled={submitting}
                className="px-4 py-2 bg-indigo-700 text-white text-sm font-medium rounded-lg hover:bg-indigo-800 disabled:opacity-50 transition-colors"
              >
                {submitting ? "Creating…" : "Create Client"}
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

        {/* Client list */}
        {loadingClients ? (
          <div className="text-sm text-slate-500 py-8 text-center">Loading clients…</div>
        ) : error ? (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded p-4">
            {error}
          </div>
        ) : clients.length === 0 ? (
          <div className="text-center py-16 bg-white border border-slate-200 rounded-lg">
            <p className="text-slate-500 text-sm">No clients found.</p>
            {canCreateClient && (
              <p className="text-slate-400 text-xs mt-1">
                Create a client above to get started.
              </p>
            )}
          </div>
        ) : (
          <div className="bg-white border border-slate-200 rounded-lg divide-y divide-slate-100">
            {clients.map((c) => (
              <div key={c.id} className="px-5 py-4 flex items-center gap-4">
                <div className="flex items-center justify-center w-9 h-9 rounded-full bg-indigo-100 text-indigo-700 text-sm font-bold shrink-0">
                  {c.name.charAt(0).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-slate-900 truncate">{c.name}</p>
                  <p className="text-xs text-slate-500 truncate">
                    {[c.organization, c.email].filter(Boolean).join(" · ") || "No contact info"}
                  </p>
                </div>
                {c.phone && (
                  <span className="text-xs text-slate-400 hidden sm:block">{c.phone}</span>
                )}
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
