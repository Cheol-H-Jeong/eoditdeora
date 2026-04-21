# 빠른 시작

이 문서는 처음 설치하시는 분 기준으로 가장 짧은 경로만 안내합니다.
목표는 다음 두 가지입니다.

1. 앱을 실행합니다.
2. 본인 로컬 LLM 서버에 연결해 검색을 시작합니다.

릴리즈 파일은 GitHub Releases에서 받으시면 됩니다.

- Releases: <https://github.com/Cheol-H-Jeong/eoditdeora/releases>

## Windows 10/11 설치

1. 릴리즈 페이지에서 `Eoditdeora-<version>-setup.exe`를 다운로드합니다.
2. 파일을 더블클릭합니다.
3. Windows SmartScreen 경고가 보이면 `추가 정보`를 누른 뒤 `실행`을 선택합니다.
4. 설치 마법사에서 기본값으로 진행합니다.
5. 설치가 끝나면 앱을 실행합니다.

(스크린샷 추가 예정)

## Linux 설치

1. 릴리즈 페이지에서 `Eoditdeora-<version>-x86_64.AppImage`를 다운로드합니다.
2. 터미널을 열고 AppImage 파일이 있는 폴더로 이동합니다.
3. 아래 명령으로 실행 권한을 부여합니다.

```bash
chmod +x ./Eoditdeora-<version>-x86_64.AppImage
```

4. 파일 관리자에서 더블클릭하거나, 터미널에서 직접 실행합니다.

```bash
./Eoditdeora-<version>-x86_64.AppImage
```

(스크린샷 추가 예정)

## 첫 실행 체크리스트

앱이 열리면 아래 항목만 순서대로 확인하시면 됩니다.

1. 우측 사이드바의 `LLM 엔드포인트` 섹션을 엽니다.
2. `LLM (답변용)` 엔드포인트를 입력합니다.
3. `임베딩 (의미 검색용)` 엔드포인트를 입력합니다.
4. `리랭커 (정렬용)` 엔드포인트를 입력합니다.
5. 필요한 경우 각 역할의 `API key`를 입력합니다.
6. `테스트`를 눌러 연결 여부를 확인합니다.
7. `저장`을 눌러 설정을 저장합니다.
8. `감시 폴더`에서 문서가 들어 있는 폴더를 추가합니다.
9. 문서 수가 많은 경우 초기 색인이 끝날 때까지 잠시 기다립니다.

권장 기본 주소는 아래와 같습니다.

- LLM: `http://127.0.0.1:8081`
- 임베딩: `http://127.0.0.1:8082`
- 리랭커: `http://127.0.0.1:8083`

단일 서버를 쓰는 경우에는 같은 주소를 여러 역할에 넣을 수도 있습니다. 다만 트래픽이 몰리면 응답 속도가 느려질 수 있습니다.

## 로컬 llama-server 예시

아래 예시는 `llama.cpp`의 `llama-server`를 역할별로 3개 포트에 나누어 띄우는 가장 단순한 형태입니다. 모델 파일명과 GPU 옵션은 환경에 맞게 바꿔서 사용하세요.

LLM 서버:

```bash
llama-server \
  -m /path/to/llm-model.gguf \
  --host 127.0.0.1 \
  --port 8081 \
  --ctx-size 8192 \
  --api-key YOUR_BEARER_KEY_HERE
```

임베딩 서버:

```bash
llama-server \
  -m /path/to/embed-model.gguf \
  --host 127.0.0.1 \
  --port 8082 \
  --embedding \
  --pooling cls \
  --api-key YOUR_BEARER_KEY_HERE
```

리랭커 서버:

```bash
llama-server \
  -m /path/to/rerank-model.gguf \
  --host 127.0.0.1 \
  --port 8083 \
  --embedding \
  --pooling rank \
  --reranking \
  --api-key YOUR_BEARER_KEY_HERE
```

앱에는 아래처럼 넣으시면 됩니다.

- `LLM (답변용)`: `http://127.0.0.1:8081`
- `임베딩 (의미 검색용)`: `http://127.0.0.1:8082`
- `리랭커 (정렬용)`: `http://127.0.0.1:8083`
- `API key`: `YOUR_BEARER_KEY_HERE`

`llama.cpp` 공식 문서 기준으로 임베딩 서버는 `--embedding --pooling cls`, 리랭커 서버는 `--reranking`과 rank 풀링 조합이 필요합니다.

참고:

- llama.cpp: <https://github.com/ggml-org/llama.cpp>
- llama.cpp server README: <https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md>

## Ollama를 쓰는 경우

Ollama를 이미 사용 중이면 아래처럼 시작하시면 됩니다.

1. 앱의 `api_kind`는 `OpenAI 호환`으로 두셔도 됩니다.
2. 기본 주소는 `http://127.0.0.1:11434/v1` 입니다.
3. LLM과 임베딩은 Ollama로 연결하셔도 됩니다.
4. 모델 이름이 자동 목록에 안 보이면 `model id`에 직접 입력하시면 됩니다.

예시:

- `LLM (답변용)`: `http://127.0.0.1:11434/v1`
- `임베딩 (의미 검색용)`: `http://127.0.0.1:11434/v1`

리랭커는 별도 서버를 권장합니다. 현재 Ollama 공식 OpenAI 호환 문서는 채팅과 임베딩 중심으로 안내되어 있어, 이 앱의 리랭커 역할은 `llama.cpp`나 `vLLM` 같은 별도 엔드포인트를 두는 편이 안정적입니다. 이는 공식 문서 범위를 기준으로 한 권장 사항입니다.

참고:

- Ollama OpenAI compatibility: <https://docs.ollama.com/api/openai-compatibility>
- Ollama embeddings: <https://docs.ollama.com/capabilities/embeddings>

## 다음 문서

설치는 되었는데 검색이나 연결이 예상대로 되지 않으면 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)를 확인해 주세요.
