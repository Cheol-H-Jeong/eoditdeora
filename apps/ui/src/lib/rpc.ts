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
  // Route through the Python sidecar so the dev bridge, Tauri shell,
  // and future native hosts all end up in the same code path.
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

export type ModelSlot = {
  key: "llm" | "embed" | "rerank";
  display: string;
  target_path: string;
  present: boolean;
  running: boolean;
  downloaded_bytes: number;
  total_bytes: number;
  percent: number;
  error: string | null;
  cancelled: boolean;
  finished: boolean;
  source_configured: boolean;
};

export async function modelsStatus(): Promise<{ slots: ModelSlot[] }> {
  return rpc<{ slots: ModelSlot[] }>("models.status");
}

export async function modelsDownload(key: string): Promise<ModelSlot> {
  return rpc<ModelSlot>("models.download", { key });
}

export async function modelsCancel(key: string): Promise<ModelSlot> {
  return rpc<ModelSlot>("models.cancel", { key });
}

export async function llmEnsure(): Promise<unknown> {
  return rpc("llm.ensure");
}
