"use client";

/**
 * AI Agent page — Day 7.
 *
 * Authenticated users submit a task and the agent autonomously calls
 * authorized backend tools (document search, case lookup) before producing
 * a grounded answer with source citations.
 *
 * Authorization note:
 *   - The case selector shows only cases the user can access (API-scoped).
 *   - The backend enforces authorization independently; the frontend
 *     case list is UX only, not a security boundary.
 *   - Every tool call re-validates access server-side.
 *   - The user identity comes exclusively from the stored JWT.
 *
 * DISCLAIMER: AI-generated answers may be incorrect. Always verify
 * claims against the cited source documents.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import Navbar from "@/components/Navbar";
import { useAuth } from "@/context/AuthContext";
import {
  AgentCitation,
  AgentRunResponse,
  AgentToolTrace,
  ApiError,
  CaseResponse,
  api,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Tool label helpers
// ---------------------------------------------------------------------------

const TOOL_LABELS: Record<string, string> = {
  search_documents: "Searched authorized documents",
  list_cases: "Listed accessible cases",
  get_case_details: "Retrieved case details",
  get_document_context: "Retrieved document context",
};

function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ExecutionTrace({ tools }: { tools: AgentToolTrace[] }) {
  if (tools.length === 0) return null;
  return (
    <div className="mt-4">
      <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
        Execution trace
      </p>
      <ul className="space-y-1">
        {tools.map((t, i) => (
          <li key={i} className="flex items-center gap-2 text-sm text-slate-600">
            <span
              className={`w-2 h-2 rounded-full flex-shrink-0 ${
                t.success ? "bg-emerald-400" : "bg-red-400"
              }`}
            />
            {toolLabel(t.tool_name)}
            {!t.success && (
              <span className="text-xs text-red-500">(failed)</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function CitationCard({ citation }: { citation: AgentCitation }) {
  return (
    <div className="border border-slate-200 rounded-lg p-3 text-sm bg-slate-50">
      <div className="flex items-start justify-between gap-2 mb-1">
        <span className="font-medium text-slate-700 truncate">
          {citation.document_name}
        </span>
        <span className="text-xs text-slate-400 flex-shrink-0">
          {(citation.similarity * 100).toFixed(0)}% match
        </span>
      </div>
      {citation.page_number != null && (
        <p className="text-xs text-slate-400 mb-1">Page {citation.page_number}</p>
      )}
      <p className="text-slate-600 text-xs line-clamp-3">{citation.excerpt}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function AgentPage() {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  const [task, setTask] = useState("");
  const [selectedCaseId, setSelectedCaseId] = useState<string>("");
  const [cases, setCases] = useState<CaseResponse[]>([]);
  const [result, setResult] = useState<AgentRunResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Redirect if not authenticated
  useEffect(() => {
    if (!isLoading && !user) {
      router.push("/login");
    }
  }, [user, isLoading, router]);

  // Load accessible cases
  useEffect(() => {
    if (!user) return;
    api.cases.list().then(setCases).catch(() => setCases([]));
  }, [user]);

  const handleRun = async () => {
    const trimmed = task.trim();
    if (!trimmed || running) return;

    setRunning(true);
    setError(null);
    setResult(null);

    try {
      const resp = await api.agent.run({
        task: trimmed,
        case_id: selectedCaseId || null,
      });
      setResult(resp);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("An unexpected error occurred. Please try again.");
      }
    } finally {
      setRunning(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleRun();
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600" />
      </div>
    );
  }

  if (!user) return null;

  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar />

      <main className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-slate-900">AI Agent</h1>
          <p className="mt-1 text-sm text-slate-500">
            Ask complex questions. The agent searches your authorized documents
            and case data to produce a grounded answer.
          </p>
          <p className="mt-1 text-xs text-amber-600">
            Answers are AI-generated and may be incorrect. Always verify against
            cited sources.
          </p>
        </div>

        {/* Input panel */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-4 mb-6">
          {/* Case selector */}
          <div className="mb-3">
            <label
              htmlFor="case-select"
              className="block text-xs font-medium text-slate-500 mb-1"
            >
              Scope to case (optional)
            </label>
            <select
              id="case-select"
              value={selectedCaseId}
              onChange={(e) => setSelectedCaseId(e.target.value)}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
              disabled={running}
            >
              <option value="">All accessible cases</option>
              {cases.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.case_number} — {c.title}
                </option>
              ))}
            </select>
          </div>

          {/* Task input */}
          <label
            htmlFor="task-input"
            className="block text-xs font-medium text-slate-500 mb-1"
          >
            Task or question
          </label>
          <textarea
            id="task-input"
            ref={textareaRef}
            value={task}
            onChange={(e) => setTask(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="e.g. What are the key obligations in the vendor contract? List my open cases."
            rows={4}
            maxLength={2000}
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 placeholder-slate-400 resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500"
            disabled={running}
          />
          <div className="flex items-center justify-between mt-2">
            <span className="text-xs text-slate-400">
              {task.length}/2000 · Ctrl+Enter to run
            </span>
            <button
              onClick={handleRun}
              disabled={!task.trim() || running}
              className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            >
              {running ? (
                <>
                  <span className="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
                  Running…
                </>
              ) : (
                "Run agent"
              )}
            </button>
          </div>
        </div>

        {/* Error state */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-6">
            <p className="text-sm font-medium text-red-700">Error</p>
            <p className="text-sm text-red-600 mt-1">{error}</p>
          </div>
        )}

        {/* Result */}
        {result && (
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
            {/* Status badge */}
            <div className="flex items-center gap-2 mb-3">
              <span
                className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                  result.status === "success"
                    ? "bg-emerald-100 text-emerald-700"
                    : "bg-red-100 text-red-700"
                }`}
              >
                {result.status === "success" ? "Success" : "Error"}
              </span>
              {result.insufficient_evidence && (
                <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-700">
                  Insufficient evidence
                </span>
              )}
            </div>

            {/* Answer */}
            <div className="prose prose-sm max-w-none text-slate-800 whitespace-pre-wrap">
              {result.answer}
            </div>

            {/* API error detail */}
            {result.error && (
              <p className="mt-3 text-sm text-red-600">{result.error}</p>
            )}

            {/* Execution trace */}
            <ExecutionTrace tools={result.tools_executed} />

            {/* Citations */}
            {result.citations.length > 0 && (
              <div className="mt-5">
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                  Sources ({result.citations.length})
                </p>
                <div className="space-y-2">
                  {result.citations.map((c, i) => (
                    <CitationCard key={i} citation={c} />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Empty state */}
        {!result && !error && !running && (
          <div className="text-center py-12 text-slate-400">
            <svg
              className="w-12 h-12 mx-auto mb-3 text-slate-300"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1 1 .03 2.712-1.17 2.712H3.968c-1.2 0-2.17-1.712-1.17-2.712L4.2 15.3"
              />
            </svg>
            <p className="text-sm">Enter a task above and click Run agent</p>
          </div>
        )}
      </main>
    </div>
  );
}
