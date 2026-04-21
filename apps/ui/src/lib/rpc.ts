import { invoke } from "@tauri-apps/api/core";

export type RpcInvokeError = {
  kind?: string;
  message?: string;
  code?: number;
  data?: {
    role?: string;
    url?: string;
    status?: number;
    detail?: string;
  } | null;
};

function isRpcInvokeError(value: unknown): value is RpcInvokeError {
  return typeof value === "object" && value !== null && "message" in value;
}

function roleLabel(role: unknown): string {
  switch (role) {
    case "llm":
      return "답변";
    case "embed":
      return "임베딩";
    case "rerank":
      return "재정렬";
    default:
      return "추론";
  }
}

export function formatRpcError(error: unknown): string {
  if (isRpcInvokeError(error)) {
    const code = error.code;
    const role = roleLabel(error.data?.role);
    if (code === -32010) {
      return `${role} 서버 API 키가 없거나 유효하지 않습니다. 설정에서 키를 확인하세요.`;
    }
    if (code === -32011) {
      return `${role} 서버 주소 또는 모델 ID를 찾을 수 없습니다. 설정 값을 확인하세요.`;
    }
    if (code === -32012) {
      return `${role} 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.`;
    }
    if (code === -32013) {
      return `${role} 서버 응답 형식이 올바르지 않습니다. OpenAI 호환 API인지 확인하세요.`;
    }
    if (typeof error.message === "string" && error.message.trim()) {
      return error.message;
    }
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  if (typeof error === "string") {
    return error;
  }
  return "알 수 없는 오류가 발생했습니다.";
}

/**
 * Call the Python sidecar through the Tauri shell.
 * The Rust side enforces framing and id matching; the JS side only cares
 * about method + params + returned value.
 */
export async function rpc<T = unknown>(
  method: string,
  params: Record<string, unknown> = {},
): Promise<T> {
  return (await invoke("rpc_call", { method, params })) as T;
}

export async function openInOs(path: string): Promise<void> {
  await rpc("open_file", { path });
}

// ---- typed helpers ---------------------------------------------------------

export type SearchResult = {
  chunk_id: string;
  doc_id: string;
  snippet: string;
  snippet_html?: string;
  score: number;
  fusion_score: number | null;
  source_path: string;
  source_path_display: string;
  format: string;
  title: string | null;
  classification: string | null;
};

export type SearchResponse = {
  query: string;
  results: SearchResult[];
  answer?: {
    answered: boolean;
    answer: string;
    citations: { index: number; source_path_display: string }[];
  };
};

export async function search(
  query: string,
  opts: { topK?: number; ask?: boolean } = {},
): Promise<SearchResponse & { warning?: string; detail?: string }> {
  return rpc<SearchResponse & { warning?: string; detail?: string }>("search", {
    query,
    top_k: opts.topK ?? 10,
    mode: opts.ask ? "ask" : "search",
  });
}

// ---- fast (file-name) search ---------------------------------------------

export type FastRow = {
  path: string;
  name: string;
  parent: string;
  size: number;
  mtime: number;
  ext: string;
};

export type FastSearchResponse = {
  query: string;
  results: FastRow[];
  total_indexed: number;
};

export async function filesSearch(
  query: string,
  opts: { limit?: number; exts?: string[] } = {},
): Promise<FastSearchResponse> {
  return rpc<FastSearchResponse>("files.search", {
    query,
    limit: opts.limit ?? 50,
    exts: opts.exts ?? null,
  });
}

export type FastStats = {
  total: number;
  by_ext: { ext: string; count: number }[];
};

export async function filesStats(): Promise<FastStats> {
  return rpc<FastStats>("files.stats");
}

export async function indexRescan(): Promise<{
  totals: { roots: number; seen: number; upserted: number };
  per_root: Array<{ root: string; seen?: number; upserted?: number; error?: string }>;
}> {
  return rpc("index.rescan");
}

export type DocPathCandidate = {
  path: string;
  display_name: string;
  exists: boolean;
  has_documents: boolean;
  sample_count: number;
};

export async function docpathsDiscover(): Promise<{ candidates: DocPathCandidate[] }> {
  return rpc<{ candidates: DocPathCandidate[] }>("docpaths.discover");
}

export async function docpathsAddDefaults(): Promise<{ added: string[]; skipped: string[] }> {
  return rpc("docpaths.add_defaults");
}

export async function addRoot(path: string): Promise<{
  ok: boolean;
  path?: string;
  error?: string;
  existing_root?: string;
}> {
  return rpc("index.add_root", { path });
}

export async function removeRoot(path: string): Promise<{ ok: boolean; removed: number }> {
  return rpc("index.remove_root", { path });
}

export type IndexStatus = {
  roots: string[];
  index: { doc_count: number; db_path: string };
};

export async function indexStatus(): Promise<IndexStatus> {
  return rpc<IndexStatus>("index.status");
}

export type IndexDiskUsage = {
  total_bytes: number;
  by_store: {
    meta: number;
    fts: number;
    vectors: number;
    fast_index: number;
    history: number;
    schema?: number;
    other: number;
  };
  index_dir: string;
};

export async function indexDiskUsage(): Promise<IndexDiskUsage> {
  return rpc<IndexDiskUsage>("index.disk_usage");
}

export async function indexReset(): Promise<{ ok: boolean; deleted_bytes: number; restarted: boolean }> {
  return rpc<{ ok: boolean; deleted_bytes: number; restarted: boolean }>("index.reset", {
    confirm: true,
  });
}

export async function ping(): Promise<{ ok: boolean; version: string }> {
  return rpc("ping");
}

// ---- recent queries / opens --------------------------------------------

export type HistoryQuery = { query: string; last_used_ts: number; count: number };
export type HistoryOpen = { path: string; last_used_ts: number; count: number };
export type HistoryTop = {
  queries?: HistoryQuery[];
  opens?: HistoryOpen[];
};

export async function historyTop(opts: {
  queries?: number;
  opens?: number;
} = {}): Promise<HistoryTop> {
  const kinds: string[] = [];
  if (opts.queries !== undefined) kinds.push("queries");
  if (opts.opens !== undefined) kinds.push("opens");
  return rpc<HistoryTop>("history.top", {
    kinds: kinds.length ? kinds : ["queries", "opens"],
    limit_query: opts.queries ?? 5,
    limit_open: opts.opens ?? 10,
  });
}

export async function historyClear(): Promise<{ ok: boolean }> {
  return rpc<{ ok: boolean }>("history.clear");
}

// ---- indexer progress ----------------------------------------------------

export type IndexerProgress = {
  running: boolean;
  stats: { indexed: number; skipped: number; deleted: number; errors: number };
  queue_size: number;
  last_file: string | null;
  last_event_ts: number;
};

export async function indexerStatus(): Promise<IndexerProgress> {
  return rpc<IndexerProgress>("indexer.status");
}

export type AutostartStatus = {
  platform: string;
  enabled: boolean;
  path?: string;
  value?: string;
};

export async function autostartStatus(): Promise<AutostartStatus> {
  return rpc<AutostartStatus>("autostart.status");
}

export async function autostartEnable(): Promise<unknown> {
  return rpc("autostart.enable");
}

export async function autostartDisable(): Promise<unknown> {
  return rpc("autostart.disable");
}

// ---- endpoints ------------------------------------------------------------

export type Role = "llm" | "embed" | "rerank";

export type Endpoint = {
  base_url: string;
  model_id: string;
  api_key: string;
  api_kind: string;
};

export type EndpointHealth = {
  configured: boolean;
  reachable: boolean;
  error: string | null;
  models: string[];
  active_model: string;
  base_url: string;
  model_id: string;
  api_kind: string;
  remote: boolean;
};

export async function endpointsHealth(): Promise<{ roles: Record<Role, EndpointHealth> }> {
  return rpc<{ roles: Record<Role, EndpointHealth> }>("endpoints.health");
}

export type ProbeResult = {
  base_url: string;
  api_kind: string;
  reachable: boolean;
  models: string[];
  error: string | null;
};

export async function endpointsDiscover(): Promise<{ endpoints: ProbeResult[] }> {
  return rpc<{ endpoints: ProbeResult[] }>("endpoints.discover");
}

export async function endpointsTest(base_url: string, api_key = "", api_kind = "openai"): Promise<ProbeResult> {
  return rpc<ProbeResult>("endpoints.test", { base_url, api_key, api_kind });
}

export async function endpointsUpdate(role: Role, endpoint: Endpoint): Promise<unknown> {
  return rpc("endpoints.update", { role, endpoint });
}

export type AutoConnectResult = {
  actions: string[];
  assigned: Record<string, { base_url: string; model_id: string; api_kind: string }>;
  probed: number;
  well_known_scanned: number;
};

export async function endpointsAutoConnect(force = false): Promise<AutoConnectResult> {
  return rpc<AutoConnectResult>("endpoints.auto_connect", { force });
}

export type Preset = {
  key: string;
  display: string;
  base_url: string;
  api_kind: string;
  requires_api_key: boolean;
  default_models: string[];
  notes: string;
  remote: boolean;
};

export async function endpointsPresets(): Promise<{ presets: Preset[] }> {
  return rpc<{ presets: Preset[] }>("endpoints.presets");
}

export type Settings = {
  model: {
    llm: Endpoint;
    embed: Endpoint;
    rerank: Endpoint;
    llm_context_tokens: number;
  };
  index: {
    roots: string[];
    max_file_bytes: number;
    extensions: string[];
    ignore_patterns: string[];
    incremental_interval_sec: number;
    batch_understand_hour: number;
  };
  search: { strict_provenance: boolean; bm25_top_k: number; dense_top_k: number; rerank_top_k: number };
};

export async function getSettings(): Promise<Settings> {
  return rpc<Settings>("settings.get");
}

export async function updateSettings(settings: Settings): Promise<Settings> {
  return rpc<Settings>("settings.update", settings as unknown as Record<string, unknown>);
}
