const API_BASE = "/api";

export interface SessionSummary {
  id: string;
  repo_url: string;
  prompt: string;
  status: string;
  pr_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface RunDetail {
  id: string;
  status: string;
  commands_used: Record<string, string> | null;
  pr_url: string | null;
  pr_number: number | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface EventDetail {
  id: number;
  role: string;
  type: string;
  data: Record<string, unknown> | null;
  timestamp: string;
  replayed?: boolean;
}

export interface ArtifactDetail {
  id: string;
  type: string;
  name: string;
  path: string;
  metadata: Record<string, unknown> | null;
  size_bytes: number | null;
  created_at: string;
}

export interface MessageDetail {
  id: number;
  role: string;
  content: string;
  timestamp: string;
}

export interface SessionDetail {
  id: string;
  repo_url: string;
  prompt: string;
  status: string;
  config_overrides: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  runs: RunDetail[];
  events: EventDetail[];
  artifacts: ArtifactDetail[];
  messages: MessageDetail[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listSessions: () => request<SessionSummary[]>("/sessions"),

  getSession: (id: string) => request<SessionDetail>(`/sessions/${id}`),

  createSession: (data: { repo_url: string; prompt: string }) =>
    request<{ id: string }>("/sessions", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  triggerRun: (sessionId: string) =>
    request<{ run_id: string; status: string }>(`/sessions/${sessionId}/run`, {
      method: "POST",
    }),

  stopRun: (sessionId: string) =>
    request<{ stopped: boolean; message: string }>(
      `/sessions/${sessionId}/stop`,
      {
        method: "POST",
      },
    ),

  sendMessage: (sessionId: string, content: string) =>
    request<{ status: string }>(`/sessions/${sessionId}/message`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),

  mergeRun: (sessionId: string) =>
    request<{ merged: boolean; sha: string | null }>(
      `/sessions/${sessionId}/merge`,
      {
        method: "POST",
      },
    ),

  deleteSession: (sessionId: string) =>
    request<{ deleted: boolean }>(`/sessions/${sessionId}`, {
      method: "DELETE",
    }),

  getArtifactContent: async (sessionId: string, artifactId: string) => {
    const scopedPath = `${API_BASE}/sessions/${sessionId}/artifacts/${artifactId}/content`;
    const scopedRes = await fetch(scopedPath);
    if (scopedRes.status !== 404) {
      return scopedRes;
    }
    return fetch(`${API_BASE}/artifacts/${artifactId}/content`);
  },
};

export function subscribeToEvents(
  sessionId: string,
  onEvent: (event: EventDetail) => void,
  onError?: (err: Event) => void,
): EventSource {
  const source = new EventSource(`${API_BASE}/sessions/${sessionId}/events`);
  source.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data));
    } catch {
      // skip parse errors
    }
  };
  if (onError) {
    source.onerror = onError;
  }
  return source;
}
