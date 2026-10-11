"use client";

/**
 * Semantic Search page.
 *
 * Allows authenticated users to search document chunks across their
 * authorized cases using semantic (vector) similarity.
 *
 * Authorization note:
 *   - The case filter shows only cases the user can access (API-scoped).
 *   - The backend enforces authorization independently; the frontend
 *     case list is UX only, not a security boundary.
 *   - Unauthorized cases never appear in results regardless of filtering.
 *
 * Day 5: retrieval only. Results are chunks + metadata; no AI answer
 * generation. That is Day 6.
 */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import Navbar from "@/components/Navbar";
import { useAuth } from "@/context/AuthContext";
import { ApiError, CaseResponse, SearchResultItem, api } from "@/lib/api";

export default function SearchPage() {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  const [query, setQuery] = useState("");
  const [selectedCaseId, setSelectedCaseId] = useState<string>("");
  const [limit, setLimit] = useState(10);

  const [cases, setCases] = useState<CaseResponse[]>([]);
  const [casesLoading, setCasesLoading] = useState(true);

  const [results, setResults] = useState<SearchResultItem[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchedQuery, setSearchedQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);

  // Redirect if not authenticated
  useEffect(() => {
    if (!isLoading && !user) router.push("/login");
  }, [isLoading, user, router]);

  // Load accessible cases for the filter dropdown
  useEffect(() => {
    if (!user) return;
    api.cases
      .list()
      .then(setCases)
      .catch(() => {
        /* silently ignore — case filter just won't populate */
      })
      .finally(() => setCasesLoading(false));
  }, [user]);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;

    setSearching(true);
    setError(null);
    setResults(null);

    try {
      const response = await api.search.query({
        query: trimmed,
        case_id: selectedCaseId || null,
        limit,
      });
      setResults(response.results);
      setSearchedQuery(response.query);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 503) {
          setError(
            "Embedding service is unavailable. Embeddings may not have been generated yet. " +
              "An administrator can run POST /search/embed to generate them.",
          );
        } else if (err.status === 422) {
          setError(err.message);
        } else {
          setError("Search failed. Please try again.");
        }
      } else {
        setError("Search failed. Please try again.");
      }
    } finally {
      setSearching(false);
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

  const noEmbeddings =
    results !== null && results.length === 0 && searchedQuery !== "";

  return (
    <div className="min-h-screen flex flex-col bg-slate-50">
      <Navbar />

      <main className="flex-1 max-w-4xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-10">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-slate-900">Semantic Search</h1>
          <p className="mt-1 text-sm text-slate-500">
            Search document contents using natural language. Results are ranked by
            similarity to your query.
          </p>
        </div>

        {/* Search form */}
        <form
          onSubmit={handleSearch}
          className="bg-white border border-slate-200 rounded-lg p-5 space-y-4 mb-6"
        >
          {/* Query input */}
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">
              Search query
            </label>
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. What does the contract say about termination?"
              maxLength={2000}
              className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              disabled={searching}
            />
          </div>

          {/* Filters row */}
          <div className="flex flex-col sm:flex-row gap-3">
            {/* Case filter */}
            <div className="flex-1">
              <label className="block text-xs font-medium text-slate-700 mb-1">
                Limit to case{" "}
                <span className="text-slate-400 font-normal">(optional)</span>
              </label>
              <select
                value={selectedCaseId}
                onChange={(e) => setSelectedCaseId(e.target.value)}
                className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                disabled={searching || casesLoading}
              >
                <option value="">All accessible cases</option>
                {cases.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.case_number} — {c.title}
                  </option>
                ))}
              </select>
            </div>

            {/* Result limit */}
            <div className="w-32">
              <label className="block text-xs font-medium text-slate-700 mb-1">
                Max results
              </label>
              <select
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
                className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                disabled={searching}
              >
                {[5, 10, 20, 50].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </div>

            {/* Submit */}
            <div className="flex items-end">
              <button
                type="submit"
                disabled={searching || !query.trim()}
                className="w-full sm:w-auto px-6 py-2 bg-indigo-700 text-white text-sm font-medium rounded-lg hover:bg-indigo-800 disabled:opacity-50 transition-colors"
              >
                {searching ? "Searching…" : "Search"}
              </button>
            </div>
          </div>
        </form>

        {/* Error state */}
        {error && (
          <div className="mb-4 bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Loading state */}
        {searching && (
          <div className="text-center py-10 text-sm text-slate-500">
            Searching…
          </div>
        )}

        {/* No results */}
        {noEmbeddings && !searching && (
          <div className="bg-white border border-slate-200 rounded-lg p-8 text-center">
            <p className="text-slate-700 font-medium mb-1">No results found</p>
            <p className="text-sm text-slate-500">
              No document chunks matched your query, or no embeddings have been
              generated yet.
            </p>
            <p className="text-xs text-slate-400 mt-2">
              An administrator can generate embeddings via{" "}
              <code className="bg-slate-100 px-1 py-0.5 rounded">
                POST /search/embed
              </code>
              .
            </p>
          </div>
        )}

        {/* Results */}
        {results && results.length > 0 && !searching && (
          <div>
            <p className="text-xs text-slate-500 mb-3">
              {results.length} result{results.length !== 1 ? "s" : ""} for{" "}
              <span className="font-medium text-slate-700">
                &ldquo;{searchedQuery}&rdquo;
              </span>
            </p>
            <div className="space-y-3">
              {results.map((result, idx) => (
                <ResultCard key={result.chunk_id} result={result} rank={idx + 1} />
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Result card component
// ---------------------------------------------------------------------------

function ResultCard({
  result,
  rank,
}: {
  result: SearchResultItem;
  rank: number;
}) {
  const similarityPct = Math.round(result.similarity * 100);

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4 hover:border-indigo-300 transition-colors">
      {/* Header row */}
      <div className="flex items-start justify-between gap-4 mb-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-mono text-slate-400">#{rank}</span>
            <span className="text-sm font-semibold text-slate-900 truncate">
              {result.document_name}
            </span>
            {result.page_number != null && (
              <span className="shrink-0 text-xs text-slate-500">
                p. {result.page_number}
              </span>
            )}
          </div>
          <div className="mt-0.5 flex items-center gap-2 flex-wrap">
            <Link
              href={`/cases/${result.case_id}`}
              className="text-xs text-indigo-600 hover:text-indigo-800 transition-colors"
            >
              View case
            </Link>
            <span className="text-xs text-slate-400">·</span>
            <span className="text-xs text-slate-400 font-mono">
              chunk {result.chunk_index}
            </span>
          </div>
        </div>

        {/* Similarity badge */}
        <div className="shrink-0 flex flex-col items-end">
          <span
            className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
              similarityPct >= 80
                ? "bg-green-100 text-green-800"
                : similarityPct >= 60
                  ? "bg-blue-100 text-blue-800"
                  : "bg-slate-100 text-slate-600"
            }`}
          >
            {similarityPct}% match
          </span>
          <span className="text-xs text-slate-400 mt-0.5">similarity</span>
        </div>
      </div>

      {/* Content excerpt */}
      <p className="text-sm text-slate-700 leading-relaxed line-clamp-4">
        {result.content}
      </p>
    </div>
  );
}
