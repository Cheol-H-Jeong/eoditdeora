# 어딨더라

어딨더라는 Windows/Linux에서 실행되는 로컬 문서 검색 앱입니다.
내 PC 또는 사내 PC의 문서를 색인해 파일명 검색, 본문 검색, AI 답변을 제공합니다.
문서는 사용자가 지정한 LLM 서버로만 전달되며, 법인 망분리 환경을 우선으로 설계했습니다.

English summary: A desktop search app for Korean office documents with
local-first retrieval and evidence-based AI answers.

## 누구를 위한 것인가

- HWP, HWPX, PDF, DOCX, XLSX, PPTX 같은 한국어 업무 문서를 자주 찾으시는 분
- 개발자는 아니지만 설치 파일 실행, 폴더 선택, 서버 주소 입력 정도는 익숙하신 분
- 법인 망분리 환경 또는 외부 SaaS 업로드가 어려운 환경에서 문서 검색이 필요하신 분

## 누구에게는 잘 맞지 않습니다

- Google Drive, Notion, Slack 같은 클라우드 문서만 검색하실 분
- 서버 구축 없이 앱 하나만 설치하면 AI까지 모두 자동 포함되길 기대하시는 분
- 팀 공용 검색 포털이나 멀티유저 웹 서비스를 찾으시는 분

## 핵심 기능

1. 파일명 즉시 검색: 문서 본문 색인이 끝나기 전에도 파일명 기준 검색 결과를 바로 보여드립니다.
2. 본문 키워드 검색: 등록한 감시 폴더의 문서 내용을 색인해 키워드와 문맥으로 찾을 수 있습니다.
3. AI 답변 + 근거: 연결한 LLM 서버를 이용해 답변을 만들고, 어떤 문서를 근거로 썼는지 함께 보여드립니다.

## 스크린샷

![screenshot](docs/screenshot.png)

(스크린샷 추가 예정)

## 시작하기

릴리즈 페이지에서 운영체제에 맞는 설치 파일을 받으신 뒤 아래 명령 또는 더블클릭으로 실행하세요.

### Windows 10/11

```powershell
start "" ".\Eoditdeora-<version>-setup.exe"
```

### Linux

```bash
chmod +x ./Eoditdeora-<version>-x86_64.AppImage && ./Eoditdeora-<version>-x86_64.AppImage
```

설치 직후에는 아래 두 가지만 먼저 확인하시면 됩니다.

1. 설정에서 `LLM (답변용)`, `임베딩 (의미 검색용)`, `리랭커 (정렬용)` 엔드포인트를 입력합니다.
2. 우측 사이드바에서 검색할 문서 폴더를 감시 폴더로 추가합니다.

자세한 설치 순서는 [QUICKSTART.md](docs/QUICKSTART.md)를 참고해 주세요.

## 문서

- [빠른 시작](docs/QUICKSTART.md)
- [문제 해결](docs/TROUBLESHOOTING.md)
- [기여 안내](CONTRIBUTING.md)
- [아키텍처 개요](docs/architecture.md)

## 지원 대상

- Windows 10/11 x64
- Linux x64
- 로컬 또는 사내 OpenAI 호환 LLM 서버, Ollama, llama.cpp, vLLM, LM Studio 등

## 라이선스

이 프로젝트는 [AGPL-3.0](LICENSE) 라이선스로 배포됩니다.
