"use client";

/**
 * AI Case Timeline + Contradiction Detector page.
 *
 * Layout
 * ------
 *   - Page header with case breadcrumb
 *   - "Run Analysis" button (OWNER/MEMBER only; hidden from VIEWER)
 *   - AI disclaimer banner
 *   - Tab bar: Events | Contradictions
 *   - Events tab: vertical chronological timeline
 *   - Contradictions tab: severity-ranked discrepancy cards with source evidence
 *
 * Authorization note
 * ------------------
 *   UI hides controls VIEWERs cannot use.
 *   Backend enforces all authorization independently.
 */

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import Navbar from "@/components/Navbar";
import { useAuth } from "@/context/AuthContext";
import {
  AnalyzeResponse,
  ApiError,
  CaseMembershipResponse,
  CaseResponse,
  ContradictionsResponse,
  ReviewStatus,
  TimelineContradictionResponse,
  TimelineResponse,
  api,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Constants / helpers
// ---------------------------------------------------------------------------

const SEVERITY_COLORS: Record<string, string> = {
  HIGH: "bg-red-100 text-red-800 border-red-200",
  MEDIUM: "bg-yellow-100 text-yellow-800 border-yellow-200",
  LOW: "bg-slate-100 text-slate-600 border-slate-200",
};

const REVIEW_COLORS: Record<string, string> = {
  UNREVIEWED: "bg-slate-100 text-slate-600",
  REVIEWED: "bg-green-100 text-green-800",
  DISPUTED: "bg-red-100 text-red-700",
};

const EVENT_TYPE_COLORS: Record<string, string> = {
  MEETING: "bg-blue-100 text-blue-800",
  FILING: "bg-indigo-100 text-indigo-800",
  PAYMENT: "bg-emerald-100 text-emerald-800",
  AGREEMENT: "bg-purple-100 text-purple-800",
  TERMINATION: "bg-red-100 text-red-800",
  CORRESPONDENCE: "bg-amber-100 text-amber-800",
  HEARING: "bg-pink-100 text-pink-800",
  DEADLINE: "bg-orange-100 text-orange-800",
  OTHER: "bg-slate-100 text-slate-600",
};

const CATEGORY_LABELS: Record<string, string> = {
  DATE_CONFLICT: "Date conflict",
  QUANTITY_CONFLICT: "Quantity conflict",
  FACT_CONFLICT: "Fact conflict",
  STATEMENT_CONFLICT: "Statement conflict",
  OTHER: "Discrepancy",
};

function formatEventDate(
  eventDate: string | null,
  datePrecision: string,
): string {
  if (!eventDate) return "Date unknown";
  try {
    if (datePrecision === "YEAR") {
      return eventDate.slice(0, 4);
    }
    if (datePrecision === "MONTH") {
      const d = new Date(eventDate + "T00:00:00Z");
      return d.toLocaleDateString("en-US", {
        year: "numeric",
        month: "long",
        timeZone: "UTC",
      });
    }
    const d = new Date(eventDate + "T00:00:00Z");
    return d.toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    });
  } catch {
    return eventDate;
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function AiDisclaimer() {
  return (
    <div className="mb-5 p-3 rounded-lg bg-amber-50 border border-amber-200 text-xs text-amber-800">
      <strong>AI-generated results.</strong> All extracted events and
      discrepancies are produced by a language model and require human review
      before being treated as accurate or legally significant.
    </div>
  );
}

function EventCard({
  event,
}: {
  event: TimelineResponse["events"][number];
}) {
  const [expanded, setExpanded] = useState(false);
  const dateLabel = formatEventDate(event.event_date, event.date_precision);

  return (
    <div className="relative pl-10">
      {/* Timeline dot */}
      <span className="absolute left-0 top-1.5 w-3.5 h-3.5 rounded-full border-2 border-indigo-500 bg-white" />

      <div
        className="bg-white border border-slate-200 rounded-lg p-4 cursor-pointer hover:border-slate-300 transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2 mb-1">
              <span className="text-xs font-mono text-slate-400 shrink-0">
                {dateLabel}
              </span>
              <span
                className={`text-xs font-medium px-1.5 py-0.5 rounded ${
                  EVENT_TYPE_COLORS[event.event_type] ??
                  EVENT_TYPE_COLORS["OTHER"]
                }`}
              >
                {event.event_type}
              </span>
              <span
                className={`text-xs font-medium px-1.5 py-0.5 rounded ${
                  REVIEW_COLORS[event.review_status] ?? ""
                }`}
              >
                {event.review_status}
              </span>
            </div>
            <p className="text-sm font-semibold text-slate-900">
              {event.title}
            </p>
            <p className="mt-0.5 text-xs text-slate-500 line-clamp-2">
              {event.description}
            </p>
          </div>
          <span className="text-slate-400 text-xs shrink-0 pt-0.5">
            {expanded ? "▲" : "▼"}
          </span>
        </div>

        {expanded && (
          <div className="mt-3 pt-3 border-t border-slate-100 space-y-2">
            {event.description && (
              <p className="text-xs text-slate-600 leading-relaxed">
                {event.description}
              </p>
            )}

            {event.source_quote && (
              <blockquote className="pl-3 border-l-2 border-indigo-300 text-xs italic text-slate-600">
                &ldquo;{event.source_quote}&rdquo;
              </blockquote>
            )}

            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
              {event.source_document_name && (
                <span>
                  Source:{" "}
                  <span className="text-slate-600">
                    {event.source_document_name}
                  </span>
                </span>
              )}
              {event.source_page != null && (
                <span>Page {event.source_page}</span>
              )}
              {event.extraction_confidence != null && (
                <span>
                  Confidence:{" "}
                  {Math.round(event.extraction_confidence * 100)}%
                </span>
              )}
            </div>

            {event.people.length > 0 && (
              <div className="text-xs text-slate-500">
                <span className="font-medium text-slate-700">People: </span>
                {event.people.join(", ")}
              </div>
            )}
            {event.organizations.length > 0 && (
              <div className="text-xs text-slate-500">
                <span className="font-medium text-slate-700">
                  Organizations:{" "}
                </span>
                {event.organizations.join(", ")}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ContradictionCard({
  item,
  canReview,
  onStatusChange,
}: {
  item: TimelineContradictionResponse;
  canReview: boolean;
  onStatusChange: (id: string, status: ReviewStatus) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [updating, setUpdating] = useState(false);

  const severityClass =
    SEVERITY_COLORS[item.severity] ?? SEVERITY_COLORS["LOW"];

  const handleReview = async (newStatus: ReviewStatus) => {
    setUpdating(true);
    try {
      onStatusChange(item.id, newStatus);
    } finally {
      setUpdating(false);
    }
  };

  return (
    <div
      className={`bg-white border rounded-lg overflow-hidden ${
        item.severity === "HIGH"
          ? "border-red-300"
          : item.severity === "MEDIUM"
            ? "border-yellow-300"
            : "border-slate-200"
      }`}
    >
      {/* Card header */}
      <div
        className="p-4 cursor-pointer"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2 mb-1">
              <span
                className={`text-xs font-semibold px-2 py-0.5 rounded border ${severityClass}`}
              >
                {item.severity}
              </span>
              <span className="text-xs text-slate-500">
                {CATEGORY_LABELS[item.category] ?? item.category}
              </span>
              <span
                className={`text-xs font-medium px-1.5 py-0.5 rounded ${
                  REVIEW_COLORS[item.review_status] ?? ""
                }`}
              >
                {item.review_status}
              </span>
            </div>
            <p className="text-sm font-semibold text-slate-900">
              {item.summary}
            </p>
          </div>
          <span className="text-slate-400 text-xs shrink-0 pt-1">
            {expanded ? "▲" : "▼"}
          </span>
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-slate-100 p-4 space-y-4">
          {/* Statement A */}
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
              Statement A
              {item.evidence_a.document_name && (
                <span className="ml-2 normal-case font-normal text-slate-400">
                  — {item.evidence_a.document_name}
                </span>
              )}
            </p>
            <p className="text-sm text-slate-700">{item.statement_a}</p>
            {item.evidence_a.quote && (
              <blockquote className="mt-1.5 pl-3 border-l-2 border-slate-300 text-xs italic text-slate-500">
                &ldquo;{item.evidence_a.quote}&rdquo;
              </blockquote>
            )}
          </div>

          {/* Statement B */}
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
              Statement B
              {item.evidence_b.document_name && (
                <span className="ml-2 normal-case font-normal text-slate-400">
                  — {item.evidence_b.document_name}
                </span>
              )}
            </p>
            <p className="text-sm text-slate-700">{item.statement_b}</p>
            {item.evidence_b.quote && (
              <blockquote className="mt-1.5 pl-3 border-l-2 border-slate-300 text-xs italic text-slate-500">
                &ldquo;{item.evidence_b.quote}&rdquo;
              </blockquote>
            )}
          </div>

          {/* Confidence + review actions */}
          <div className="flex items-center justify-between gap-4 pt-1">
            <span className="text-xs text-slate-400">
              AI confidence: {Math.round(item.confidence * 100)}%
            </span>
            {canReview && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500">Mark as:</span>
                {(["REVIEWED", "DISPUTED", "UNREVIEWED"] as ReviewStatus[]).map(
                  (s) => (
                    <button
                      key={s}
                      disabled={updating || item.review_status === s}
                      onClick={() => handleReview(s)}
                      className={`text-xs px-2 py-0.5 rounded border transition-colors disabled:opacity-40 ${
                        item.review_status === s
                          ? "bg-slate-100 text-slate-500 border-slate-200 cursor-default"
                          : "bg-white text-slate-700 border-slate-300 hover:bg-slate-50"
                      }`}
                    >
                      {s}
                    </button>
                  ),
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page content
// ---------------------------------------------------------------------------

function TimelineContent() {
  const { user, isLoading: authLoading } = useAuth();
  const router = useRouter();
  const params = useParams();
  const caseId = params?.id as string;

  const [caseData, setCaseData] = useState<CaseResponse | null>(null);
  const [members, setMembers] = useState<CaseMembershipResponse[]>([]);
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [contradictions, setContradictions] =
    useState<ContradictionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"events" | "contradictions">(
    "events",
  );
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeResult, setAnalyzeResult] = useState<AnalyzeResponse | null>(
    null,
  );
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.push("/login");
  }, [authLoading, user, router]);

  useEffect(() => {
    if (!user || !caseId) return;
    Promise.all([
      api.cases.get(caseId),
      api.caseMembers.list(caseId),
      api.timeline.getEvents(caseId),
      api.timeline.getContradictions(caseId),
    ])
      .then(([c, m, tl, ct]) => {
        setCaseData(c);
        setMembers(m);
        setTimeline(tl);
        setContradictions(ct);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) {
          setError("Case not found or you do not have access.");
        } else {
          setError("Failed to load timeline data.");
        }
      })
      .finally(() => setLoading(false));
  }, [user, caseId]);

  const myMembership = members.find((m) => m.user_id === user?.id);
  const canAnalyze =
    user?.role === "ADMIN" ||
    myMembership?.role === "OWNER" ||
    myMembership?.role === "MEMBER";

  const handleAnalyze = useCallback(
    async (forceReanalyze = false) => {
      setAnalyzing(true);
      setAnalyzeError(null);
      setAnalyzeResult(null);
      try {
        const result = await api.timeline.analyze(caseId, {
          force_reanalyze: forceReanalyze,
          max_documents: 5,
        });
        setAnalyzeResult(result);
        // Refresh timeline and contradictions
        const [tl, ct] = await Promise.all([
          api.timeline.getEvents(caseId),
          api.timeline.getContradictions(caseId),
        ]);
        setTimeline(tl);
        setContradictions(ct);
      } catch (err) {
        if (err instanceof ApiError) {
          setAnalyzeError(err.message);
        } else {
          setAnalyzeError("Analysis failed. Please try again.");
        }
      } finally {
        setAnalyzing(false);
      }
    },
    [caseId],
  );

  const handleContradictionStatusChange = useCallback(
    async (id: string, status: ReviewStatus) => {
      try {
        const updated = await api.timeline.updateContradictionReview(
          caseId,
          id,
          status,
        );
        setContradictions((prev) =>
          prev
            ? {
                ...prev,
                contradictions: prev.contradictions.map((c) =>
                  c.id === updated.id ? updated : c,
                ),
              }
            : prev,
        );
      } catch {
        // Silently ignore — the optimistic update didn't happen so UI is consistent
      }
    },
    [caseId],
  );

  // ---------------------------------------------------------------------------
  // Loading / error states
  // ---------------------------------------------------------------------------

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

  const eventCount = timeline?.total ?? 0;
  const contradictionCount = contradictions?.total ?? 0;

  // Sort contradictions: HIGH first, then MEDIUM, then LOW
  const severityOrder: Record<string, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 };
  const sortedContradictions = contradictions
    ? [...contradictions.contradictions].sort(
        (a, b) =>
          (severityOrder[a.severity] ?? 3) - (severityOrder[b.severity] ?? 3),
      )
    : [];

  return (
    <div className="min-h-screen flex flex-col bg-slate-50">
      <Navbar />

      <main className="flex-1 max-w-4xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-10">
        {/* Breadcrumb */}
        <div className="mb-6 flex items-center gap-1.5 text-sm">
          <Link href="/cases" className="text-indigo-700 hover:underline">
            Cases
          </Link>
          <span className="text-slate-400">/</span>
          <Link
            href={`/cases/${caseId}`}
            className="text-indigo-700 hover:underline"
          >
            {caseData.case_number}
          </Link>
          <span className="text-slate-400">/</span>
          <span className="text-slate-600">Timeline</span>
        </div>

        {/* Page header */}
        <div className="flex items-start justify-between gap-4 mb-6">
          <div>
            <h1 className="text-xl font-bold text-slate-900">
              AI Case Timeline
            </h1>
            <p className="mt-0.5 text-sm text-slate-500">{caseData.title}</p>
          </div>

          {canAnalyze && (
            <div className="flex items-center gap-2 shrink-0">
              {timeline?.has_been_analyzed && (
                <button
                  onClick={() => handleAnalyze(true)}
                  disabled={analyzing}
                  className="text-xs px-3 py-1.5 rounded border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition-colors"
                >
                  {analyzing ? "Analyzing…" : "Re-analyze"}
                </button>
              )}
              <button
                onClick={() => handleAnalyze(false)}
                disabled={analyzing}
                className="text-xs font-medium px-3 py-1.5 rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              >
                {analyzing
                  ? "Analyzing…"
                  : timeline?.has_been_analyzed
                    ? "Analyze New Docs"
                    : "Run Analysis"}
              </button>
            </div>
          )}
        </div>

        {/* Analysis result banner */}
        {analyzeResult && (
          <div className="mb-5 p-3 rounded-lg bg-green-50 border border-green-200 text-xs text-green-800">
            {analyzeResult.message}
          </div>
        )}
        {analyzeError && (
          <div className="mb-5 p-3 rounded-lg bg-red-50 border border-red-200 text-xs text-red-700">
            {analyzeError}
          </div>
        )}

        <AiDisclaimer />

        {/* Tab bar */}
        <div className="flex border-b border-slate-200 mb-6">
          <button
            onClick={() => setActiveTab("events")}
            className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
              activeTab === "events"
                ? "border-indigo-600 text-indigo-700"
                : "border-transparent text-slate-500 hover:text-slate-700"
            }`}
          >
            Events
            {eventCount > 0 && (
              <span className="ml-1.5 text-xs bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded-full">
                {eventCount}
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveTab("contradictions")}
            className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
              activeTab === "contradictions"
                ? "border-indigo-600 text-indigo-700"
                : "border-transparent text-slate-500 hover:text-slate-700"
            }`}
          >
            Contradictions
            {contradictionCount > 0 && (
              <span
                className={`ml-1.5 text-xs px-1.5 py-0.5 rounded-full ${
                  sortedContradictions.some((c) => c.severity === "HIGH")
                    ? "bg-red-100 text-red-700"
                    : "bg-slate-100 text-slate-600"
                }`}
              >
                {contradictionCount}
              </span>
            )}
          </button>
        </div>

        {/* Events tab */}
        {activeTab === "events" && (
          <div>
            {!timeline?.has_been_analyzed ? (
              <div className="text-center py-16 text-slate-400">
                <p className="text-sm">No analysis has been run yet.</p>
                {canAnalyze && (
                  <p className="mt-1 text-xs">
                    Click &ldquo;Run Analysis&rdquo; to extract a timeline from
                    your documents.
                  </p>
                )}
              </div>
            ) : eventCount === 0 ? (
              <div className="text-center py-16 text-slate-400">
                <p className="text-sm">
                  No events were extracted from the documents.
                </p>
                <p className="mt-1 text-xs">
                  Ensure documents are in READY status before re-analyzing.
                </p>
              </div>
            ) : (
              <div className="relative">
                {/* Vertical line */}
                <div className="absolute left-[6px] top-3 bottom-3 w-px bg-indigo-200" />
                <div className="space-y-4">
                  {timeline.events.map((event) => (
                    <EventCard key={event.id} event={event} />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Contradictions tab */}
        {activeTab === "contradictions" && (
          <div>
            {!timeline?.has_been_analyzed ? (
              <div className="text-center py-16 text-slate-400">
                <p className="text-sm">No analysis has been run yet.</p>
              </div>
            ) : contradictionCount === 0 ? (
              <div className="text-center py-16 text-slate-400">
                <p className="text-sm">
                  No potential discrepancies were identified.
                </p>
                <p className="mt-1 text-xs text-slate-400">
                  This may mean the documents are consistent, or there were too
                  few events to compare.
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {sortedContradictions.map((item) => (
                  <ContradictionCard
                    key={item.id}
                    item={item}
                    canReview={canAnalyze}
                    onStatusChange={handleContradictionStatusChange}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

export default function TimelinePage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-slate-50">
          <div className="text-sm text-slate-500">Loading…</div>
        </div>
      }
    >
      <TimelineContent />
    </Suspense>
  );
}
