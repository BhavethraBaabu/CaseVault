"use client";

/**
 * Case detail page.
 *
 * Shows:
 *   - Case information (number, title, status, description)
 *   - Client information
 *   - Current user's membership role in this case
 *   - Case members list
 *
 * Authorization note:
 *   Edit/manage controls are hidden from VIEWERs and non-owners (UX only).
 *   Backend enforces all authorization independently.
 */

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import Navbar from "@/components/Navbar";
import { useAuth } from "@/context/AuthContext";
import {
  ApiError,
  CaseMembershipResponse,
  CaseResponse,
  ClientResponse,
  api,
} from "@/lib/api";

const STATUS_COLORS: Record<string, string> = {
  OPEN: "bg-green-100 text-green-800",
  CLOSED: "bg-slate-100 text-slate-600",
  ARCHIVED: "bg-yellow-100 text-yellow-800",
};

const ROLE_COLORS: Record<string, string> = {
  OWNER: "bg-indigo-100 text-indigo-800",
  MEMBER: "bg-blue-100 text-blue-800",
  VIEWER: "bg-slate-100 text-slate-600",
};

function CaseDetailContent() {
  const { user, isLoading: authLoading } = useAuth();
  const router = useRouter();
  const params = useParams();
  const caseId = params?.id as string;

  const [caseData, setCaseData] = useState<CaseResponse | null>(null);
  const [client, setClient] = useState<ClientResponse | null>(null);
  const [members, setMembers] = useState<CaseMembershipResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.push("/login");
  }, [authLoading, user, router]);

  useEffect(() => {
    if (!user || !caseId) return;
    Promise.all([api.cases.get(caseId), api.caseMembers.list(caseId)])
      .then(async ([c, m]) => {
        setCaseData(c);
        setMembers(m);
        try {
          const cl = await api.clients.get(c.client_id);
          setClient(cl);
        } catch {
          // Client might be inaccessible; that's fine
        }
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) {
          setError("Case not found or you do not have access.");
        } else {
          setError("Failed to load case.");
        }
      })
      .finally(() => setLoading(false));
  }, [user, caseId]);

  const myMembership = members.find((m) => m.user_id === user?.id);
  const isOwnerOrAdmin =
    user?.role === "ADMIN" || myMembership?.role === "OWNER";

  if (authLoading || loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="text-sm text-slate-500">Loading…</div>
      </div>
    );
  }

  if (!user) return null;

  if (error || !caseData) {
    return (
      <div className="min-h-screen flex flex-col bg-slate-50">
        <Navbar />
        <main className="flex-1 max-w-5xl mx-auto w-full px-4 py-10">
          <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
            <p className="text-sm text-red-700">{error ?? "Case not found."}</p>
            <Link
              href="/cases"
              className="mt-3 inline-block text-sm text-indigo-700 hover:underline"
            >
              Back to cases
            </Link>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col bg-slate-50">
      <Navbar />

      <main className="flex-1 max-w-5xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-10">
        {/* Breadcrumb */}
        <div className="mb-6">
          <Link
            href="/cases"
            className="text-sm text-indigo-700 hover:underline"
          >
            Cases
          </Link>
          <span className="text-sm text-slate-400 mx-2">/</span>
          <span className="text-sm text-slate-600">{caseData.case_number}</span>
        </div>

        {/* Case header */}
        <div className="bg-white border border-slate-200 rounded-lg p-6 mb-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <h1 className="text-xl font-bold text-slate-900">{caseData.title}</h1>
                <span
                  className={`text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_COLORS[caseData.status] ?? ""}`}
                >
                  {caseData.status}
                </span>
              </div>
              <p className="text-sm text-slate-500">{caseData.case_number}</p>
            </div>
            {myMembership && (
              <span
                className={`shrink-0 text-xs font-medium px-2.5 py-1 rounded-full ${ROLE_COLORS[myMembership.role] ?? ""}`}
              >
                {myMembership.role}
              </span>
            )}
          </div>

          {caseData.description && (
            <p className="mt-4 text-sm text-slate-600 leading-relaxed">
              {caseData.description}
            </p>
          )}

          <div className="mt-4 flex flex-wrap gap-4 text-xs text-slate-400">
            <span>
              Created{" "}
              {new Date(caseData.created_at).toLocaleDateString("en-US", {
                year: "numeric",
                month: "short",
                day: "numeric",
              })}
            </span>
            <span>
              Updated{" "}
              {new Date(caseData.updated_at).toLocaleDateString("en-US", {
                year: "numeric",
                month: "short",
                day: "numeric",
              })}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Client info */}
          <div className="lg:col-span-1">
            <div className="bg-white border border-slate-200 rounded-lg p-5">
              <h2 className="text-sm font-semibold text-slate-900 mb-3">Client</h2>
              {client ? (
                <div>
                  <p className="text-sm font-medium text-slate-900">{client.name}</p>
                  {client.organization && (
                    <p className="text-xs text-slate-500 mt-0.5">{client.organization}</p>
                  )}
                  {client.email && (
                    <p className="text-xs text-slate-500 mt-0.5">{client.email}</p>
                  )}
                  {client.phone && (
                    <p className="text-xs text-slate-500 mt-0.5">{client.phone}</p>
                  )}
                  <Link
                    href="/clients"
                    className="mt-3 inline-block text-xs text-indigo-700 hover:underline"
                  >
                    View all clients
                  </Link>
                </div>
              ) : (
                <p className="text-xs text-slate-400">Client details unavailable.</p>
              )}
            </div>
          </div>

          {/* Members */}
          <div className="lg:col-span-2">
            <div className="bg-white border border-slate-200 rounded-lg p-5">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-slate-900">
                  Members ({members.length})
                </h2>
                {isOwnerOrAdmin && (
                  <span className="text-xs text-slate-400">
                    Manage via API
                  </span>
                )}
              </div>

              {members.length === 0 ? (
                <p className="text-xs text-slate-400">No members.</p>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {members.map((m) => (
                    <li key={m.id} className="py-2.5 flex items-center justify-between">
                      <div>
                        <p className="text-sm text-slate-700 font-medium">
                          {m.user_id === user.id ? "You" : m.user_id.slice(0, 8) + "…"}
                        </p>
                        <p className="text-xs text-slate-400">
                          Added{" "}
                          {new Date(m.created_at).toLocaleDateString("en-US", {
                            month: "short",
                            day: "numeric",
                            year: "numeric",
                          })}
                        </p>
                      </div>
                      <span
                        className={`text-xs font-medium px-2 py-0.5 rounded-full ${ROLE_COLORS[m.role] ?? ""}`}
                      >
                        {m.role}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

export default function CaseDetailPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-slate-50">
          <div className="text-sm text-slate-500">Loading…</div>
        </div>
      }
    >
      <CaseDetailContent />
    </Suspense>
  );
}
