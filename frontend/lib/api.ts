const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface HealthResponse {
  status: string;
  version: string;
  database: string;
}

export interface UserResponse {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface ClientResponse {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  organization: string | null;
  created_at: string;
  updated_at: string;
}

export interface ClientCreate {
  name: string;
  email?: string | null;
  phone?: string | null;
  organization?: string | null;
}

export interface ClientUpdate {
  name?: string | null;
  email?: string | null;
  phone?: string | null;
  organization?: string | null;
}

export type CaseStatus = "OPEN" | "CLOSED" | "ARCHIVED";
export type CaseMemberRole = "OWNER" | "MEMBER" | "VIEWER";

export interface CaseResponse {
  id: string;
  client_id: string;
  case_number: string;
  title: string;
  description: string | null;
  status: CaseStatus;
  created_at: string;
  updated_at: string;
}

export interface CaseCreate {
  client_id: string;
  case_number: string;
  title: string;
  description?: string | null;
  status?: CaseStatus;
}

export interface CaseUpdate {
  title?: string | null;
  description?: string | null;
  status?: CaseStatus | null;
}

export interface CaseMembershipResponse {
  id: string;
  case_id: string;
  user_id: string;
  role: CaseMemberRole;
  created_at: string;
}

export interface CaseMembershipCreate {
  user_id: string;
  role: CaseMemberRole;
}

export interface CaseMembershipUpdate {
  role: CaseMemberRole;
}

export type DocumentStatus = "UPLOADED" | "PROCESSING" | "READY" | "FAILED";

export interface DocumentResponse {
  id: string;
  case_id: string;
  uploaded_by: string | null;
  original_filename: string;
  content_type: string;
  file_size: number;
  file_hash: string;
  status: DocumentStatus;
  page_count: number | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentChunkResponse {
  id: string;
  document_id: string;
  chunk_index: number;
  content: string;
  token_count: number | null;
  page_number: number | null;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(init.headers as Record<string, string>),
  };
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new ApiError(res.status, (body as { detail?: string }).detail ?? "Request failed");
  }
  if (res.status === 204) return undefined as unknown as T;
  return res.json() as Promise<T>;
}

async function requestBlob(path: string, init: RequestInit = {}): Promise<Blob> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(init.headers as Record<string, string>),
  };
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new ApiError(res.status, (body as { detail?: string }).detail ?? "Request failed");
  }
  return res.blob();
}

async function requestMultipart<T>(path: string, formData: FormData): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    // Do NOT set Content-Type for multipart — browser sets it with boundary
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers,
    body: formData,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new ApiError(res.status, (body as { detail?: string }).detail ?? "Request failed");
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Public API client
// ---------------------------------------------------------------------------

export const api = {
  health(): Promise<HealthResponse> {
    return request<HealthResponse>("/health");
  },

  register(email: string, password: string, fullName: string): Promise<UserResponse> {
    return request<UserResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, full_name: fullName }),
    });
  },

  login(email: string, password: string): Promise<TokenResponse> {
    return request<TokenResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },

  logout(): Promise<{ message: string }> {
    return request<{ message: string }>("/auth/logout", { method: "POST" });
  },

  getCurrentUser(): Promise<UserResponse> {
    return request<UserResponse>("/auth/me");
  },

  clients: {
    list(): Promise<ClientResponse[]> {
      return request<ClientResponse[]>("/clients");
    },
    get(id: string): Promise<ClientResponse> {
      return request<ClientResponse>(`/clients/${id}`);
    },
    create(data: ClientCreate): Promise<ClientResponse> {
      return request<ClientResponse>("/clients", {
        method: "POST",
        body: JSON.stringify(data),
      });
    },
    update(id: string, data: ClientUpdate): Promise<ClientResponse> {
      return request<ClientResponse>(`/clients/${id}`, {
        method: "PUT",
        body: JSON.stringify(data),
      });
    },
    delete(id: string): Promise<void> {
      return request<void>(`/clients/${id}`, { method: "DELETE" });
    },
  },

  cases: {
    list(): Promise<CaseResponse[]> {
      return request<CaseResponse[]>("/cases");
    },
    get(id: string): Promise<CaseResponse> {
      return request<CaseResponse>(`/cases/${id}`);
    },
    create(data: CaseCreate): Promise<CaseResponse> {
      return request<CaseResponse>("/cases", {
        method: "POST",
        body: JSON.stringify(data),
      });
    },
    update(id: string, data: CaseUpdate): Promise<CaseResponse> {
      return request<CaseResponse>(`/cases/${id}`, {
        method: "PUT",
        body: JSON.stringify(data),
      });
    },
    delete(id: string): Promise<void> {
      return request<void>(`/cases/${id}`, { method: "DELETE" });
    },
  },

  documents: {
    upload(caseId: string, file: File): Promise<DocumentResponse> {
      const form = new FormData();
      form.append("file", file);
      return requestMultipart<DocumentResponse>(`/cases/${caseId}/documents`, form);
    },
    list(caseId: string): Promise<DocumentResponse[]> {
      return request<DocumentResponse[]>(`/cases/${caseId}/documents`);
    },
    get(documentId: string): Promise<DocumentResponse> {
      return request<DocumentResponse>(`/documents/${documentId}`);
    },
    download(documentId: string): Promise<Blob> {
      return requestBlob(`/documents/${documentId}/download`);
    },
    listChunks(documentId: string): Promise<DocumentChunkResponse[]> {
      return request<DocumentChunkResponse[]>(`/documents/${documentId}/chunks`);
    },
    delete(documentId: string): Promise<void> {
      return request<void>(`/documents/${documentId}`, { method: "DELETE" });
    },
  },

  caseMembers: {
    list(caseId: string): Promise<CaseMembershipResponse[]> {
      return request<CaseMembershipResponse[]>(`/cases/${caseId}/members`);
    },
    add(caseId: string, data: CaseMembershipCreate): Promise<CaseMembershipResponse> {
      return request<CaseMembershipResponse>(`/cases/${caseId}/members`, {
        method: "POST",
        body: JSON.stringify(data),
      });
    },
    update(
      caseId: string,
      userId: string,
      data: CaseMembershipUpdate,
    ): Promise<CaseMembershipResponse> {
      return request<CaseMembershipResponse>(`/cases/${caseId}/members/${userId}`, {
        method: "PUT",
        body: JSON.stringify(data),
      });
    },
    remove(caseId: string, userId: string): Promise<void> {
      return request<void>(`/cases/${caseId}/members/${userId}`, { method: "DELETE" });
    },
  },
};

// ---------------------------------------------------------------------------
// Legacy export — kept for HealthStatus component compatibility
// ---------------------------------------------------------------------------

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json() as Promise<HealthResponse>;
}
