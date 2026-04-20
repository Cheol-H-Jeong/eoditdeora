# 어딨더라 (Eoditdeora)

> *"그 파일, 어딨더라?" — 에 답하는 유일한 방법*

완전 로컬에서 동작하는 개인 문서 지식베이스 데스크톱 앱. HWP, HWPX, PDF, DOC,
DOCX, XLSX, PPTX 등 **내 컴퓨터 안의 모든 문서**를 색인하고, 자연어 검색과
엄격한 근거 인용 기반 RAG Q&A를 제공합니다. 네트워크 전송 없음, 텔레메트리
없음.

- **타겟**: 공무원 및 문서 중심 한국어 지식노동자
- **플랫폼**: Windows 10/11 x64, Linux x64 (Ubuntu 22.04+, Fedora 39+)
- **하드웨어 권장**: AMD Ryzen AI Max+ 395 (VRAM 64GB 설정) 또는 동급
- **라이선스**: AGPL-3.0-or-later (코어), MIT (파서 플러그인)

## 빠른 시작

### 빌드된 설치파일 사용

[릴리즈](../../releases) 페이지에서 OS에 맞는 설치파일을 받습니다.
- Windows: `Eoditdeora-<ver>-x64.msi`
- Linux: `Eoditdeora-<ver>.AppImage`

설치 후 첫 실행 시 모델 다운로드 안내가 뜹니다. 오프라인 환경이면
[installers/linux/README.md](installers/linux/README.md)를 참조.

### 소스에서 빌드

```bash
# 1) Python 사이드카 설정
pip install -e ".[dev]"
pytest core/tests

# 2) UI 의존성
pnpm install

# 3) 데스크톱 번들
cd apps/shell && cargo tauri dev        # 개발
cd apps/shell && cargo tauri build      # 릴리즈 번들
```

## 아키텍처

```
┌────────── Eoditdeora.app ──────────┐
│ Tauri Rust shell                   │
│   ├─ Svelte 5 WebView UI           │
│   └─ JSON-RPC over stdio ──────┐   │
│                                ▼   │
│ Python sidecar (PyInstaller)       │
│   ├─ Collector (watchdog)          │
│   ├─ Parsers (hwp, hwpx, pdf, …)   │
│   ├─ Understanders (LLM)           │
│   ├─ Indexer (SQLite/Lance/Tantivy)│
│   └─ Retriever (BM25+Dense+Rerank) │
│                                │   │
│                                ▼ HTTP 127.0.0.1 only
│ llama.cpp servers                  │
│   ├─ Gemma 4 26B A4B IT (chat)     │
│   ├─ bge-m3 (embed)                │
│   └─ bge-reranker-v2-m3 (rerank)   │
└────────────────────────────────────┘
```

모든 프로세스간 통신은 localhost 한정. LAN / 인터넷 리스너 없음.

## 설계 원칙 (Locked)

| 번호 | 원칙 |
|---|---|
| **D1** | 공무원·지식노동자 타겟. HWP/HWPX/PDF/DOC 필수 |
| **D2** | 한컴 COM 사용 금지. 모든 파서 순수 Python, 크로스플랫폼 |
| **D3** | 원본 파일 복제 금지. 인덱스는 경로와 해시만 보관 |
| **D4** | 네트워크 없음. 모델 다운로드만 예외이며 별도 스크립트 실행 필요 |
| **D5** | 문서 전용 (L1). 화면 캡처·클립보드 기록 등 포함하지 않음 |
| **D6** | 1인 1서버. 멀티 유저 아님 |
| **D7** | 데스크톱 앱. 단일 설치파일 |
| **D8** | AGPL-3.0 코어. 커뮤니티 가능 |
| **D9** | 엄격 근거 (Strict provenance). 근거 없으면 "모름" |

자세한 배경은 [docs/DECISIONS.md](docs/DECISIONS.md).

## 파싱 전략

| 포맷 | 파서 | 비고 |
|---|---|---|
| HWPX | `hwpx_native` | ZIP + lxml. 본문·표 무손실 |
| HWP 5.x | `hwp_pyhwp` | 텍스트·단순 표. 복잡 레이아웃은 텍스트화 |
| HWP 3.x | 파일명 스텁 | 구버전 바이너리는 스텁만 |
| PDF | `pdf_pdfplumber` | 텍스트 레이어. OCR은 Understand 단계 |
| DOCX | `docx_python_docx` | 제목·문단·표·주석 |
| XLSX | `xlsx_openpyxl` | 시트별 500행 청킹 |
| PPTX | `pptx_python_pptx` | 슬라이드별 블록 |
| TXT/MD/CSV | 내장 | UTF-8 + CP949 sniff |

## 개발 기여

- 이슈: 버그·기능 제안 모두 GitHub Issues
- 코드: `core/tests`에 새 파서마다 최소 3개 단위 테스트 동반
- 코드 스타일: `ruff` / `mypy --strict`
- 커밋: conventional commits (`feat:`, `fix:`, `docs:`, …)

## 라이선스

AGPL-3.0-or-later. 자세한 내용은 [LICENSE](LICENSE).
