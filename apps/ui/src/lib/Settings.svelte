<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import {
    addRoot,
    autostartDisable,
    autostartEnable,
    autostartStatus,
    endpointsDiscover,
    endpointsHealth,
    endpointsTest,
    endpointsUpdate,
    getSettings,
    indexStatus,
    removeRoot,
    type AutostartStatus,
    type Endpoint,
    type EndpointHealth,
    type IndexStatus,
    type ProbeResult,
    type Role,
  } from "./rpc";

  const ROLE_LABELS: Record<Role, string> = {
    llm: "LLM (답변용)",
    embed: "임베딩 (의미 검색용)",
    rerank: "리랭커 (정렬용)",
  };

  let roots = $state<string[]>([]);
  let docCount = $state(0);
  let autostart = $state<AutostartStatus | null>(null);

  let endpoints = $state<Record<Role, Endpoint>>({
    llm: { base_url: "", model_id: "", api_key: "", api_kind: "openai" },
    embed: { base_url: "", model_id: "", api_key: "", api_kind: "openai" },
    rerank: { base_url: "", model_id: "", api_key: "", api_kind: "openai" },
  });
  let health = $state<Record<Role, EndpointHealth | null>>({ llm: null, embed: null, rerank: null });
  let discovered = $state<ProbeResult[]>([]);
  let discovering = $state(false);

  let newPath = $state("");
  let busy = $state<Record<string, boolean>>({});
  let timer: number | undefined;

  async function refresh() {
    try {
      const idx: IndexStatus = await indexStatus();
      roots = idx.roots;
      docCount = idx.index.doc_count;
      autostart = await autostartStatus();
      const s = await getSettings();
      endpoints = {
        llm: s.model.llm,
        embed: s.model.embed,
        rerank: s.model.rerank,
      };
      const h = await endpointsHealth();
      health = h.roles;
    } catch (e) {
      console.warn(e);
    }
  }

  onMount(async () => {
    await refresh();
    timer = window.setInterval(refresh, 3000);
  });

  onDestroy(() => {
    if (timer !== undefined) clearInterval(timer);
  });

  async function onAdd() {
    const p = newPath.trim();
    if (!p) return;
    busy = { ...busy, add: true };
    try {
      const result = await addRoot(p);
      if (result.ok) newPath = "";
      await refresh();
    } finally {
      busy = { ...busy, add: false };
    }
  }

  async function onRemove(path: string) {
    busy = { ...busy, [path]: true };
    try {
      await removeRoot(path);
      await refresh();
    } finally {
      busy = { ...busy, [path]: false };
    }
  }

  async function onToggleAutostart() {
    if (!autostart) return;
    busy = { ...busy, autostart: true };
    try {
      if (autostart.enabled) await autostartDisable();
      else await autostartEnable();
      await refresh();
    } finally {
      busy = { ...busy, autostart: false };
    }
  }

  async function onDiscover() {
    discovering = true;
    try {
      const r = await endpointsDiscover();
      discovered = r.endpoints;
    } finally {
      discovering = false;
    }
  }

  async function saveEndpoint(role: Role) {
    busy = { ...busy, [`save:${role}`]: true };
    try {
      await endpointsUpdate(role, endpoints[role]);
      await refresh();
    } finally {
      busy = { ...busy, [`save:${role}`]: false };
    }
  }

  async function clearEndpoint(role: Role) {
    endpoints[role] = { base_url: "", model_id: "", api_key: "", api_kind: "openai" };
    await saveEndpoint(role);
  }

  async function testEndpoint(role: Role) {
    const e = endpoints[role];
    if (!e.base_url) return;
    busy = { ...busy, [`test:${role}`]: true };
    try {
      const p = await endpointsTest(e.base_url, e.api_key, e.api_kind);
      health[role] = {
        ...(health[role] ?? { configured: true, base_url: e.base_url, model_id: e.model_id, active_model: "" }),
        reachable: p.reachable,
        error: p.error,
        models: p.models,
      };
    } finally {
      busy = { ...busy, [`test:${role}`]: false };
    }
  }

  function pickDiscovered(role: Role, p: ProbeResult, modelId = "") {
    endpoints[role] = {
      base_url: p.base_url,
      model_id: modelId || p.models[0] || "",
      api_key: endpoints[role].api_key,
      api_kind: p.api_kind,
    };
  }
</script>

<aside class="sidebar">
  <section>
    <h2>감시 폴더</h2>
    <p class="hint">이 폴더 안의 모든 파일을 자동 색인합니다. 새 파일은 실시간 반영.</p>
    {#if roots.length === 0}
      <p class="empty">아직 등록된 폴더가 없습니다.</p>
    {:else}
      <ul class="roots">
        {#each roots as r}
          <li>
            <span class="path" title={r}>{r}</span>
            <button class="remove" onclick={() => onRemove(r)} disabled={busy[r]}>제거</button>
          </li>
        {/each}
      </ul>
    {/if}
    <div class="add">
      <input
        type="text"
        bind:value={newPath}
        placeholder="/home/..../Documents"
        onkeydown={(e) => e.key === 'Enter' && onAdd()}
      />
      <button onclick={onAdd} disabled={busy.add || !newPath.trim()}>추가</button>
    </div>
    <p class="stat">색인된 문서 <strong>{docCount.toLocaleString()}</strong>개</p>
  </section>

  <section>
    <h2>자동 시작</h2>
    {#if autostart}
      <label class="toggle">
        <input
          type="checkbox"
          checked={autostart.enabled}
          onchange={onToggleAutostart}
          disabled={busy.autostart}
        />
        <span>PC 시작 시 어딨더라 자동 실행</span>
      </label>
      <p class="hint small">{autostart.platform} · {autostart.path ?? autostart.value ?? ""}</p>
    {/if}
  </section>

  <section>
    <h2>LLM 엔드포인트</h2>
    <p class="hint">
      이 앱은 모델 가중치를 직접 올리지 않습니다. 이미 서빙 중인 로컬
      엔드포인트를 고르면 연결만 합니다.
    </p>

    <div class="discover-row">
      <button onclick={onDiscover} disabled={discovering}>
        {discovering ? "탐색 중..." : "자동 탐색"}
      </button>
      <span class="hint small">127.0.0.1 의 주요 포트 조회</span>
    </div>

    {#if discovered.length}
      <ul class="discovered">
        {#each discovered as d}
          <li>
            <div class="row">
              <span class="url">{d.base_url}</span>
              <span class="muted small">{d.models.length}개 모델</span>
            </div>
            <div class="models">
              {#each d.models as m}
                <span class="modelchip" title={m}>{m}</span>
              {/each}
            </div>
            <div class="row">
              {#each ["llm", "embed", "rerank"] as r}
                <button
                  class="pick"
                  onclick={() => pickDiscovered(r as Role, d, d.models[0] ?? "")}
                >{ROLE_LABELS[r as Role]}에 지정</button>
              {/each}
            </div>
          </li>
        {/each}
      </ul>
    {/if}

    {#each ["llm", "embed", "rerank"] as role}
      {@const r = role as Role}
      <div class="slot" class:ok={health[r]?.reachable}>
        <div class="row">
          <span class="name">{ROLE_LABELS[r]}</span>
          <span class="badge">
            {#if !endpoints[r].base_url}
              미설정
            {:else if health[r]?.reachable}
              연결됨
            {:else if health[r]?.error}
              오류
            {:else}
              확인 중
            {/if}
          </span>
        </div>
        <input
          class="url-input"
          type="text"
          placeholder="base URL (http://127.0.0.1:8080)"
          bind:value={endpoints[r].base_url}
        />
        <div class="row small">
          {#if health[r]?.models?.length}
            <select bind:value={endpoints[r].model_id}>
              <option value="">(서버 기본)</option>
              {#each health[r].models as m}
                <option value={m}>{m}</option>
              {/each}
            </select>
          {:else}
            <input
              class="model-input"
              type="text"
              placeholder="model id (선택)"
              bind:value={endpoints[r].model_id}
            />
          {/if}
          <select bind:value={endpoints[r].api_kind}>
            <option value="openai">OpenAI 호환</option>
            <option value="ollama">Ollama 네이티브</option>
          </select>
        </div>
        <input
          class="key-input"
          type="password"
          placeholder="API key (선택)"
          bind:value={endpoints[r].api_key}
        />
        {#if health[r]?.error}
          <p class="small err">{health[r].error}</p>
        {/if}
        <div class="row small actions">
          <button onclick={() => testEndpoint(r)} disabled={busy[`test:${r}`] || !endpoints[r].base_url}>
            테스트
          </button>
          <button onclick={() => saveEndpoint(r)} disabled={busy[`save:${r}`]}>
            저장
          </button>
          <button class="cancel" onclick={() => clearEndpoint(r)}>초기화</button>
        </div>
      </div>
    {/each}
  </section>
</aside>

<style>
  .sidebar {
    width: 340px;
    padding: 24px 18px;
    border-left: 1px solid #1f2330;
    background: #0e1117;
    color: #d7dae0;
    overflow-y: auto;
    height: 100vh;
  }
  section { margin-bottom: 24px; }
  h2 {
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    color: #8ab4ff;
    margin: 0 0 8px;
  }
  .hint { margin: 0 0 10px; font-size: 11px; color: #8a94a3; line-height: 1.5; }
  .hint.small, .small { font-size: 10.5px; }
  .muted { color: #6b7280; }
  .err { color: #ff9c9c; }
  ul.roots {
    list-style: none; padding: 0; margin: 0 0 8px;
    display: flex; flex-direction: column; gap: 6px;
  }
  ul.roots li {
    display: flex; gap: 8px; align-items: center;
    background: #141822; border: 1px solid #1e2230;
    border-radius: 8px; padding: 8px 10px;
  }
  .path {
    flex: 1; font-family: ui-monospace, Menlo, Consolas, monospace;
    font-size: 11px; color: #c7cbd3;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .remove {
    font-size: 11px; background: transparent; border: 1px solid #2a2f3a;
    color: #c7cbd3; border-radius: 6px; padding: 3px 8px; cursor: pointer;
  }
  .empty { font-size: 12px; color: #6b7280; margin: 0 0 10px; }
  .add { display: flex; gap: 6px; margin-top: 4px; }
  input, select {
    background: #0f131b; border: 1px solid #1f2330; border-radius: 6px;
    color: #e8e8ea; font-size: 12px; padding: 6px 8px; outline: none;
    width: 100%;
  }
  .add input { flex: 1; }
  button {
    background: #4b7bff; color: #fff; border: 0; border-radius: 6px;
    padding: 6px 10px; font-size: 12px; cursor: pointer;
  }
  button:disabled { opacity: 0.4; cursor: not-allowed; }
  button.cancel { background: #2a2f3a; color: #a0a6b0; }
  .stat { margin: 6px 0 0; font-size: 11px; color: #8a94a3; }
  .toggle { display: flex; gap: 8px; align-items: center; font-size: 12px; cursor: pointer; }
  .discover-row {
    display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
  }
  ul.discovered {
    list-style: none; padding: 0; margin: 0 0 12px;
    display: flex; flex-direction: column; gap: 8px;
  }
  ul.discovered li {
    background: #141822; border: 1px solid #1e2230;
    border-radius: 8px; padding: 10px;
  }
  .url { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; }
  .models { display: flex; gap: 4px; flex-wrap: wrap; margin: 6px 0; }
  .modelchip {
    font-size: 10px; padding: 2px 6px; border-radius: 6px;
    background: #1f2330; color: #a0a6b0;
    max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .pick {
    font-size: 10.5px; background: #222731; color: #8ab4ff; padding: 3px 6px;
  }
  .slot {
    background: #141822; border: 1px solid #1e2230;
    border-radius: 8px; padding: 10px 12px; margin-bottom: 8px;
    display: flex; flex-direction: column; gap: 6px;
  }
  .slot.ok { border-color: #0f4f2d; }
  .row { display: flex; gap: 6px; align-items: center; justify-content: space-between; }
  .row.small > * { flex: 1; min-width: 0; }
  .name { font-size: 12px; font-weight: 600; }
  .badge {
    font-size: 10px; padding: 2px 6px; border-radius: 999px;
    background: #1f2330; color: #a0a6b0;
  }
  .actions { justify-content: flex-start; }
</style>
