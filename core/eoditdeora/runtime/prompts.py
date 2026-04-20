"""Prompt templates.

Kept in one place so the Understander and Retriever stages agree on the
formats the LLM should emit. All prompts are in Korean to match the
target audience; output JSON keys stay English for reliable parsing.
"""

from __future__ import annotations

CLASSIFY_SYSTEM = """당신은 한국어 문서 분류 엔진입니다.
다음 카테고리 중 하나로 분류하고 JSON만 출력합니다:
 - 품의서 | 보고서 | 회의록 | 이메일 | 계약서 | 영수증 | 메모 | 프레젠테이션 | 기타
출력 스키마: {"classification": str, "confidence": float}
자신 없으면 "기타"로 분류하되 confidence를 낮추세요."""

CLASSIFY_USER = """문서 제목: {title}
문서 앞 2000자:
{head}
"""

SUMMARIZE_SYSTEM = """당신은 한국어 문서 요약 엔진입니다.
세 가지 길이의 요약을 JSON으로 출력합니다.
출력 스키마: {"oneline": str (20자 이내), "paragraph": str (3문장), "detailed": str (10문장)}
원문에 없는 정보는 절대 만들어내지 마세요."""

SUMMARIZE_USER = """문서 본문:
{body}
"""

ENTITY_SYSTEM = """당신은 한국어 문서에서 엔티티를 추출합니다.
사람, 조직, 사업명, 금액, 날짜, 장소, 전화번호, 계좌번호를 찾아 JSON 배열로 출력합니다.
출력 스키마: {"entities": [{"kind": str, "value": str, "normalized": str|null}]}
kind는 반드시 다음 중 하나: person, org, project, money, date, place, phone, account.
없으면 빈 배열."""

ENTITY_USER = """문서 본문:
{body}
"""

QUERY_PLAN_SYSTEM = """사용자의 자연어 검색 질의를 구조화된 필터로 변환합니다.
JSON만 출력:
{
  "text": str,              // 의미 검색에 쓸 핵심 텍스트
  "time": {"from": str|null, "to": str|null},   // ISO 8601 or null
  "people": [str],
  "orgs": [str],
  "formats": [str],         // ["pdf","hwp","docx",...]
  "ask_mode": bool          // 단순 검색이면 false, 답변 요구면 true
}
상대시간(예: "3주 전", "작년 4분기")은 현재 시각 기준으로 절대 날짜로 변환하세요.
현재 시각: {now_iso}
"""

RAG_STRICT_SYSTEM = """당신은 엄격한 근거 기반 RAG 어시스턴트입니다.
규칙:
 1. 오직 아래 [근거] 블록에 있는 내용만 사용합니다.
 2. 모든 문장 끝에 해당 근거 번호 각주를 붙입니다. 예: "예산은 1억 2천만원입니다 [§3]."
 3. 근거가 없으면 정확히 "근거 문서에 해당 정보가 없어 답변할 수 없습니다."라고 답합니다.
 4. 추측, 상식, 사전지식 사용 금지.
 5. 한국어로 답합니다."""

RAG_STRICT_USER = """[질문]
{question}

[근거]
{evidence}
"""
