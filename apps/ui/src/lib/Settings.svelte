<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import {
    addRoot,
    autostartDisable,
    autostartEnable,
    autostartStatus,
    indexStatus,
    llmEnsure,
    modelsCancel,
    modelsDownload,
    modelsStatus,
    removeRoot,
    type AutostartStatus,
    type IndexStatus,
    type ModelSlot,
  } from "./rpc";

  let roots = $state<string[]>([]);
  let docCount = $state(0);
  let autostart = $state<AutostartStatus | null>(null);
  let models = $state<ModelSlot[]>([]);
  let newPath = $state("");
  let busy = $state<Record<string, boolean>>({});
  let timer: number | undefined;

  async function refresh() {
    try {
      const idx: IndexStatus = await indexStatus();
      roots = idx.roots;
      docCount = idx.index.doc_count;
      autostart = await autostartStatus();
      const m = await modelsStatus();
      models = m.slots;
    } catch (e) {
      console.warn(e);
    }
  }

  onMount(async () => {
    await refresh();
    timer = window.setInterval(refresh, 1500);
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

  async function onDownload(key: string) {
    busy = { ...busy, [key]: true };
    try {
      await modelsDownload(key);
      await refresh();
    } finally {
      busy = { ...busy, [key]: false };
    }
  }

  async function onCancel(key: string) {
    await modelsCancel(key);
    await refresh();
  }

  async function onStartLlm() {
    busy = { ...busy, llm: true };
    try {
      await llmEnsure();
      await refresh();
    } finally {
      busy = { ...busy, llm: false };
    }
  }

  function fmt(bytes: number): string {
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    let v = bytes;
    while (v >= 1024 && i < units.length - 1) {
      v /= 1024;
      i++;
    }
    return `${v.toFixed(v < 10 ? 1 : 0)} ${units[i]}`;
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
              title="인덱스에서 제거 (원본 파일은 그대로)"
            >제거</button>
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
    <h2>로컬 LLM 모델</h2>
    <p class="hint">답변 모드를 쓰려면 아래 3개 모두 다운로드. 다 받으면 자동으로 LLM이 기동됩니다.</p>
    {#each models as m}
      <div class="model" class:present={m.present} class:running={m.running}>
        <div class="row">
          <span class="name">{m.display}</span>
          <span class="badge">
            {#if m.present}설치됨{:else if m.running}다운로드 중{:else if m.error}오류{:else}미설치{/if}
          </span>
        </div>
        {#if m.running}
          <div class="bar">
            <div class="fill" style={`width:${m.percent.toFixed(1)}%`}></div>
          </div>
          <div class="row small">
            <span>{m.percent.toFixed(1)}%</span>
            <span>{fmt(m.downloaded_bytes)} / {fmt(m.total_bytes)}</span>
            <button class="cancel" onclick={() => onCancel(m.key)}>취소</button>
          </div>
        {:else if m.present}
          <p class="small muted" title={m.target_path}>{m.target_path.split('/').pop()}</p>
        {:else if m.error}
          <p class="small err">{m.error}</p>
          <button onclick={() => onDownload(m.key)} disabled={busy[m.key]}>다시 시도</button>
        {:else}
          <button
            onclick={() => onDownload(m.key)}
            disabled={busy[m.key] || !m.source_configured}
          >다운로드</button>
          {#if !m.source_configured}
            <p class="small muted">
              설정 파일에 다운로드 URL을 지정해야 합니다.
              (settings.toml의 model.gguf_urls.{m.key})
            </p>
          {/if}
        {/if}
      </div>
    {/each}
    <button class="ensure" onclick={onStartLlm} disabled={busy.llm}>
      지금 LLM 기동 시도
    </button>
  </section>
</aside>

<style>
  .sidebar {
    width: 320px;
    padding: 24px 18px;
    border-left: 1px solid #1f2330;
    background: #0e1117;
    color: #d7dae0;
    overflow-y: auto;
    height: 100vh;
  }
  section {
    margin-bottom: 24px;
  }
  h2 {
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    color: #8ab4ff;
    margin: 0 0 8px;
  }
  .hint {
    margin: 0 0 10px;
    font-size: 11px;
    color: #8a94a3;
    line-height: 1.5;
  }
  .hint.small,
  .small {
    font-size: 10.5px;
  }
  .muted {
    color: #6b7280;
  }
  .err {
    color: #ff9c9c;
  }
  ul.roots {
    list-style: none;
    padding: 0;
    margin: 0 0 8px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  ul.roots li {
    display: flex;
    gap: 8px;
    align-items: center;
    background: #141822;
    border: 1px solid #1e2230;
    border-radius: 8px;
    padding: 8px 10px;
  }
  .path {
    flex: 1;
    font-family: ui-monospace, Menlo, Consolas, monospace;
    font-size: 11px;
    color: #c7cbd3;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .remove {
    font-size: 11px;
    background: transparent;
    border: 1px solid #2a2f3a;
    color: #c7cbd3;
    border-radius: 6px;
    padding: 3px 8px;
    cursor: pointer;
  }
  .remove:hover {
    border-color: #ff9c9c;
    color: #ff9c9c;
  }
  .empty {
    font-size: 12px;
    color: #6b7280;
    margin: 0 0 10px;
  }
  .add {
    display: flex;
    gap: 6px;
    margin-top: 4px;
  }
  .add input {
    flex: 1;
    background: #0f131b;
    border: 1px solid #1f2330;
    border-radius: 6px;
    color: #e8e8ea;
    font-size: 12px;
    padding: 6px 8px;
    outline: none;
  }
  .add button,
  .model button,
  .ensure {
    background: #4b7bff;
    color: #fff;
    border: 0;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
    cursor: pointer;
  }
  .add button:disabled,
  .model button:disabled,
  .ensure:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .ensure {
    width: 100%;
    margin-top: 6px;
    background: #2a2f3a;
  }
  .stat {
    margin: 6px 0 0;
    font-size: 11px;
    color: #8a94a3;
  }
  .toggle {
    display: flex;
    gap: 8px;
    align-items: center;
    font-size: 12px;
    cursor: pointer;
  }
  .model {
    background: #141822;
    border: 1px solid #1e2230;
    border-radius: 8px;
    padding: 10px 12px;
    margin-bottom: 8px;
  }
  .model.present {
    border-color: #0f4f2d;
  }
  .model.running {
    border-color: #4b7bff;
  }
  .row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 6px;
    margin-bottom: 4px;
  }
  .name {
    font-size: 12px;
    font-weight: 600;
  }
  .badge {
    font-size: 10px;
    padding: 2px 6px;
    border-radius: 999px;
    background: #1f2330;
    color: #a0a6b0;
  }
  .bar {
    height: 4px;
    background: #1f2330;
    border-radius: 2px;
    margin: 4px 0 6px;
    overflow: hidden;
  }
  .fill {
    height: 100%;
    background: #4b7bff;
    transition: width 200ms linear;
  }
  .cancel {
    background: transparent;
    border: 1px solid #2a2f3a;
    color: #a0a6b0;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 10.5px;
    cursor: pointer;
  }
</style>
