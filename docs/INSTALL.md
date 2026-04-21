# 설치 및 실행

어딨더라는 **단일 설치파일** 로 배포됩니다. 플랫폼에 맞는 하나만 받으면
Python/Node/Rust 무엇도 설치할 필요가 없습니다.

## 다운로드

| OS | 파일 | 실행 방법 |
|---|---|---|
| **Windows 10/11 x64** | `Eoditdeora-0.1.0-setup.exe` | 더블클릭 → 설치 마법사 |
| **Linux x64** (Ubuntu 22.04+, Fedora 39+) | `Eoditdeora-0.1.0-x86_64.AppImage` | 더블클릭 (파일 관리자) 또는 `./Eoditdeora-*.AppImage` |

릴리즈 페이지: <https://github.com/Cheol-H-Jeong/eoditdeora/releases>

## Windows

1. `Eoditdeora-<ver>-setup.exe` 더블클릭.
2. 기본값으로 "다음 → 다음 → 설치".
3. 설치 마법사에서 **"Windows 로그인 시 자동 시작"** 체크박스 유지 (기본 ON).
4. 설치 완료 → 자동 실행.
5. 이후에는 시작메뉴 "어딨더라" 아이콘 또는 바탕화면 바로가기.

설치 위치: `%LOCALAPPDATA%\Programs\Eoditdeora\` (관리자 권한 없이 설치 가능).
인덱스 저장소: `%LOCALAPPDATA%\eoditdeora\` (제거해도 문서 원본은 안 건드림).

## Linux

1. AppImage 파일에 실행 권한 부여 (파일 관리자가 자동으로 못 하면):
   ```bash
   chmod +x Eoditdeora-0.1.0-x86_64.AppImage
   ```
2. 더블클릭하거나 터미널에서:
   ```bash
   ./Eoditdeora-0.1.0-x86_64.AppImage
   ```
3. 첫 실행 시 로그인 자동 시작이 `~/.config/autostart/eoditdeora.desktop`에
   자동 등록됩니다.

## 첫 실행 후 무슨 일이 일어나나

| 단계 | 동작 |
|---|---|
| 1. 창 표시 | PyQt6 WebEngine 기반 네이티브 창. 별도 브라우저 불필요 |
| 2. 인덱서 데몬 | 백그라운드 스레드로 기동. 감시 폴더가 아직 없으면 대기 |
| 3. LLM 기동 시도 | 모델 가중치가 있으면 `llama-server` 3개 백엔드를 자동 기동 |
| 4. 자동 시작 등록 | 로그인 시 자동 실행되도록 OS에 기록 |

## 재부팅 후

OS 로그인 즉시 어딨더라가 자동으로 기동됩니다.
- 인덱서 데몬 → 기동
- 로컬 LLM 미기동 상태면 → 자동 기동 (`RuntimeSupervisor.ensure_running()`)
- 창은 기본 표시. `--autostart` 플래그로 실행되며, 단축키(Ctrl+Shift+Space)로 언제든 불러오기 가능.

자동 시작을 끄려면:

| OS | 방법 |
|---|---|
| Windows | 설정 → 앱 → 시작프로그램 → "Eoditdeora" OFF |
| Linux | `rm ~/.config/autostart/eoditdeora.desktop` |
| 앱 내부 | 설정 메뉴의 "자동 시작" 토글 (v0.2 예정) |

## 문서 폴더 등록

창이 열리면 우측 사이드바 "감시 폴더" → "+ 폴더 추가" 또는 CLI:

```bash
# Linux
./Eoditdeora-*.AppImage --cli add-root ~/Documents
# Windows
"C:\Program Files\Eoditdeora\eoditdeora.exe" --cli add-root "%USERPROFILE%\Documents"
```

등록 후:
- 과거 파일 전부 → **catch-up scan** 으로 색인
- 이후 추가/수정/삭제 → **watchdog** 이 실시간 감지하여 즉시 반영

## LLM 엔드포인트 연결 (옵션 — 답변 모드 활성화)

어딨더라는 **모델 가중치를 직접 올리지 않습니다.** 이미 서빙 중인
로컬 LLM API (vLLM, llama.cpp, Ollama, LM Studio 등)를 연결만 합니다.
이미 돌고 있는 서버가 없으면 검색 모드는 BM25만으로 정상 작동하고,
답변 모드는 설정 후에 활성화됩니다.

### 연결 방법 (모두 창 안에서)

1. 우측 사이드바 **LLM 엔드포인트** 섹션 → **자동 탐색** 버튼
2. 127.0.0.1 에서 발견된 서버가 목록으로 표시됨
3. 원하는 서버의 `LLM에 지정` 클릭 → 모델 선택 → **저장**
4. (옵션) 임베딩·리랭커 엔드포인트도 같은 방식으로 지정

### 자동 탐색 대상 포트

| 서버 | 기본 URL |
|---|---|
| llama.cpp `llama-server` | http://127.0.0.1:8080 |
| vLLM | http://127.0.0.1:8000/v1 |
| LM Studio | http://127.0.0.1:1234/v1 |
| Ollama | http://127.0.0.1:11434/v1 |

다른 포트나 원격 서버를 쓰려면 사이드바 입력란에 직접 URL 입력 후 저장.
인증이 필요한 vLLM은 API key 필드 사용.

### 왜 가중치를 직접 안 올리나?

GPU 하나에 여러 모델을 중복 적재하면 컨텍스트·성능이 충돌합니다.
사용자가 이미 운영 중인 로컬 LLM 파이프라인(예: oss-120b + Qwen)
그대로 활용하는 게 가장 효율적이고, 유지보수 책임도 사용자 쪽에
일관되게 남습니다.

## 제거

| OS | 방법 |
|---|---|
| Windows | 설정 → 앱 → "어딨더라" → 제거 |
| Linux | AppImage 파일 삭제 + `~/.config/autostart/eoditdeora.desktop` 삭제 |

인덱스 데이터를 완전히 지우려면:
```bash
# Linux
rm -rf ~/.local/share/eoditdeora ~/.config/eoditdeora
# Windows
rmdir /s "%LOCALAPPDATA%\eoditdeora"
```
문서 원본은 건드리지 않습니다 (D3 불변식).
