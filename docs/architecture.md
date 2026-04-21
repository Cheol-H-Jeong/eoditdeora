# 아키텍처 개요

어딨더라는 데스크톱 UI에서 검색 요청을 받고, Tauri 셸과 Python 사이드카를 거쳐 저장소와 검색기를 호출한 뒤, 필요할 때만 외부 LLM 서버에 질의하는 구조입니다.

```text
+-------------------- UI --------------------+
| Svelte desktop UI                         |
| - 파일명 검색                             |
| - 본문 검색                               |
| - AI 답변 + 근거 표시                     |
+-------------------+------------------------+
                    |
                    v
+---------------- Tauri Shell ---------------+
| Rust shell / dev bridge                    |
| - 윈도우 생성                              |
| - 프런트엔드 <-> 사이드카 RPC 연결         |
+-------------------+------------------------+
                    |
                    v
+------------- Python Sidecar ---------------+
| stdio JSON-RPC                             |
| - 설정 로드                                |
| - 감시 폴더 관리                           |
| - 색인/검색 요청 조정                      |
+-------------------+------------------------+
                    |
                    v
+------- Stores / Retrievers / Clients ------+
| stores                                     |
| - fast index                               |
| - full-text index                          |
| - vector store                             |
| retrievers                                 |
| - filename / keyword / hybrid / rag        |
| clients                                    |
| - llm / embed / rerank HTTP client         |
+-------------------+------------------------+
                    |
                    v
+------------- External LLM Servers ---------+
| OpenAI-compatible local servers            |
| - llama-server                             |
| - Ollama                                   |
| - vLLM / LM Studio / internal gateway      |
+--------------------------------------------+
```

핵심 원칙은 단순합니다. 문서 색인과 검색 제어는 앱 내부에서 처리하고, 모델 추론은 사용자가 지정한 LLM 서버에 맡깁니다.
