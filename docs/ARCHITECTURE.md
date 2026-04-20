# 아키텍처

## 프로세스 토폴로지

```
┌─────────────────────────────────────────────────────────────┐
│  Tauri Rust 셸 (메인 프로세스)                                │
│  ─ 윈도우 / 트레이 / 전역 단축키                                │
│  ─ Python 사이드카 자식 프로세스 소유                            │
│  ─ 프론트엔드 ↔ 백엔드 브리지                                   │
└──┬──────────────────────────────────────────────────────────┘
   │ stdin/stdout (JSON-RPC 2.0 over LSP framing)
┌──▼──────────────────────────────────────────────────────────┐
│  Python 사이드카 (eoditdeora-core, PyInstaller 단일 바이너리)  │
│  ─ 파일 감시 (watchdog)                                       │
│  ─ 파서 파이프라인                                             │
│  ─ Understand 작업 큐                                         │
│  ─ SQLite / LanceDB / Tantivy 기록                            │
│  ─ llama.cpp HTTP 클라이언트                                  │
└──┬──────────────────────────────────────────────────────────┘
   │ HTTP 127.0.0.1 (three ports)
┌──▼──────────────────────────────────────────────────────────┐
│  llama.cpp llama-server × 3 (Vulkan GPU 백엔드)                │
│  ─ :17651  Gemma 4 26B A4B IT (chat)                         │
│  ─ :17652  bge-m3               (embed)                       │
│  ─ :17653  bge-reranker-v2-m3  (rerank)                       │
└─────────────────────────────────────────────────────────────┘
```

모든 포트는 127.0.0.1에 바인딩. 외부 리스너 없음. 방화벽 예외 불필요.

## 디렉토리 구조

```
eoditdeora/
├─ apps/
│  ├─ shell/   Tauri Rust 프로젝트 (main.rs, rpc.rs)
│  └─ ui/      SvelteKit WebView
├─ core/
│  └─ eoditdeora/
│     ├─ api/            JSON-RPC 서버
│     ├─ collector/      파일 감시 + ignore 규칙
│     ├─ parsers/        포맷별 파서 (플러그인)
│     ├─ understanders/  LLM 이해 (분류·요약·엔티티)
│     ├─ indexer/        chunker, pipeline
│     ├─ storage/        meta(SQLite) / vectors(Lance) / fts(Tantivy)
│     ├─ retriever/      hybrid, RAG
│     ├─ runtime/        llama.cpp 관리 + 클라이언트
│     ├─ config/         경로·설정
│     └─ utils/          로깅·해싱·경로
├─ runtimes/llama_cpp/   빌드/실행 보조 (바이너리는 커밋 안 함)
├─ installers/           OS별 설치 스크립트
├─ schemas/              JSON Schema 계약
├─ scripts/              개발·배포 스크립트
└─ docs/
```

## 데이터 흐름 (파일 생성 이벤트 기준)

```
Watcher event → CollectedFile
  → pipeline.index_file()
    → hash (sha256, xxhash)
    → parser_registry.parse_file()
       └─ ParsedDoc (공통 스키마)
    → chunker.chunk_parsed()
       └─ [Chunk]
    → MetaStore.upsert_document()
    → MetaStore.replace_chunks()
    → FtsStore.upsert()              ← Kiwi 토큰화 후 Tantivy
    → MetaStore.enqueue_job("embed") ← 비동기 워커가 LanceDB에 기록
    → MetaStore.enqueue_job("understand") ← LLM 분류/요약/엔티티
```

사용자가 트리거한 검색은 embed 잡이 아직 끝나지 않아도 즉시 실행 — BM25
단독 검색으로 동작하다가, 벡터가 채워지면 하이브리드로 자연 승격됩니다.

## 저장소 파일 배치

`AppPaths.data` (OS별 위치) 아래:

```
eoditdeora/
├─ config/
│  └─ settings.toml
├─ data/
│  ├─ index/
│  │  ├─ meta.sqlite3
│  │  ├─ lancedb/         (chunks 테이블)
│  │  └─ tantivy/
│  ├─ models/             (다운로드된 GGUF)
│  └─ runtime/bin/        (번들 llama-server 바이너리)
├─ cache/
│  └─ thumbnails/
└─ logs/
   └─ eoditdeora.log      (rotating, 10MB × 5)
```

`EODITDEORA_HOME` 환경변수로 루트 재지정 가능. 모든 테스트가 이것으로
격리됩니다.

## 스레드 모델

- 메인 (Rust): Tauri 이벤트 루프
- sidecar stdio reader: tokio 태스크 하나
- Python 사이드카: asyncio 이벤트 루프
- 파일 감시: watchdog가 자체 OS 쓰레드 사용, 이벤트는 queue로 직렬화
- LLM 호출: 현재는 동기 (httpx.Client). 백프레셔는 큐 깊이로 흡수.

## 공개 RPC 계약

현재 제공 메서드 (see `core/eoditdeora/api/methods.py`):

| 메서드 | 입력 | 반환 |
|---|---|---|
| `ping` | — | `{ok, version}` |
| `settings.get` | — | `Settings` |
| `settings.update` | `Settings` | `Settings` |
| `index.add_root` | `{path}` | `{ok, path}` |
| `index.remove_root` | `{path}` | `{ok, removed}` |
| `index.status` | — | `{roots, index}` |
| `search` | `{query, top_k?, mode?}` | `{query, results, answer?}` |
| `forget` | `{doc_ids, paths, entities}` | `{ok, removed}` |
