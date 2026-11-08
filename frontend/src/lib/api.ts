export type GameTypeId = string;

export interface Role {
  id: string;
  label: string;
  /** Higher values take precedence over normal rules (errata = 100). */
  precedence?: number;
}

export interface GameType {
  id: GameTypeId;
  label: string;
  description: string;
  roles: Role[];
  builtin: boolean;
  game_count: number;
}

export interface Game {
  id: string;
  title: string;
  game_type: string;
  type_label: string;
  description: string;
  created_at: string;
  document_count: number;
  documents_by_role: Record<string, number>;
  chunk_count: number;
}

export type DocumentStatus = "pending" | "processing" | "ready" | "error";

export interface Document {
  id: string;
  game_id: string;
  title: string;
  role: string;
  sort_order: number;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  page_count: number;
  chunk_count: number;
  embedded_chunks: number;
  thumbnail_url: string;
  status: DocumentStatus;
  error: string | null;
  created_at: string;
  indexed_at: string | null;
}

export interface SearchResult {
  chunk_id: number;
  snippet: string;
  page_start: number | null;
  page_end: number | null;
  score: number;
  document: {
    id: string;
    title: string;
    role: string;
    role_label: string;
    precedence: number;
    overrides: boolean;
  };
  game: { id: string; title: string; game_type: string };
}

export interface EmbeddingInfo {
  provider_id: string;
  provider_name: string;
  model: string;
}

export interface SearchResponse {
  query: string;
  mode: string;
  mode_used: string;
  note: string | null;
  count: number;
  embedding: EmbeddingInfo | null;
  results: SearchResult[];
}

export interface SearchParams {
  q: string;
  game_id?: string;
  roles?: string[];
  document_id?: string;
  mode: "keyword" | "semantic" | "hybrid";
  limit?: number;
}

export interface Provider {
  id: string;
  name: string;
  kind: string;
  base_url: string;
  chat_model: string;
  embed_model: string;
  enabled: boolean;
  builtin: boolean;
  docs_url: string;
  description: string;
  has_api_key: boolean;
}

export interface Driver {
  kind: string;
  label: string;
  description: string;
  supports_embeddings: boolean;
  requires_api_key: boolean;
  default_base_url: string;
}

export interface ProviderList {
  providers: Provider[];
  drivers: Driver[];
}

export interface ModelInfo {
  id: string;
  kind: string;
}

export interface FormatInfo {
  extensions: string[];
  label: string;
  description: string;
}

export interface AppSettings {
  settings: Record<string, string>;
  info: {
    app_name: string;
    version: string;
    data_dir: string;
    chunk_size: number;
    chunk_overlap: number;
    max_upload_mb: number;
    formats: FormatInfo[];
    embedding_ready: boolean;
    embedding_error: string | null;
    embedding_model_active: string;
    chat_ready: boolean;
    chat_model_active: string;
    provider_names: Record<string, string>;
  };
}

export interface Stats {
  games: number;
  documents: number;
  chunks: number;
  embedded_chunks: number;
  documents_by_status: Record<string, number>;
  formats: number;
  data_dir: string;
  max_upload_mb: number;
}

export interface Job {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "error";
  progress: number;
  message: string;
  result: string;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let message = response.statusText || `Request failed (${response.status})`;
    try {
      const body = await response.json();
      message = body.detail ?? body.message ?? message;
      if (Array.isArray(message)) {
        message = message.map((item: { msg?: string }) => item.msg ?? String(item)).join("; ");
      }
    } catch {
      /* not JSON */
    }
    throw new ApiError(String(message), response.status);
  }
  return (await response.json()) as T;
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });

export const api = {
  stats: () => request<Stats>("/api/stats"),

  games: () => request<{ games: Game[]; total: number }>("/api/games"),
  game: (id: string) => request<Game>(`/api/games/${id}`),
  createGame: (body: { title: string; game_type: string; description: string }) =>
    post<Game>("/api/games", body),
  updateGame: (id: string, body: Partial<Pick<Game, "title" | "game_type" | "description">>) =>
    patch<Game>(`/api/games/${id}`, body),
  deleteGame: (id: string) => request<{ deleted: boolean }>(`/api/games/${id}`, { method: "DELETE" }),

  gameTypes: () => request<{ game_types: GameType[] }>("/api/game-types"),
  createGameType: (body: Omit<GameType, "builtin" | "game_count">) =>
    post<GameType>("/api/game-types", body),
  deleteGameType: (id: string) =>
    request<{ deleted: boolean }>(`/api/game-types/${id}`, { method: "DELETE" }),

  documents: (gameId?: string) =>
    request<{ documents: Document[]; total: number }>(
      `/api/documents${gameId ? `?game_id=${encodeURIComponent(gameId)}` : ""}`,
    ),
  uploadDocument: (gameId: string, role: string, file: File, title?: string) => {
    const form = new FormData();
    form.set("game_id", gameId);
    form.set("role", role);
    if (title) form.set("title", title);
    form.set("file", file);
    return request<Document>("/api/documents", { method: "POST", body: form });
  },
  updateDocument: (id: string, body: { title?: string; role?: string; sort_order?: number }) =>
    patch<Document>(`/api/documents/${id}`, body),
  deleteDocument: (id: string) =>
    request<{ deleted: boolean }>(`/api/documents/${id}`, { method: "DELETE" }),
  reindexDocument: (id: string) =>
    request<{ status: string }>(`/api/documents/${id}/reindex`, { method: "POST" }),
  page: (id: string, page: number) =>
    request<{
      document: { id: string; title: string; role: string };
      page: number;
      total_pages: number;
      chunks: { id: number; text: string; ordinal: number }[];
    }>(`/api/documents/${id}/pages?page=${page}`),
  fileUrl: (id: string, page?: number | null, download = false) =>
    `/api/documents/${id}/file${download ? "?download=true" : ""}${page ? `#page=${page}` : ""}`,

  search: (params: SearchParams) => {
    const query = new URLSearchParams({ q: params.q, mode: params.mode });
    if (params.game_id) query.set("game_id", params.game_id);
    if (params.roles?.length) query.set("roles", params.roles.join(","));
    if (params.document_id) query.set("document_id", params.document_id);
    if (params.limit) query.set("limit", String(params.limit));
    return request<SearchResponse>(`/api/search?${query.toString()}`);
  },

  providers: () => request<ProviderList>("/api/providers"),
  createProvider: (body: {
    name: string;
    kind: string;
    base_url: string;
    api_key: string;
    chat_model: string;
    embed_model: string;
    description: string;
  }) => post<Provider>("/api/providers", body),
  updateProvider: (
    id: string,
    body: Partial<{
      name: string;
      base_url: string;
      api_key: string;
      chat_model: string;
      embed_model: string;
      description: string;
      enabled: boolean;
    }>,
  ) => patch<Provider>(`/api/providers/${id}`, body),
  deleteProvider: (id: string) =>
    request<{ deleted: boolean }>(`/api/providers/${id}`, { method: "DELETE" }),
  testProvider: (id: string) =>
    request<{ ok: boolean; message: string }>(`/api/providers/${id}/test`, { method: "POST" }),
  providerModels: (id: string) =>
    request<{ models: ModelInfo[]; count: number }>(`/api/providers/${id}/models`),

  settings: () => request<AppSettings>("/api/settings"),
  updateSettings: (body: Record<string, string | number>) =>
    request<AppSettings>("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
  buildEmbeddings: (body: { game_id?: string; force?: boolean }) =>
    post<{ job_id: string; status: string }>("/api/embeddings/build", body),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
};

export interface AskPayload {
  query: string;
  game_id?: string;
  roles?: string[];
  document_id?: string;
  mode: string;
  provider_id?: string;
  model?: string;
  top_k?: number;
  temperature?: number;
  history?: { role: "user" | "assistant"; content: string }[];
}

export interface AskHandlers {
  onSources: (payload: {
    sources: SearchResult[];
    mode_used: string;
    note: string | null;
    provider: string;
    model: string;
    embedding: EmbeddingInfo | null;
  }) => void;
  onToken: (text: string) => void;
  onError: (message: string) => void;
  onDone: () => void;
}

/** POST /api/ask and consume the SSE stream. */
export async function ask(
  payload: AskPayload,
  handlers: AskHandlers,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message = body.detail ?? message;
    } catch {
      /* ignore */
    }
    throw new ApiError(String(message), response.status);
  }
  if (!response.body) throw new ApiError("Streaming is not supported by this browser.", 500);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatch = (block: string) => {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (!dataLines.length) return;
    let data: unknown;
    try {
      data = JSON.parse(dataLines.join("\n"));
    } catch {
      return;
    }
    if (event === "sources") {
      handlers.onSources(data as Parameters<AskHandlers["onSources"]>[0]);
    } else if (event === "token") {
      handlers.onToken((data as { t: string }).t);
    } else if (event === "error") {
      handlers.onError((data as { message: string }).message);
    } else if (event === "done") {
      handlers.onDone();
    }
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) dispatch(block);
  }
  if (buffer.trim()) dispatch(buffer);
  handlers.onDone();
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function formatDate(value: string): string {
  if (!value) return "";
  const date = new Date(value.endsWith("Z") || value.includes("+") ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function plural(count: number, singular: string, pluralForm?: string): string {
  return `${count} ${count === 1 ? singular : (pluralForm ?? `${singular}s`)}`;
}
