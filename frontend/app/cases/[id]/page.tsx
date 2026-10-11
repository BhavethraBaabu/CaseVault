"use client";

/**
 * Case detail page.
 *
 * Shows:
 *   - Case information (number, title, status, description)
 *   - Client information
 *   - Current user's membership role in this case
 *   - Case members list
 *   - Document upload and management (Day 4)
 *
 * Authorization note:
 *   Upload/delete controls are hidden from VIEWERs (UX only).
 *   Backend enforces all authorization independently.
 */

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import Navbar from "@/components/Navbar";
import { useAuth } from "@/context/AuthContext";
import {
  ApiError,
  CaseMembershipResponse,
  CaseResponse,
  ClientResponse,
  DocumentResponse,
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

const DOC_STATUS_COLORS: Record<string, string> = {
  READY: "bg-green-100 text-green-800",
  PROCESSING: "bg-yellow-100 text-yellow-800",
  UPLOADED: "bg-blue-100 text-blue-800",
  FAILED: "bg-red-100 text-red-800",
};

const MAX_UPLOAD_MB = 10;
const ALLOWED_FORMATS = ".pdf, .docx, .txt";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function DocumentsSection({
  caseId,
  canUpload,
  canDelete,
}: {
  caseId: string;
  canUpload: boolean;
  canDelete: boolean;
}) {
  const [documents, setDocuments] = useState<DocumentResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.documents
      .list(caseId)
      .then((docs) => {
        setDocuments(docs);
        setError(null);
        setLoading(false);
      })
      .catch(() => {
        setError("Failed to load documents.");
        setLoading(false);
      });
  }, [caseId]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setUploadError(`File exceeds ${MAX_UPLOAD_MB} MB limit.`);
      return;
    }

    setUploading(true);
    setUploadError(null);

    try {
      const doc = await api.documents.upload(caseId, file);
      setDocuments((prev) => [doc, ...prev]);
      if (doc.status === "FAILED") {
        setUploadError(
          doc.error_message ??
            "Document was uploaded but processing failed.",
        );
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setUploadError(err.message);
      } else {
        setUploadError("Upload failed. Please try again.");
      }
    } finally {
      setUploading(false);
      // Reset input so the same file can be re-uploaded if needed
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDownload = async (doc: DocumentResponse) => {
    try {
      const blob = await api.documents.download(doc.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = doc.original_filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert("Download failed.");
    }
  };

  const handleDelete = async (doc: DocumentResponse) => {
    if (!confirm(`Delete "${doc.original_filename}"? This cannot be undone.`)) return;
    setDeletingId(doc.id);
    try {
      await api.documents.delete(doc.id);
      setDocuments((prev) => prev.filter((d) => d.id !== doc.id));
    } catch {
      alert("Delete failed.");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-slate-900">
          Documents ({documents.length})
        </h2>
        {canUpload && (
          <label className="cursor-pointer">
            <span
              className={`text-xs font-medium px-3 py-1.5 rounded bg-indigo-600 text-white hover:bg-indigo-700 transition-colors ${
                uploading ? "opacity-60 pointer-events-none" : ""
              }`}
            >
              {uploading ? "Uploading…" : "Upload"}
            </span>
            <input
              ref={fileInputRef}
              type="file"
              accept={ALLOWED_FORMATS}
              className="sr-only"
              onChange={handleUpload}
              disabled={uploading}
            />
          </label>
        )}
      </div>

      {canUpload && (
        <p className="text-xs text-slate-400 mb-3">
          Supported: PDF, DOCX, TXT — max {MAX_UPLOAD_MB} MB
        </p>
      )}

      {uploadError && (
        <div className="mb-3 p-2.5 rounded bg-red-50 border border-red-200 text-xs text-red-700">
          {uploadError}
        </div>
      )}

      {loading ? (
        <p className="text-xs text-slate-400">Loading documents…</p>
      ) : error ? (
        <p className="text-xs text-red-600">{error}</p>
      ) : documents.length === 0 ? (
        <p className="text-xs text-slate-400">No documents uploaded yet.</p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {documents.map((doc) => (
            <li key={doc.id} className="py-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-slate-900 truncate max-w-xs">
                      {doc.original_filename}
                    </span>
                    <span
                      className={`shrink-0 text-xs font-medium px-1.5 py-0.5 rounded ${
                        DOC_STATUS_COLORS[doc.status] ?? ""
                      }`}
                    >
                      {doc.status}
                    </span>
                  </div>
                  <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-slate-400">
                    <span>{formatBytes(doc.file_size)}</span>
                    {doc.page_count != null && (
                      <span>{doc.page_count} page{doc.page_count !== 1 ? "s" : ""}</span>
                    )}
                    <span>
                      {new Date(doc.created_at).toLocaleDateString("en-US", {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })}
                    </span>
                  </div>
                  {doc.status === "FAILED" && doc.error_message && (
                    <p className="mt-1 text-xs text-red-600">{doc.error_message}</p>
                  )}
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  {doc.status === "READY" && (
                    <button
                      onClick={() => handleDownload(doc)}
                      className="text-xs text-indigo-700 hover:underline"
                    >
                      Download
                    </button>
                  )}
                  {canDelete && (
                    <button
                      onClick={() => handleDelete(doc)}
                      disabled={deletingId === doc.id}
                      className="text-xs text-red-600 hover:underline disabled:opacity-50"
                    >
                      {deletingId === doc.id ? "Deleting…" : "Delete"}
                    </button>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

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
  const canUpload =
    user?.role === "ADMIN" ||
    myMembership?.role === "OWNER" ||
    myMembership?.role === "MEMBER";
  const canDelete = isOwnerOrAdmin;

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

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
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

        {/* Documents */}
        <DocumentsSection
          caseId={caseId}
          canUpload={canUpload}
          canDelete={canDelete}
        />
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
