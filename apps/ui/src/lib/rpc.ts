import { invoke } from "@tauri-apps/api/core";

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
  score: number;
  fusion_score: number;
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
): Promise<SearchResponse> {
  return rpc<SearchResponse>("search", {
    query,
    top_k: opts.topK ?? 10,
    mode: opts.ask ? "ask" : "search",
  });
}

export async function addRoot(path: string): Promise<{ ok: boolean; path?: string; error?: string }> {
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

export async function ping(): Promise<{ ok: boolean; version: string }> {
  return rpc("ping");
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

export type Settings = {
  model: {
    llm: Endpoint;
    embed: Endpoint;
    rerank: Endpoint;
    llm_context_tokens: number;
  };
  index: { roots: string[]; max_file_bytes: number };
  search: { strict_provenance: boolean; bm25_top_k: number; dense_top_k: number; rerank_top_k: number };
};

export async function getSettings(): Promise<Settings> {
  return rpc<Settings>("settings.get");
}
