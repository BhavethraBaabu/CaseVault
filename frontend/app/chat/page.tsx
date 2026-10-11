"use client";

/**
 * Chat (RAG) page — Day 6.
 *
 * Authenticated users can ask natural-language questions about their
 * authorized documents and receive AI-generated answers with validated
 * source citations.
 *
 * Authorization note:
 *   - The case filter shows only cases the user can access (API-scoped).
 *   - The backend enforces authorization independently; the frontend
 *     case list is UX only, not a security boundary.
 *   - All answers are grounded in authorized evidence only.
 *
 * DISCLAIMER: AI-generated answers may be incorrect. Always verify
 * claims against the cited source documents.
 */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import Navbar from "@/components/Navbar";
import { useAuth } from "@/context/AuthContext";
import { ApiError, AskResponse, CaseResponse, ConversationResponse, SourceCitation, api } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: SourceCitation[];
  insufficient_evidence?: boolean;
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function ChatPage() {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  const [question, setQuestion] = useState("");
  const [selectedCaseId, setSelectedCaseId] = useState<string>("");
  const [conversationId, setConversationId] = useState<string | null>(null);

  const [cases, setCases] = useState<CaseResponse[]>([]);
  const [conversations, setConversations] = useState<ConversationResponse[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Redirect if not authenticated
  useEffect(() => {
    if (!isLoading && !user) router.push("/login");
  }, [isLoading, user, router]);

  // Load accessible cases for the case scope dropdown
  useEffect(() => {
    if (!user) return;
    api.cases.list().catch(() => []).then(setCases);
  }, [user]);

  // Load conversation history sidebar
  useEffect(() => {
    if (!user) return;
    api.chat.listConversations().then(setConversations).catch(() => {});
  }, [user, conversationId]);

  // Scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || asking) return;

    setAsking(true);
    setError(null);

    // Optimistically add user message
    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setQuestion("");

    try {
      const response: AskResponse = await api.chat.ask({
        question: trimmed,
        conversation_id: conversationId,
        case_id: selectedCaseId || null,
      });

      if (!conversationId) {
        setConversationId(response.conversation_id);
      }

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: response.answer,
          sources: response.sources,
          insufficient_evidence: response.insufficient_evidence,
        },
      ]);
    } catch (err) {
      // Remove the optimistic user message on failure
      setMessages((prev) => prev.slice(0, -1));
      setQuestion(trimmed);

      if (err instanceof ApiError) {
        if (err.status === 503) {
          setError("AI service is temporarily unavailable. Please try again later.");
        } else if (err.status === 422) {
          setError(err.message);
        } else {
          setError("Failed to get an answer. Please try again.");
        }
      } else {
        setError("Failed to get an answer. Please try again.");
      }
    } finally {
      setAsking(false);
      inputRef.current?.focus();
    }
  };

  const handleNewConversation = () => {
    setConversationId(null);
    setMessages([]);
    setSelectedCaseId("");
    setError(null);
    inputRef.current?.focus();
  };

  const handleLoadConversation = async (conv: ConversationResponse) => {
    setConversationId(conv.id);
    setSelectedCaseId(conv.case_id ?? "");
    setError(null);

    try {
      const msgs = await api.chat.getMessages(conv.id);
      setMessages(
        msgs.map((m) => ({
          role: m.role,
          content: m.content,
        })),
      );
    } catch {
      setError("Failed to load conversation.");
    }
  };

  const handleDeleteConversation = async (convId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await api.chat.deleteConversation(convId);
      setConversations((prev) => prev.filter((c) => c.id !== convId));
      if (conversationId === convId) {
        setConversationId(null);
        setMessages([]);
      }
    } catch {
      setError("Failed to delete conversation.");
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleAsk(e as unknown as React.FormEvent);
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

      <div className="flex flex-1 max-w-7xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-6 gap-6">
        {/* Sidebar: conversations */}
        <aside className="hidden lg:flex flex-col w-64 shrink-0 gap-3">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Conversations
            </h2>
            <button
              onClick={handleNewConversation}
              className="text-xs text-indigo-600 hover:text-indigo-800 font-medium transition-colors"
            >
              + New
            </button>
          </div>

          <div className="flex flex-col gap-1 overflow-y-auto max-h-[calc(100vh-180px)]">
            {conversations.length === 0 && (
              <p className="text-xs text-slate-400 px-2 py-1">No conversations yet.</p>
            )}
            {conversations.map((conv) => (
              <button
                key={conv.id}
                onClick={() => handleLoadConversation(conv)}
                className={`group flex items-start justify-between w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                  conv.id === conversationId
                    ? "bg-indigo-50 text-indigo-900 font-medium"
                    : "text-slate-700 hover:bg-slate-100"
                }`}
              >
                <span className="truncate flex-1 min-w-0">
                  {conv.title ?? "Untitled conversation"}
                </span>
                <span
                  role="button"
                  tabIndex={0}
                  onClick={(e) => handleDeleteConversation(conv.id, e)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      void handleDeleteConversation(conv.id, e as unknown as React.MouseEvent);
                    }
                  }}
                  className="ml-1 shrink-0 text-slate-300 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100"
                  aria-label="Delete conversation"
                >
                  ×
                </span>
              </button>
            ))}
          </div>
        </aside>

        {/* Main chat area */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <div>
              <h1 className="text-2xl font-bold text-slate-900">Ask AI</h1>
              <p className="text-sm text-slate-500">
                Get AI-generated answers grounded in your authorized documents.
              </p>
            </div>

            {/* Case scope selector */}
            <div className="hidden sm:flex items-center gap-2">
              <label className="text-xs text-slate-500 whitespace-nowrap">Scope to case:</label>
              <select
                value={selectedCaseId}
                onChange={(e) => {
                  setSelectedCaseId(e.target.value);
                  if (conversationId) {
                    // Changing case scope starts a new conversation
                    setConversationId(null);
                    setMessages([]);
                  }
                }}
                disabled={asking}
                className="text-sm border border-slate-300 rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-indigo-500 max-w-48"
              >
                <option value="">All cases</option>
                {cases.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.case_number} — {c.title}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Messages area */}
          <div className="flex-1 flex flex-col gap-4 mb-4 overflow-y-auto max-h-[calc(100vh-340px)]">
            {messages.length === 0 && (
              <div className="flex-1 flex items-center justify-center py-16">
                <div className="text-center max-w-sm">
                  <div className="text-4xl mb-3">💬</div>
                  <p className="text-slate-700 font-medium">Ask a question about your documents</p>
                  <p className="text-sm text-slate-500 mt-1">
                    Answers are grounded exclusively in your authorized document content.
                  </p>
                </div>
              </div>
            )}

            {messages.map((msg, idx) =>
              msg.role === "user" ? (
                <UserMessage key={idx} content={msg.content} />
              ) : (
                <AssistantMessage
                  key={idx}
                  content={msg.content}
                  sources={msg.sources ?? []}
                  insufficientEvidence={msg.insufficient_evidence ?? false}
                />
              ),
            )}

            {asking && (
              <div className="flex gap-3">
                <div className="w-7 h-7 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-700 text-xs font-bold shrink-0 mt-0.5">
                  AI
                </div>
                <div className="bg-white border border-slate-200 rounded-xl px-4 py-3 text-sm text-slate-500 italic">
                  Thinking…
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          {/* Error */}
          {error && (
            <div className="mb-3 bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
              {error}
            </div>
          )}

          {/* Disclaimer */}
          <p className="text-xs text-slate-400 mb-2">
            AI-generated answers may be incorrect. Always verify claims against the cited source
            documents.
          </p>

          {/* Input form */}
          <form onSubmit={handleAsk} className="flex gap-3 items-end">
            <textarea
              ref={inputRef}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question about your documents… (Enter to send, Shift+Enter for newline)"
              maxLength={2000}
              rows={2}
              disabled={asking}
              className="flex-1 border border-slate-300 rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
            />
            <button
              type="submit"
              disabled={asking || !question.trim()}
              className="px-5 py-3 bg-indigo-700 text-white text-sm font-medium rounded-xl hover:bg-indigo-800 disabled:opacity-50 transition-colors shrink-0"
            >
              {asking ? "…" : "Send"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Message components
// ---------------------------------------------------------------------------

function UserMessage({ content }: { content: string }) {
  return (
    <div className="flex gap-3 justify-end">
      <div className="bg-indigo-700 text-white rounded-xl px-4 py-3 text-sm max-w-2xl whitespace-pre-wrap">
        {content}
      </div>
    </div>
  );
}

function AssistantMessage({
  content,
  sources,
  insufficientEvidence,
}: {
  content: string;
  sources: SourceCitation[];
  insufficientEvidence: boolean;
}) {
  const [showSources, setShowSources] = useState(false);

  return (
    <div className="flex gap-3">
      <div className="w-7 h-7 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-700 text-xs font-bold shrink-0 mt-0.5">
        AI
      </div>
      <div className="flex-1 min-w-0">
        <div
          className={`rounded-xl px-4 py-3 text-sm text-slate-800 whitespace-pre-wrap max-w-2xl ${
            insufficientEvidence
              ? "bg-amber-50 border border-amber-200"
              : "bg-white border border-slate-200"
          }`}
        >
          {content}
        </div>

        {sources.length > 0 && (
          <div className="mt-2 max-w-2xl">
            <button
              onClick={() => setShowSources((s) => !s)}
              className="text-xs text-indigo-600 hover:text-indigo-800 font-medium transition-colors"
            >
              {showSources ? "Hide" : "Show"} {sources.length} source
              {sources.length !== 1 ? "s" : ""}
            </button>

            {showSources && (
              <div className="mt-2 space-y-2">
                {sources.map((src, i) => (
                  <SourceCard key={src.chunk_id} source={src} index={i + 1} />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function SourceCard({ source, index }: { source: SourceCitation; index: number }) {
  const similarityPct = Math.round(source.similarity * 100);

  return (
    <div className="bg-slate-50 border border-slate-200 rounded-lg p-3">
      <div className="flex items-start justify-between gap-3 mb-1.5">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-xs font-mono text-slate-400">[{index}]</span>
            <span className="text-xs font-semibold text-slate-800 truncate">
              {source.document_name}
            </span>
            {source.page_number != null && (
              <span className="text-xs text-slate-500">p. {source.page_number}</span>
            )}
          </div>
          <Link
            href={`/cases/${source.case_id}`}
            className="text-xs text-indigo-600 hover:text-indigo-800 transition-colors"
          >
            View case
          </Link>
        </div>
        <span
          className={`shrink-0 text-xs font-semibold px-2 py-0.5 rounded-full ${
            similarityPct >= 80
              ? "bg-green-100 text-green-800"
              : similarityPct >= 60
                ? "bg-blue-100 text-blue-800"
                : "bg-slate-100 text-slate-600"
          }`}
        >
          {similarityPct}%
        </span>
      </div>
      <p className="text-xs text-slate-600 leading-relaxed line-clamp-3">{source.excerpt}</p>
    </div>
  );
}
