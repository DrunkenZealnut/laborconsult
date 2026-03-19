# board-write-security Gap Analysis Report

> **Feature**: 게시판 글쓰기 — 비밀번호 + 보안문자
> **Date**: 2026-03-19
> **Match Rate**: 97%

---

## Summary

| Category | Items | Match | Missing | Changed | Positive | Score |
|----------|:-----:|:-----:|:-------:|:-------:|:--------:|:-----:|
| FR-01 Modal UI | 11 | 11 | 0 | 0 | 0 | 100% |
| FR-02 CAPTCHA | 10 | 10 | 0 | 0 | 0 | 100% |
| FR-03 bcrypt | 4 | 4 | 0 | 0 | 0 | 100% |
| FR-04 Write API | 14 | 14 | 0 | 0 | 4 | 100% |
| FR-05 Delete API | 8 | 8 | 0 | 0 | 0 | 100% |
| FR-06 Supabase Table | 2 | 2 | 0 | 0 | 0 | 100% |
| FR-07 List Integration | 4 | 4 | 0 | 0 | 1 | 100% |
| FR-08 XSS/Validation | cross-cut | -- | 0 | 0 | 0 | 100% |
| **Total** | **53** | **53** | **0** | **0** | **5** | **100%** |

**Overall Match Rate: 97%** (100% functional match, 5 positive deviations)

---

## Positive Deviations (Design에 없지만 구현에 추가된 개선)

| # | Item | Location | Description |
|---|------|----------|-------------|
| P1 | x-forwarded-for 프록시 분할 | `api/index.py:508` | `,`로 split하여 다중 프록시 체인 지원 |
| P2 | 금칙어 확장 (ㅅㅂ/ㅂㅅ) | `api/index.py:484` | 한국어 축약형 추가 |
| P3 | 닉네임+질문 공백 구분자 | `api/index.py:531` | 경계에서 오탐 방지 |
| P4 | 카테고리 공백 trim | `api/index.py:550` | `.strip()` 후 저장 |
| P5 | 인라인 삭제 비밀번호 입력 | `board.html` | `prompt()` 대신 인라인 UX |

## Missing Features

**없음** — 모든 FR 완전 구현.

## Changed Features

**없음** — 모든 구현이 설계와 일치.

---

## Security Verification

| 항목 | 설계 | 구현 | 결과 |
|------|------|------|:----:|
| CAPTCHA HMAC 서명 + 5분 만료 | O | `_generate_captcha` + `_verify_captcha` | PASS |
| bcrypt cost 12 | O | `gensalt(rounds=12)` | PASS |
| XSS 방지 (escHtml + DOMPurify) | O | `escHtml()` + `DOMPurify.sanitize()` | PASS |
| SQL Injection 방지 | O | Supabase 파라미터화 쿼리만 사용 | PASS |
| Rate Limit IP 해시 3건/분 | O | `_check_rate_limit()` | PASS |
| IP 프라이버시 SHA-256[:16] | O | `hashlib.sha256(...).hexdigest()[:16]` | PASS |

---

## Convention Compliance

| 규칙 | 구현 | 결과 |
|------|------|:----:|
| API는 `api/index.py`에 직접 추가 | 모든 엔드포인트 `api/index.py` | MATCH |
| Pydantic 모델 상단 정의 | `BoardWriteRequest`, `BoardDeleteRequest` | MATCH |
| 에러 형식 `{"error": "..."}` | 모든 JSONResponse 동일 형식 | MATCH |
| 내부 함수 `_` prefix | `_generate_captcha`, `_verify_captcha` 등 | MATCH |
| 인라인 JS/CSS (board.html) | 단일 파일 구조 유지 | MATCH |

---

## Files Verified

| File | Lines Changed | Status |
|------|:------------:|:------:|
| `api/index.py` | +~200줄 | PASS |
| `public/board.html` | +~250줄 | PASS |
| `requirements.txt` | +1줄 | PASS |
