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

export async function addRoot(path: string): Promise<unknown> {
  return rpc("index.add_root", { path });
}

export async function indexStatus(): Promise<unknown> {
  return rpc("index.status");
}

export async function ping(): Promise<{ ok: boolean; version: string }> {
  return rpc("ping");
}
