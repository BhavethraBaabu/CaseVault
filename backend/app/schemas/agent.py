"""
Agent request/response schemas — Day 7.

No storage paths, embedding vectors, credentials, or internal keys are exposed.
Citations reference only chunks from the authorized retrieval set.
"""

import uuid

from pydantic import BaseModel, Field, field_validator


class AgentRunRequest(BaseModel):
    """
    Request to run the AI agent on a task.

    task     — natural-language question or instruction (1–2000 chars, non-blank).
    case_id  — optional case scope UUID.  Backend re-verifies access; specifying
               an unauthorized case will cause relevant tool calls to return
               "Case not found" rather than leaking data.
    """

    task: str = Field(..., min_length=1, max_length=2000)
    case_id: uuid.UUID | None = None

    @field_validator("task")
    @classmethod
    def task_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("task must not be blank or whitespace-only.")
        return v.strip()


class AgentToolTrace(BaseModel):
    """
    A single entry in the agent's execution trace.

    Shows which tool ran and whether it succeeded.
    Does not include raw arguments, tool results, or internal data.
    """

    tool_name: str
    success: bool


class AgentCitation(BaseModel):
    """
    A validated source citation from the agent's document retrieval.

    Citations come exclusively from the authorized retrieval set.
    They are validated application-side; the LLM cannot inject references.
    """

    document_id: uuid.UUID
    document_name: str
    case_id: uuid.UUID
    chunk_id: uuid.UUID
    chunk_index: int
    page_number: int | None
    excerpt: str
    similarity: float


class AgentRunResponse(BaseModel):
    """
    Agent execution result.

    answer                — the agent's final response.
    tools_executed        — concise trace of tools called (name + success only).
    citations             — validated source citations when document evidence was used.
    insufficient_evidence — True when no relevant authorized documents were found.
    status                — "success" or "error".
    error                 — safe error description when status="error"; never includes
                            stack traces, storage paths, or internal details.

    DISCLAIMER: Answers are AI-generated and may be incorrect.
    Always verify claims against the cited source documents.
    """

    answer: str
    tools_executed: list[AgentToolTrace]
    citations: list[AgentCitation]
    insufficient_evidence: bool
    status: str  # "success" | "error"
    error: str | None = None
