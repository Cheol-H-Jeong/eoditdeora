<script lang="ts">
  import { onMount } from "svelte";
  import { listen } from "@tauri-apps/api/event";
  import { openInOs, ping, search, type SearchResponse } from "$lib/rpc";

  let query = $state("");
  let askMode = $state(false);
  let loading = $state(false);
  let response = $state<SearchResponse | null>(null);
  let errorMessage = $state<string | null>(null);
  let version = $state<string>("");
  let inputEl: HTMLInputElement | undefined = $state();

  onMount(async () => {
    try {
      const v = await ping();
      version = v.version;
    } catch (e) {
      errorMessage = `Sidecar not reachable: ${e}`;
    }
    await listen("hotkey:activate", () => {
      inputEl?.focus();
      inputEl?.select();
    });
  });

  async function submit() {
    if (!query.trim() || loading) return;
    loading = true;
    errorMessage = null;
    try {
      response = await search(query, { ask: askMode, topK: 10 });
    } catch (e) {
      errorMessage = String(e);
    } finally {
      loading = false;
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === "Enter") submit();
  }
</script>

<div class="spotlight">
  <header>
    <div class="brand">어딨더라</div>
    <div class="version">v{version || "?"}</div>
  </header>

  <div class="bar">
    <input
      bind:this={inputEl}
      bind:value={query}
      onkeydown={onKeydown}
      placeholder={askMode ? "무엇이 궁금한가요?" : "어떤 파일을 찾고 계신가요?"}
      autocomplete="off"
      autocorrect="off"
      spellcheck="false"
    />
    <button class="mode" class:active={askMode} onclick={() => (askMode = !askMode)}>
      {askMode ? "답변 모드" : "검색 모드"}
    </button>
  </div>

  {#if errorMessage}
    <div class="error">{errorMessage}</div>
  {/if}

  {#if loading}
    <div class="status">검색 중...</div>
  {:else if response?.answer}
    <section class="answer">
      <header>답변</header>
      <p>{response.answer.answer}</p>
      {#if response.answer.citations.length}
        <ol class="citations">
          {#each response.answer.citations as c}
            <li>
              <button class="cite" onclick={() => openInOs(c.source_path_display)}>
                §{c.index} — {c.source_path_display}
              </button>
            </li>
          {/each}
        </ol>
      {/if}
    </section>
  {/if}

  {#if response?.results?.length}
    <section class="results">
      {#each response.results as hit, i}
        <button class="card" onclick={() => openInOs(hit.source_path_display)}>
          <div class="title">
            {hit.title || hit.source_path_display.split(/[\\/]/).pop()}
            {#if hit.classification}<span class="tag">{hit.classification}</span>{/if}
          </div>
          <div class="snippet">{hit.snippet}</div>
          <div class="path">{hit.source_path_display}</div>
          <div class="score">#{i + 1} · score {hit.score.toFixed(3)}</div>
        </button>
      {/each}
    </section>
  {:else if response && !loading}
    <div class="status">결과 없음.</div>
  {/if}
</div>

<style>
  .spotlight {
    max-width: 860px;
    width: 100%;
    margin: 0 auto;
    padding: 32px 24px 48px;
  }
  header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 18px;
  }
  .brand {
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.5px;
  }
  .version {
    font-size: 11px;
    color: #6b7280;
  }
  .bar {
    display: flex;
    gap: 8px;
    background: #15181f;
    border: 1px solid #222731;
    border-radius: 12px;
    padding: 10px 12px;
  }
  input {
    flex: 1;
    background: transparent;
    border: 0;
    outline: 0;
    color: #e8e8ea;
    font-size: 17px;
    font-weight: 500;
  }
  .mode {
    border: 0;
    border-radius: 8px;
    background: #222731;
    color: #a0a6b0;
    padding: 6px 12px;
    font-size: 12px;
    cursor: pointer;
  }
  .mode.active {
    background: #4b7bff;
    color: white;
  }
  .status,
  .error {
    margin: 24px 0;
    padding: 12px 14px;
    border-radius: 10px;
    font-size: 13px;
  }
  .status {
    background: #1a1d24;
    color: #9ca3af;
  }
  .error {
    background: #3a1f22;
    color: #ffb8b8;
  }
  .answer {
    margin-top: 28px;
    padding: 18px;
    border: 1px solid #2a2f3a;
    border-radius: 12px;
    background: #101319;
  }
  .answer header {
    font-size: 11px;
    letter-spacing: 1px;
    color: #6b7280;
    text-transform: uppercase;
    margin-bottom: 8px;
  }
  .answer p {
    margin: 0 0 12px;
    line-height: 1.6;
    white-space: pre-wrap;
  }
  .citations {
    margin: 0;
    padding-left: 20px;
    font-size: 12px;
  }
  .cite {
    background: transparent;
    border: 0;
    color: #8ab4ff;
    cursor: pointer;
    padding: 0;
    text-align: left;
  }
  .results {
    margin-top: 24px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .card {
    text-align: left;
    background: #12151c;
    border: 1px solid #1f2330;
    border-radius: 10px;
    padding: 12px 14px;
    color: #e8e8ea;
    cursor: pointer;
    transition: border-color 80ms ease, background 80ms ease;
  }
  .card:hover {
    border-color: #4b7bff;
    background: #151924;
  }
  .title {
    font-size: 14px;
    font-weight: 600;
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .tag {
    font-size: 10px;
    padding: 2px 6px;
    border-radius: 999px;
    background: #4b7bff33;
    color: #8ab4ff;
  }
  .snippet {
    margin-top: 6px;
    font-size: 12px;
    line-height: 1.5;
    color: #c7cbd3;
  }
  .path {
    margin-top: 8px;
    font-size: 11px;
    color: #6b7280;
    font-family: ui-monospace, Menlo, Consolas, monospace;
  }
  .score {
    margin-top: 4px;
    font-size: 10px;
    color: #4b5563;
  }
</style>
