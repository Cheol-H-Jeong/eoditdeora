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

## LLM 모델 받기 (옵션 — 답변 모드 활성화)

검색만 쓸 거면 생략해도 됩니다. Strict 근거 답변 기능을 쓰려면:

```bash
# Linux
./Eoditdeora-*.AppImage --cli download-models
# 또는 가중치를 직접 놓기
cp gemma-4-26b-a4b-it.Q8_0.gguf  ~/.local/share/eoditdeora/models/
cp bge-m3.Q8_0.gguf               ~/.local/share/eoditdeora/models/
cp bge-reranker-v2-m3.Q8_0.gguf   ~/.local/share/eoditdeora/models/
```

모델이 있는 상태에서 실행하면 `llama-server` 3개가 자동 기동됩니다.
공무원 오프라인 환경이면 USB로 위 파일들을 옮기고 끝.

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
