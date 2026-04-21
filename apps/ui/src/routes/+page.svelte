<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { listen } from "@tauri-apps/api/event";
  import Settings from "$lib/Settings.svelte";
  import {
    endpointsHealth,
    filesSearch,
    filesStats,
    indexerStatus,
    openInOs,
    ping,
    search,
    type EndpointHealth,
    type FastRow,
    type FastStats,
    type IndexerProgress,
    type Role,
    type SearchResponse,
  } from "$lib/rpc";

  type Mode = "name" | "content" | "ai";

  let mode = $state<Mode>("name");
  let query = $state("");
  let loading = $state(false);
  let nameResults = $state<FastRow[]>([]);
  let nameTotal = $state(0);
  let contentResponse = $state<SearchResponse | null>(null);
  let aiResponse = $state<SearchResponse | null>(null);
  let stats = $state<FastStats | null>(null);
  let errorMessage = $state<string | null>(null);
  let warning = $state<string | null>(null);
  let version = $state<string>("");
  let showSidebar = $state(false);
  let inputEl: HTMLInputElement | undefined = $state();
  let debounceTimer: number | undefined;

  // Keyboard-nav: selectedIndex is shared across tabs and always
  // points into the currently-visible result list.
  let selectedIndex = $state(-1);

  // Indexer progress polling.
  let progress = $state<IndexerProgress | null>(null);
  let progressTimer: number | undefined;

  // Header health LED.
  let health = $state<Record<Role, EndpointHealth> | null>(null);
  let healthTimer: number | undefined;

  onMount(async () => {
    try {
      const v = await ping();
      version = v.version;
    } catch (e) {
      errorMessage = `Sidecar not reachable: ${e}`;
    }
    try {
      stats = await filesStats();
    } catch {
      stats = null;
    }
    try {
      await listen("hotkey:activate", () => {
        inputEl?.focus();
        inputEl?.select();
      });
    } catch {
      // Non-Tauri host (dev bridge) has no event bus.
    }
    inputEl?.focus();
    startProgressPoll();
    startHealthPoll();
  });

  onDestroy(() => {
    if (progressTimer) window.clearInterval(progressTimer);
    if (healthTimer) window.clearInterval(healthTimer);
    if (debounceTimer) window.clearTimeout(debounceTimer);
  });

  function startProgressPoll() {
    const tick = async () => {
      try {
        progress = await indexerStatus();
      } catch {
        progress = null;
      }
    };
    void tick();
    progressTimer = window.setInterval(tick, 2000) as unknown as number;
  }

  function startHealthPoll() {
    const tick = async () => {
      try {
        const r = await endpointsHealth();
        health = r.roles;
      } catch {
        health = null;
      }
    };
    void tick();
    healthTimer = window.setInterval(tick, 10000) as unknown as number;
  }

  function currentResults(): Array<{ path: string }> {
    if (mode === "name") {
      return nameResults.map((r) => ({ path: r.path }));
    }
    const src = mode === "content" ? contentResponse : aiResponse;
    return (src?.results ?? []).map((r) => ({ path: r.source_path_display }));
  }

  function clampSelection() {
    const n = currentResults().length;
    if (n === 0) {
      selectedIndex = -1;
      return;
    }
    if (selectedIndex < 0) selectedIndex = 0;
    if (selectedIndex >= n) selectedIndex = n - 1;
  }

  function scrollSelectedIntoView() {
    queueMicrotask(() => {
      const el = document.querySelector<HTMLElement>(
        `[data-result-index='${selectedIndex}']`,
      );
      el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  }

  $effect(() => {
    // Whenever the result list changes, reset selection to the top.
    contentResponse;
    aiResponse;
    nameResults;
    selectedIndex = currentResults().length ? 0 : -1;
  });

  function isHealthy(h: EndpointHealth | undefined): boolean {
    return !!h && h.configured && h.reachable;
  }

  function healthColor(): "green" | "amber" | "red" {
    if (!health) return "red";
    const llm = isHealthy(health.llm);
    const embed = isHealthy(health.embed);
    const rerank = isHealthy(health.rerank);
    if (llm && embed) return "green";
    if (llm || embed || rerank) return "amber";
    return "red";
  }

  function healthTooltip(): string {
    if (!health) return "사이드카 연결 확인 중";
    const parts: string[] = [];
    for (const role of ["llm", "embed", "rerank"] as Role[]) {
      const h = health[role];
      const dot = isHealthy(h) ? "●" : "○";
      const label = role === "llm" ? "LLM" : role === "embed" ? "EMBED" : "RERANK";
      const state = !h?.configured
        ? "미설정"
        : h?.reachable
          ? h.model_id || "OK"
          : h?.error ?? "연결 안됨";
      parts.push(`${dot} ${label}: ${state}`);
    }
    return parts.join("\n");
  }

  function indexingActive(): boolean {
    if (!progress) return false;
    if (progress.queue_size > 0) return true;
    // "recently active" = event within the last 3s
    const nowSec = Date.now() / 1000;
    return progress.last_event_ts > 0 && nowSec - progress.last_event_ts < 3;
  }

  // Reactive: typing in name mode triggers a debounced fast search so
  // results land as the user types without hammering the backend.
  $effect(() => {
    const q = query;
    const m = mode;
    if (debounceTimer !== undefined) {
      clearTimeout(debounceTimer);
      debounceTimer = undefined;
    }
    if (m !== "name") return;
    if (!q.trim()) {
      nameResults = [];
      return;
    }
    debounceTimer = window.setTimeout(() => runNameSearch(q), 120) as unknown as number;
  });

  async function runNameSearch(q: string) {
    loading = true;
    errorMessage = null;
    warning = null;
    try {
      const r = await filesSearch(q, { limit: 100 });
      nameResults = r.results;
      nameTotal = r.total_indexed;
      if (r.total_indexed === 0) {
        warning = "아직 색인된 파일이 없습니다. 설정에서 문서 폴더를 추가하거나 잠시 기다려주세요.";
      }
    } catch (e) {
      errorMessage = String(e);
    } finally {
      loading = false;
    }
  }

  async function runContentSearch(q: string, ask: boolean) {
    loading = true;
    errorMessage = null;
    warning = null;
    try {
      const r = await search(q, { ask, topK: 10 });
      if (ask) aiResponse = r;
      else contentResponse = r;
      if (r.warning === "no_results") {
        warning = "일치하는 문서가 없습니다. 본문 색인이 아직 진행 중일 수 있습니다.";
      } else if (r.warning === "search_backend_failed") {
        warning = `검색 엔진 오류: ${r.detail ?? "알 수 없음"}`;
      }
    } catch (e) {
      errorMessage = String(e);
    } finally {
      loading = false;
    }
  }

  function onKeydown(e: KeyboardEvent) {
    // Esc clears the query from anywhere.
    if (e.key === "Escape") {
      if (query) {
        e.preventDefault();
        query = "";
        nameResults = [];
        contentResponse = null;
        aiResponse = null;
        warning = null;
        selectedIndex = -1;
        return;
      }
    }
    const results = currentResults();
    if ((e.key === "ArrowDown" || e.key === "ArrowUp") && results.length) {
      e.preventDefault();
      if (e.key === "ArrowDown") {
        selectedIndex = Math.min(selectedIndex + 1, results.length - 1);
      } else {
        selectedIndex = Math.max(selectedIndex - 1, 0);
      }
      scrollSelectedIntoView();
      return;
    }
    if (e.key === "Enter") {
      if (selectedIndex >= 0 && selectedIndex < results.length) {
        e.preventDefault();
        void openInOs(results[selectedIndex].path);
        return;
      }
      if (mode === "content") void runContentSearch(query, false);
      if (mode === "ai") void runContentSearch(query, true);
    }
  }

  function onTabClick(m: Mode) {
    mode = m;
    errorMessage = null;
    warning = null;
    selectedIndex = -1;
    if (m === "name" && query.trim()) {
      void runNameSearch(query);
    }
  }

  function humanSize(n: number): string {
    if (n < 1024) return `${n} B`;
    const kb = n / 1024;
    if (kb < 1024) return `${kb.toFixed(1)} KB`;
    const mb = kb / 1024;
    if (mb < 1024) return `${mb.toFixed(1)} MB`;
    return `${(mb / 1024).toFixed(1)} GB`;
  }

  function humanDate(mtime: number): string {
    if (!mtime) return "";
    return new Date(mtime * 1000).toLocaleDateString("ko-KR", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
  }

  function basename(p: string): string {
    return p.split(/[\\/]/).pop() ?? p;
  }

  function parentDir(p: string): string {
    const parts = p.split(/[\\/]/);
    parts.pop();
    return parts.join("/");
  }
</script>

<div class="app">
  <div class="main" class:no-sidebar={!showSidebar}>
    <header>
      <div class="brand">어딨더라</div>
      <div class="toolbar">
        {#if stats}
          <div class="stat-badge" title="파일명 인덱스 크기">
            📂 {stats.total.toLocaleString()}
          </div>
        {/if}
        <button
          class="health health-{healthColor()}"
          onclick={() => (showSidebar = true)}
          title={healthTooltip()}
          aria-label="엔드포인트 상태"
        ><span class="led"></span></button>
        <button
          class="gear"
          onclick={() => (showSidebar = !showSidebar)}
          title={showSidebar ? "설정 닫기" : "설정 열기"}
        >⚙</button>
        <div class="version">v{version || "?"}</div>
      </div>
    </header>

    <div class="tabs">
      <button class="tab" class:active={mode === "name"} onclick={() => onTabClick("name")}>
        <span class="tab-title">파일명</span>
        <span class="tab-hint">실시간</span>
      </button>
      <button class="tab" class:active={mode === "content"} onclick={() => onTabClick("content")}>
        <span class="tab-title">내용</span>
        <span class="tab-hint">키워드 · AI 불필요</span>
      </button>
      <button class="tab" class:active={mode === "ai"} onclick={() => onTabClick("ai")}>
        <span class="tab-title">AI</span>
        <span class="tab-hint">답변 생성</span>
      </button>
    </div>

    <div class="bar">
      <input
        bind:this={inputEl}
        bind:value={query}
        onkeydown={onKeydown}
        placeholder={mode === "name"
          ? "파일명 / 경로 일부 — 타이핑하면 바로 나옵니다"
          : mode === "content"
          ? "문서 본문에서 찾을 키워드 (Enter)"
          : "무엇이 궁금한가요? (Enter)"}
        autocomplete="off"
        autocorrect="off"
        spellcheck="false"
      />
    </div>

    {#if errorMessage}
      <div class="error">{errorMessage}</div>
    {/if}
    {#if warning}
      <div class="warning">{warning}</div>
    {/if}
    {#if indexingActive() && progress}
      <div class="progress" role="status" aria-live="polite">
        <span class="spinner"></span>
        <span class="progress-text">
          인덱싱 중 · {progress.stats.indexed.toLocaleString()}개 완료 · 대기 {progress.queue_size}
          {#if progress.last_file}
            <span class="progress-file" title={progress.last_file}>· {progress.last_file.split(/[\\/]/).pop()}</span>
          {/if}
        </span>
      </div>
    {/if}
    {#if loading}
      <div class="status">검색 중...</div>
    {/if}

    {#if mode === "name"}
      {#if nameResults.length}
        <section class="file-list">
          {#each nameResults as r, i}
            <button
              class="file-row"
              class:selected={i === selectedIndex}
              data-result-index={i}
              onclick={() => openInOs(r.path)}
            >
              <div class="file-name">
                <span class="ext-chip">{r.ext || "file"}</span>
                <span class="name-text">{r.name}</span>
              </div>
              <div class="file-meta">
                <span class="file-parent">{r.parent}</span>
                <span class="file-size">{humanSize(r.size)}</span>
                <span class="file-date">{humanDate(r.mtime)}</span>
              </div>
            </button>
          {/each}
        </section>
      {:else if query.trim() && !loading}
        <div class="status">일치하는 파일명이 없습니다.</div>
      {:else if !query.trim()}
        <div class="hint-panel">
          <p>👆 검색어를 입력하면 PC에 있는 문서 파일명을 즉시 찾습니다.</p>
          {#if stats && stats.total > 0}
            <p class="small">현재 색인된 파일: <strong>{stats.total.toLocaleString()}</strong>개</p>
            {#if stats.by_ext.length}
              <div class="ext-breakdown">
                {#each stats.by_ext.slice(0, 8) as b}
                  <span class="ext-pill">{b.ext} {b.count.toLocaleString()}</span>
                {/each}
              </div>
            {/if}
          {:else}
            <p class="small">아직 색인된 파일이 없습니다. 오른쪽 설정에서 문서 폴더를 추가하세요.</p>
          {/if}
        </div>
      {/if}
    {:else if mode === "content"}
      {#if contentResponse?.results?.length}
        <section class="results">
          {#each contentResponse.results as hit, i}
            <button
              class="card"
              class:selected={i === selectedIndex}
              data-result-index={i}
              onclick={() => openInOs(hit.source_path_display)}
            >
              <div class="title">
                {hit.title || basename(hit.source_path_display)}
                {#if hit.classification}<span class="tag">{hit.classification}</span>{/if}
              </div>
              <div class="snippet">
                {#if hit.snippet_html}
                  {@html hit.snippet_html}
                {:else}
                  {hit.snippet}
                {/if}
              </div>
              <div class="path">{hit.source_path_display}</div>
              <div class="score">#{i + 1} · score {hit.score.toFixed(3)}</div>
            </button>
          {/each}
        </section>
      {:else if contentResponse && !loading}
        <div class="status">결과 없음. 본문 색인이 아직일 수 있습니다.</div>
      {:else if !query.trim()}
        <div class="hint-panel">
          <p>📄 문서 본문에서 키워드를 찾습니다. BM25 렉시컬 검색 — AI 서버가 꺼져있어도 즉답.</p>
          <p class="small">Enter 또는 탭 전환으로 실행됩니다.</p>
        </div>
      {/if}
    {:else if mode === "ai"}
      {#if aiResponse?.answer}
        <section class="answer">
          <header>답변</header>
          <p>{aiResponse.answer.answer}</p>
          {#if aiResponse.answer.citations.length}
            <ol class="citations">
              {#each aiResponse.answer.citations as c}
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
      {#if aiResponse?.results?.length}
        <section class="results">
          {#each aiResponse.results as hit, i}
            <button
              class="card"
              class:selected={i === selectedIndex}
              data-result-index={i}
              onclick={() => openInOs(hit.source_path_display)}
            >
              <div class="title">
                {hit.title || basename(hit.source_path_display)}
                {#if hit.classification}<span class="tag">{hit.classification}</span>{/if}
              </div>
              <div class="snippet">
                {#if hit.snippet_html}
                  {@html hit.snippet_html}
                {:else}
                  {hit.snippet}
                {/if}
              </div>
              <div class="path">{hit.source_path_display}</div>
              <div class="score">#{i + 1} · score {hit.score.toFixed(3)}</div>
            </button>
          {/each}
        </section>
      {:else if !query.trim()}
        <div class="hint-panel">
          <p>🤖 질문하면 문서 근거를 찾아 답변합니다. 답변 옆 § 번호로 원본 열기.</p>
          <p class="small">LLM 엔드포인트가 설정되어 있어야 합니다.</p>
        </div>
      {/if}
    {/if}
  </div>

  {#if showSidebar}
    <Settings />
  {/if}
</div>

<style>
  .app {
    display: flex;
    min-height: 100vh;
  }
  .main {
    flex: 1;
    padding: 24px 28px 36px;
    max-width: 820px;
    margin: 0 auto;
  }
  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 14px;
  }
  .brand {
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.5px;
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .stat-badge {
    font-size: 11px;
    color: #8ab4ff;
    background: #1a1f2e;
    border: 1px solid #2a3550;
    border-radius: 12px;
    padding: 3px 10px;
  }
  .gear {
    background: transparent;
    border: 1px solid #2a2f3a;
    color: #a0a6b0;
    border-radius: 6px;
    padding: 4px 8px;
    cursor: pointer;
    font-size: 14px;
  }
  .health {
    background: transparent;
    border: 1px solid #2a2f3a;
    border-radius: 6px;
    padding: 0 8px;
    height: 26px;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
  }
  .health .led {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #4b5563;
    box-shadow: 0 0 6px transparent;
    transition: background 120ms ease, box-shadow 120ms ease;
  }
  .health-green .led { background: #22c55e; box-shadow: 0 0 6px #22c55e80; }
  .health-amber .led { background: #f59e0b; box-shadow: 0 0 6px #f59e0b80; }
  .health-red .led   { background: #ef4444; box-shadow: 0 0 6px #ef444480; }
  .progress {
    margin: 10px 0 4px;
    padding: 8px 12px;
    border-radius: 10px;
    background: #121821;
    border: 1px solid #1f2b3a;
    color: #7ec0ff;
    font-size: 12px;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .spinner {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    border: 2px solid #1f2b3a;
    border-top-color: #7ec0ff;
    animation: spin 0.9s linear infinite;
    flex-shrink: 0;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .progress-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .progress-file {
    color: #a8c5ec;
    margin-left: 4px;
    font-family: ui-monospace, Menlo, Consolas, monospace;
    font-size: 11px;
  }
  .snippet :global(mark) {
    background: #5b3b00;
    color: #ffd684;
    padding: 0 2px;
    border-radius: 3px;
  }
  .version {
    font-size: 11px;
    color: #6b7280;
  }
  .tabs {
    display: flex;
    gap: 6px;
    margin-bottom: 10px;
  }
  .tab {
    flex: 1;
    background: #15181f;
    border: 1px solid #222731;
    color: #a0a6b0;
    border-radius: 10px;
    padding: 8px 12px;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
    transition: all 80ms ease;
  }
  .tab:hover {
    border-color: #4b7bff66;
  }
  .tab.active {
    background: #1a1f2e;
    border-color: #4b7bff;
    color: #e8e8ea;
  }
  .tab-title {
    font-size: 13px;
    font-weight: 600;
  }
  .tab-hint {
    font-size: 10px;
    color: #6b7280;
  }
  .tab.active .tab-hint {
    color: #8ab4ff;
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
  .status, .error, .warning {
    margin: 16px 0;
    padding: 10px 14px;
    border-radius: 10px;
    font-size: 13px;
  }
  .status { background: #1a1d24; color: #9ca3af; }
  .error { background: #3a1f22; color: #ffb8b8; }
  .warning { background: #2a2418; color: #f0c674; }
  .hint-panel {
    margin-top: 32px;
    padding: 18px;
    background: #12151c;
    border: 1px solid #1f2330;
    border-radius: 12px;
    color: #c7cbd3;
    font-size: 13px;
  }
  .hint-panel p { margin: 0 0 8px; line-height: 1.6; }
  .hint-panel .small { font-size: 11px; color: #8a94a3; }
  .ext-breakdown {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 10px;
  }
  .ext-pill {
    font-size: 10px;
    padding: 2px 6px;
    border-radius: 6px;
    background: #1f2330;
    color: #8ab4ff;
  }

  /* file (name) results */
  .file-list {
    margin-top: 16px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .file-row {
    text-align: left;
    background: transparent;
    border: 0;
    border-radius: 6px;
    padding: 8px 10px;
    color: #e8e8ea;
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
  }
  .file-row:hover { background: #141822; }
  .file-row.selected { background: #1b2435; outline: 1px solid #4b7bff; }
  .file-name {
    display: flex;
    gap: 8px;
    align-items: center;
    flex: 1;
    min-width: 0;
  }
  .ext-chip {
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 4px;
    background: #2a2f3a;
    color: #8ab4ff;
    font-family: ui-monospace, Menlo, Consolas, monospace;
    white-space: nowrap;
  }
  .name-text {
    font-size: 13px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 500;
  }
  .file-meta {
    display: flex;
    gap: 10px;
    font-size: 11px;
    color: #6b7280;
    font-family: ui-monospace, Menlo, Consolas, monospace;
    flex-shrink: 0;
  }
  .file-parent {
    max-width: 260px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .file-size { min-width: 60px; text-align: right; }
  .file-date { min-width: 80px; }

  /* content / AI results */
  .answer {
    margin-top: 20px;
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
    margin-top: 20px;
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
  .card.selected {
    border-color: #4b7bff;
    background: #162035;
    box-shadow: 0 0 0 1px #4b7bff55;
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
