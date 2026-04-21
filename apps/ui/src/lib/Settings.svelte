<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import {
    addRoot,
    autostartDisable,
    autostartEnable,
    autostartStatus,
    docpathsAddDefaults,
    docpathsDiscover,
    endpointsAutoConnect,
    endpointsDiscover,
    endpointsHealth,
    endpointsPresets,
    endpointsTest,
    endpointsUpdate,
    filesStats,
    getSettings,
    indexRescan,
    indexStatus,
    removeRoot,
    updateSettings,
    type AutoConnectResult,
    type AutostartStatus,
    type DocPathCandidate,
    type Endpoint,
    type EndpointHealth,
    type FastStats,
    type IndexStatus,
    type Preset,
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
  let autoConnectMsg = $state<string>("");
  let autoConnecting = $state(false);
  let presets = $state<Preset[]>([]);
  let presetRole = $state<Role>("llm");
  let activePresetKey = $state<string | null>(null);

  let newPath = $state("");
  let busy = $state<Record<string, boolean>>({});
  let timer: number | undefined;
  let docCandidates = $state<DocPathCandidate[]>([]);
  let fastStats = $state<FastStats | null>(null);
  let rescanMsg = $state<string>("");

  // Extension picker state.
  const DEFAULT_EXTS: readonly string[] = [
    ".hwp", ".hwpx",
    ".pdf",
    ".doc", ".docx",
    ".ppt", ".pptx",
    ".xls", ".xlsx",
    ".txt", ".md", ".markdown",
    ".rtf", ".odt", ".ods", ".odp",
  ];
  let selectedExtensions = $state<string[]>([]);
  let newExt = $state("");
  let extSaveMsg = $state<string>("");

  function extOptions(): string[] {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const e of DEFAULT_EXTS) {
      if (!seen.has(e)) { seen.add(e); out.push(e); }
    }
    for (const e of selectedExtensions) {
      if (!seen.has(e)) { seen.add(e); out.push(e); }
    }
    for (const b of fastStats?.by_ext ?? []) {
      const key = b.ext || "(none)";
      if (!seen.has(key) && key !== "(none)") { seen.add(key); out.push(key); }
    }
    return out.sort();
  }

  function extCountFor(ext: string): number {
    return fastStats?.by_ext.find((b) => b.ext === ext)?.count ?? 0;
  }

  async function saveExtensions(next: string[]) {
    busy = { ...busy, extsave: true };
    extSaveMsg = "저장 중...";
    try {
      const s = await getSettings();
      s.index.extensions = Array.from(new Set(next)).sort();
      await updateSettings(s);
      selectedExtensions = s.index.extensions;
      extSaveMsg = `${selectedExtensions.length}개 확장자 저장됨. 새 확장자는 '재탐색'으로 반영하세요.`;
    } catch (e) {
      extSaveMsg = String(e);
    } finally {
      busy = { ...busy, extsave: false };
    }
  }

  async function onToggleExt(ext: string, on: boolean) {
    const next = on
      ? [...selectedExtensions, ext]
      : selectedExtensions.filter((e) => e !== ext);
    await saveExtensions(next);
  }

  async function onAddExt() {
    let e = newExt.trim().toLowerCase();
    if (!e) return;
    if (!e.startsWith(".")) e = "." + e;
    if (selectedExtensions.includes(e)) {
      extSaveMsg = "이미 목록에 있습니다.";
      newExt = "";
      return;
    }
    await saveExtensions([...selectedExtensions, e]);
    newExt = "";
  }

  async function onResetExts() {
    await saveExtensions([...DEFAULT_EXTS]);
  }

  // Periodic refresh must NOT touch `endpoints` — the user is often
  // mid-edit on the base URL / API key inputs, and pulling the stored
  // (possibly empty) values from the backend every 3s would wipe the
  // characters they just typed. Endpoint form state is owned by the
  // UI and only reconciled on explicit events (mount, save, auto-
  // connect, preset pick, discovery pick).
  async function refreshRuntime() {
    try {
      const idx: IndexStatus = await indexStatus();
      roots = idx.roots;
      docCount = idx.index.doc_count;
      autostart = await autostartStatus();
      const h = await endpointsHealth();
      health = h.roles;
      try {
        fastStats = await filesStats();
      } catch {
        fastStats = null;
      }
    } catch (e) {
      console.warn(e);
    }
  }

  async function refreshDocCandidates() {
    try {
      const d = await docpathsDiscover();
      docCandidates = d.candidates;
    } catch (e) {
      console.warn(e);
    }
  }

  async function onAddDefaults() {
    busy = { ...busy, addDefaults: true };
    try {
      const r = await docpathsAddDefaults();
      rescanMsg = r.added.length
        ? `${r.added.length}개 폴더를 추가했습니다.`
        : "추가할 새 폴더가 없습니다.";
      await refreshRuntime();
    } catch (e) {
      rescanMsg = String(e);
    } finally {
      busy = { ...busy, addDefaults: false };
    }
  }

  async function onRescan() {
    busy = { ...busy, rescan: true };
    rescanMsg = "재탐색 중...";
    try {
      const r = await indexRescan();
      rescanMsg = `재탐색 완료 — ${r.totals.roots}개 폴더, ${r.totals.upserted.toLocaleString()}개 파일 색인.`;
      await refreshRuntime();
    } catch (e) {
      rescanMsg = String(e);
    } finally {
      busy = { ...busy, rescan: false };
    }
  }

  async function refreshEndpoints() {
    try {
      const s = await getSettings();
      endpoints = {
        llm: s.model.llm,
        embed: s.model.embed,
        rerank: s.model.rerank,
      };
      selectedExtensions = s.index.extensions ?? [];
    } catch (e) {
      console.warn(e);
    }
  }

  onMount(async () => {
    await refreshEndpoints();
    await refreshRuntime();
    await refreshDocCandidates();
    try {
      const p = await endpointsPresets();
      presets = p.presets;
    } catch (e) {
      console.warn(e);
    }
    timer = window.setInterval(refreshRuntime, 3000);
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
      await refreshRuntime();
    } finally {
      busy = { ...busy, add: false };
    }
  }

  async function onRemove(path: string) {
    busy = { ...busy, [path]: true };
    try {
      await removeRoot(path);
      await refreshRuntime();
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
      await refreshRuntime();
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

  async function onAutoConnect(force: boolean) {
    autoConnecting = true;
    autoConnectMsg = "";
    try {
      const r: AutoConnectResult = await endpointsAutoConnect(force);
      const assigned = Object.keys(r.assigned);
      if (assigned.length === 0) {
        autoConnectMsg = r.probed === 0
          ? "127.0.0.1 에 서빙 중인 OpenAI 호환 엔드포인트가 없습니다."
          : "이미 모든 역할이 설정되어 있어 변경된 건 없습니다.";
      } else {
        autoConnectMsg = `자동 연결됨: ${assigned.join(", ")}`;
      }
      await refreshEndpoints();
      await refreshRuntime();
    } catch (e) {
      autoConnectMsg = String(e);
    } finally {
      autoConnecting = false;
    }
  }

  function isRemote(url: string): boolean {
    try {
      const u = new URL(url);
      const h = (u.hostname || "").toLowerCase();
      return h !== "" && !["127.0.0.1", "localhost", "::1", "0.0.0.0"].includes(h);
    } catch {
      return false;
    }
  }

  async function saveEndpoint(role: Role) {
    const e = endpoints[role];
    if (isRemote(e.base_url)) {
      const ok = window.confirm(
        "⚠️ 외부 원격 엔드포인트입니다.\n\n" +
          `${e.base_url} 로 문서 내용이 전송됩니다.\n` +
          "공무원·감사 대상 문서가 있다면 진행하지 마세요.\n\n" +
          "저장할까요?"
      );
      if (!ok) return;
    }
    busy = { ...busy, [`save:${role}`]: true };
    try {
      await endpointsUpdate(role, e);
      // The server may normalize (e.g. strip trailing /) what we sent.
      // Pull it back so the form matches truth, then refresh health.
      await refreshEndpoints();
      await refreshRuntime();
    } finally {
      busy = { ...busy, [`save:${role}`]: false };
    }
  }

  function applyPreset(preset: Preset, role: Role) {
    activePresetKey = preset.key;
    endpoints[role] = {
      base_url: preset.base_url,
      model_id: preset.default_models[0] ?? "",
      api_key: endpoints[role].api_key,
      api_kind: preset.api_kind,
    };
    presetRole = role;
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
        ...(health[role] ?? {
          configured: true,
          base_url: e.base_url,
          model_id: e.model_id,
          active_model: "",
          api_kind: e.api_kind,
          remote: false,
        }),
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
            <button
              class="remove"
              onclick={() => onRemove(r)}
              disabled={busy[r]}
              title="이 폴더를 감시 목록에서 제거"
              aria-label="{r} 제거"
            >{busy[r] ? "…" : "✕"}</button>
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
    <div class="discover-row">
      <button onclick={onAddDefaults} disabled={busy.addDefaults}>
        주요 문서 폴더 자동 추가
      </button>
      <button class="cancel" onclick={onRescan} disabled={busy.rescan}>
        재탐색
      </button>
    </div>
    {#if rescanMsg}
      <p class="hint small">{rescanMsg}</p>
    {/if}
    {#if docCandidates.length}
      <details class="disc-det">
        <summary>감지된 주요 폴더 ({docCandidates.filter(c => c.exists).length}개 존재)</summary>
        <ul class="cand-list">
          {#each docCandidates as c}
            <li class:missing={!c.exists}>
              <span class="cand-name">{c.display_name}</span>
              <span class="cand-path" title={c.path}>{c.path}</span>
              {#if c.has_documents}
                <span class="cand-badge ok">문서 있음</span>
              {:else if c.exists}
                <span class="cand-badge">비어있음</span>
              {:else}
                <span class="cand-badge muted">없음</span>
              {/if}
            </li>
          {/each}
        </ul>
      </details>
    {/if}
    <p class="stat">
      문서 본문 색인 <strong>{docCount.toLocaleString()}</strong>개
      {#if fastStats}
        · 파일명 색인 <strong>{fastStats.total.toLocaleString()}</strong>개
      {/if}
    </p>
  </section>

  <section>
    <h2>색인 대상 확장자</h2>
    <p class="hint">
      체크된 확장자만 실시간 색인합니다. 변경 시 즉시 저장되며, 추가한
      확장자는 재탐색 시 반영됩니다.
    </p>
    <div class="ext-grid">
      {#each extOptions() as ext}
        <label class="ext-check">
          <input
            type="checkbox"
            checked={selectedExtensions.includes(ext)}
            onchange={(e) => onToggleExt(ext, (e.target as HTMLInputElement).checked)}
            disabled={busy.extsave}
          />
          <span class="ext-label">{ext}</span>
          {#if extCountFor(ext) > 0}
            <span class="ext-count">{extCountFor(ext).toLocaleString()}</span>
          {/if}
        </label>
      {/each}
    </div>
    <div class="ext-addrow">
      <input
        type="text"
        bind:value={newExt}
        placeholder=".epub"
        onkeydown={(e) => e.key === 'Enter' && onAddExt()}
      />
      <button onclick={onAddExt} disabled={busy.extsave || !newExt.trim()}>확장자 추가</button>
      <button class="cancel" onclick={onResetExts} disabled={busy.extsave}>기본값 복원</button>
    </div>
    {#if extSaveMsg}
      <p class="hint small">{extSaveMsg}</p>
    {/if}
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

    <div class="subhead">로컬 (127.0.0.1)</div>
    <div class="discover-row">
      <button onclick={() => onAutoConnect(false)} disabled={autoConnecting}>
        {autoConnecting ? "연결 중..." : "자동 연결"}
      </button>
      <button
        class="cancel"
        onclick={() => onAutoConnect(true)}
        disabled={autoConnecting}
        title="이미 지정된 역할도 무시하고 다시 할당"
      >강제 재연결</button>
    </div>
    {#if autoConnectMsg}
      <p class="hint small">{autoConnectMsg}</p>
    {/if}
    <div class="discover-row">
      <button class="cancel" onclick={onDiscover} disabled={discovering}>
        {discovering ? "탐색 중..." : "서버 목록만 보기"}
      </button>
      <span class="hint small">수동 선택용</span>
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

    {#if presets.length}
      <div class="subhead">외부 API / 원격 서버</div>
      <p class="hint small">
        로컬에 서빙 중인 모델이 없을 때 사용합니다. 문서 내용이 해당 서버로
        전송된다는 점에 주의하세요.
      </p>
      <div class="preset-grid">
        {#each presets as pr}
          <button
            class="preset"
            class:active={activePresetKey === pr.key}
            onclick={() => applyPreset(pr, presetRole)}
            title={pr.notes}
          >
            <span class="preset-name">{pr.display}</span>
            {#if pr.remote}<span class="rbadge">원격</span>{/if}
          </button>
        {/each}
      </div>
      <div class="row small">
        <span class="hint small">역할 선택:</span>
        {#each ["llm", "embed", "rerank"] as role}
          {@const r = role as Role}
          <button
            class="pick"
            class:active={presetRole === r}
            onclick={() => (presetRole = r)}
          >{ROLE_LABELS[r]}</button>
        {/each}
      </div>
    {/if}

    {#each ["llm", "embed", "rerank"] as role}
      {@const r = role as Role}
      <div class="slot" class:ok={health[r]?.reachable} class:remote={health[r]?.remote}>
        <div class="row">
          <span class="name">{ROLE_LABELS[r]}</span>
          <span class="badges">
            {#if health[r]?.remote}<span class="rbadge">원격</span>{/if}
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
  .ext-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
    gap: 4px 8px;
    margin-bottom: 10px;
  }
  .ext-check {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 6px;
    border-radius: 6px;
    font-size: 12px;
    cursor: pointer;
    color: #c7cbd3;
  }
  .ext-check:hover { background: #181c26; }
  .ext-check input { accent-color: #4b7bff; }
  .ext-label { font-family: ui-monospace, Menlo, Consolas, monospace; }
  .ext-count {
    margin-left: auto;
    font-size: 10px;
    color: #6b7280;
  }
  .ext-addrow {
    display: flex;
    gap: 6px;
    margin-top: 4px;
  }
  .ext-addrow input {
    flex: 1;
    background: #12151c;
    border: 1px solid #2a2f3a;
    color: #e8e8ea;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 12px;
  }
  .ext-addrow button {
    background: #4b7bff;
    border: 0;
    color: white;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 12px;
    cursor: pointer;
  }
  .ext-addrow button.cancel {
    background: transparent;
    border: 1px solid #2a2f3a;
    color: #a0a6b0;
  }
  .ext-addrow button:disabled { opacity: 0.5; cursor: not-allowed; }
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
  .slot.remote { border-color: #8a3b2b; }
  .subhead {
    margin-top: 6px;
    font-size: 10.5px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #6b7280;
    margin-bottom: 6px;
  }
  .preset-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
    margin-bottom: 8px;
  }
  .preset {
    background: #141822;
    border: 1px solid #1e2230;
    color: #c7cbd3;
    padding: 8px 10px;
    border-radius: 6px;
    font-size: 11px;
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    gap: 6px;
    align-items: center;
    text-align: left;
  }
  .preset:hover { border-color: #4b7bff; }
  .preset.active { border-color: #4b7bff; background: #1a1f2e; }
  .preset-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .rbadge {
    font-size: 9.5px;
    padding: 1px 5px;
    border-radius: 6px;
    background: #3a1f22;
    color: #ff9c9c;
    border: 1px solid #5a2e33;
  }
  .badges { display: flex; gap: 4px; align-items: center; }
  .pick.active { background: #4b7bff; color: #fff; }
  .row { display: flex; gap: 6px; align-items: center; justify-content: space-between; }
  .row.small > * { flex: 1; min-width: 0; }
  .name { font-size: 12px; font-weight: 600; }
  .badge {
    font-size: 10px; padding: 2px 6px; border-radius: 999px;
    background: #1f2330; color: #a0a6b0;
  }
  .actions { justify-content: flex-start; }
  .disc-det {
    margin: 6px 0 10px;
    background: #12151c;
    border: 1px solid #1e2230;
    border-radius: 8px;
    padding: 6px 10px;
  }
  .disc-det summary {
    font-size: 11px;
    color: #8ab4ff;
    cursor: pointer;
    outline: none;
  }
  .cand-list {
    list-style: none;
    padding: 0;
    margin: 8px 0 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .cand-list li {
    display: flex;
    gap: 6px;
    align-items: center;
    font-size: 10.5px;
  }
  .cand-list li.missing { opacity: 0.5; }
  .cand-name {
    flex: 0 0 90px;
    color: #c7cbd3;
    font-weight: 600;
  }
  .cand-path {
    flex: 1;
    color: #6b7280;
    font-family: ui-monospace, Menlo, Consolas, monospace;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .cand-badge {
    font-size: 9.5px;
    padding: 1px 5px;
    border-radius: 4px;
    background: #1f2330;
    color: #a0a6b0;
  }
  .cand-badge.ok { background: #0f4f2d; color: #7be3a7; }
  .cand-badge.muted { background: #2a2f3a; color: #6b7280; }
</style>
