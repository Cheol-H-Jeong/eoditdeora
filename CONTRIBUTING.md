# Contributing to 어딨더라

이 프로젝트는 AGPL-3.0-or-later 라이선스 하에 있습니다. 기여한 코드는
같은 라이선스로 공개됩니다.

## 개발 환경 요구사항

- Python 3.11+
- Rust stable (Tauri 빌드용)
- Node 20+ / pnpm 9+
- Linux의 경우: `libwebkit2gtk-4.1-dev`, `libssl-dev`, `patchelf`

## 빌드·테스트

```bash
# Python 코어
pip install -e ".[dev]"
pytest core/tests -q

# UI
pnpm install
pnpm --filter eoditdeora-ui check

# 전체 데스크톱 번들
cd apps/shell && cargo tauri build
```

## 기여 절차

1. 이슈 먼저 여세요. 특히 설계 변경은 사전 합의가 필요합니다.
2. 새 파서를 추가할 때:
   - `core/eoditdeora/parsers/<fmt>_parser.py`에 `Parser` 프로토콜 구현
   - `core/eoditdeora/parsers/__init__.py`에 이름 등록
   - `core/tests/test_<fmt>_parser.py`에 최소 3개 테스트
   - 샘플 파일을 커밋하지 말고 테스트 안에서 동적 생성
3. 커밋 메시지는 conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`).
4. PR 제출 전 `ruff check . && mypy core/eoditdeora`가 통과해야 합니다.

## 설계 불변식

[docs/DECISIONS.md](docs/DECISIONS.md)에 기록된 D1~D9 결정은 PR이 깨뜨릴
수 없습니다. 번복하려면 먼저 ADR을 갱신하는 PR을 선행하세요.

## 영역별 담당 (초대 시 채움)

| 영역 | 담당 |
|---|---|
| 파서 (HWP 계열) | — |
| 파서 (PDF/OCR) | — |
| UI / UX | — |
| 빌드 / 릴리즈 | — |

## 보안 이슈 신고

`cheol@markr.ai`로 이메일. 공개 이슈로 올리지 마세요.
