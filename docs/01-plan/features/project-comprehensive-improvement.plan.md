# 전체 프로젝트 종합 개선 Plan (project-comprehensive-improvement)

> **Summary**: laborconsult 전 서브시스템(보안·계산모듈·RAG 파이프라인·프론트/배포)을 4개 병렬 에이전트로 심층 감사하여 P0~P3 발견사항을 도출하고, 6개 웨이브(긴급→보안→계산→RAG→프론트→정리)로 개선을 계획한다.
>
> **Project**: laborconsult
> **Author**: DrunkenZealnut
> **Date**: 2026-07-02
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 핵심 기능(통상임금·판례 RAG·챗봇)은 견고하나, 서버리스 신뢰경계·시크릿 위생에 구조적 결함이 있고(무인증 메일 릴레이, 커밋된 실 API 키), 계산기가 특정 입력에서 크래시하며(ZeroDivisionError), 판례 인용·보강 기능이 dict 키 불일치로 조용히 죽어 있고, 저장소에 75MB+ 코퍼스·쓰레기 파일이 방치되어 있다 |
| **Solution** | 심각도 기준 6개 웨이브로 정리 — ① 긴급(오픈 릴레이 인증·키 폐기·크래시 가드) ② 보안 하드닝(JWT 시크릿 분리·브루트포스·공유 rate-limit·인젝션/XSS) ③ 계산 정확성(국민연금 최신값·음수 가드·골든 테스트) ④ RAG 기능결함(인용 화이트리스트·판례 보강·이중 LLM 호출 제거) ⑤ 프론트/배포(maxDuration·타임아웃·a11y) ⑥ 저장소 위생·죽은 코드 정리 |
| **Function/UX Effect** | 피싱 릴레이·관리자 탈취·개인정보 노출 경로 차단, "주 0일" 등 입력에도 계산기가 죽지 않음, 판례 근거가 실제로 답변에 노출되고 환각 억제 recall 개선, 긴 RAG 응답이 중간에 끊기지 않으며 스크린리더·키보드 접근성 확보 |
| **Core Value** | 노동상담 서비스의 **신뢰성·안전성·법적 정확성**을 프로덕션 수준으로 끌어올려, 개인정보를 다루는 공공성 높은 서비스로서의 최소 방어선과 답변 품질을 동시에 확보 |

---

## 1. 분석 개요

### 1.1 목적

전체 코드베이스를 기능설계·보안·보완사항·계산모듈 관점에서 점검하고, 실행 가능한 개선계획을 우선순위와 함께 제시한다. 본 문서는 **감사 결과 종합 + 개선 로드맵**이며, 개별 항목은 이후 각자의 design/do 단계로 분화한다.

### 1.2 분석 방법

4개 독립 에이전트가 실제 코드·git 히스토리·테스트 실행·법령 웹 검증을 병렬 수행했다(추측 배제, 파일 정독 기반).

| 영역 | 주요 대상 | 검증 방식 |
|------|-----------|-----------|
| 보안 | `api/index.py`(922줄), `app/config.py`, `.env.example`, `vercel.json`, git 히스토리 | OWASP Top 10, 시크릿 스캔, 커밋 diff |
| 계산모듈 | `wage_calculator/` 39파일(9,584줄) | 테스트 2종 실행, 2026 법령·판례 웹 교차검증, 엣지케이스 재현 |
| RAG 파이프라인 | `app/core/` 전 모듈, `session.py`, 프론트 `readSSE` | 데이터 흐름 추적, 폴백 경로 검증, dict 스키마 대조 |
| 프론트/배포 | `public/index.html`(1,470줄), `calculator_flow/`, `vercel.json`, `.gitignore` | XSS 벡터 추적, `git check-ignore`, 죽은 코드 grep |

### 1.3 영역별 건강도 요약

| 영역 | 강점 | 핵심 약점 | 종합 |
|------|------|-----------|:----:|
| **계산 정확성** | 통상임금(2023다302838)·주휴(2022다291153)·퇴직금·4대보험 요율(2026) 정확 반영 | ZeroDivisionError 크래시, 음수 미검증, 회귀 테스트 부재 | 🟢 우수(안정성 보강 필요) |
| **RAG/기능설계** | 전 외부의존 실패에 폴백 실구현, known P0 이미 해소 | 판례 인용·보강 2건 조용히 사문화, 비계산 질문 LLM 2회 | 🟡 견고하나 은닉결함 |
| **보안** | bcrypt·JWT alg 고정·path traversal·파일 magic-byte 검증 | 무인증 메일 릴레이, 커밋된 실 키, JWT=관리자비번 재사용 | 🔴 구조적 결함 |
| **프론트/배포** | SSE·마크다운·KaTeX·파일첨부 완성도, 폴백 처리 | 저장소 위생(75MB+ 방치), maxDuration 미설정, 렌더 XSS | 🟡 위생·견고성 보강 |

### 1.4 특기사항 (PDCA 상태 정합)

- **`chatbot-network-error-fix`(현재 활성 feature, plan 단계)** — RAG 에이전트 확인 결과 SSE `error_gen` NameError와 Pinecone eager-init 모두 **이미 코드상 해결**됨(`api/index.py:115,154`, `app/config.py:56-63`). 별도 수정 불요 → **verify 후 종료(archive)** 권장.
- **`interactive-follow-up`(check, matchRate 97%)** — 그러나 실제로는 `session.save_pending()` 호출부가 없어 pending·`follow_up` 플로우가 **배선되지 않음**. 문서상 상태와 코드 실태가 불일치 → 재점검 필요.

---

## 2. 발견사항 종합 (심각도별 마스터 목록)

### 🔴 P0 — 즉시 조치 (서비스 안전 직결)

| # | 영역 | 발견 | 위치 |
|---|------|------|------|
| S-0 | 보안 | **무인증 오픈 메일 릴레이** — `/api/send-email`이 인증·CAPTCHA 없이 서버 SMTP로 임의 수신자에게 브랜드 사칭 메일 발송 가능 | `api/index.py:865-917` |
| C-0 | 계산 | **ZeroDivisionError 전체 크래시** — `daily_work_hours=0`/`weekly_work_days=0` 입력 시 통상임금 산정이 죽어 모든 계산기 마비 | `ordinary_wage.py:119,216`, `minimum_wage.py:145` |

### 🟠 P1 — 높음 (권한 탈취·정보 노출·기능 사문화·배포 위험)

| # | 영역 | 발견 | 위치 |
|---|------|------|------|
| S-1a | 보안 | `.env.example`에 **실제 API 키 2개 커밋**(ODCLOUD 64자 hex, LAW `kcsvictory`) — git 히스토리 영구 노출 | `.env.example` |
| S-1b | 보안 | **JWT 서명키에 관리자 비밀번호 재사용** + CAPTCHA HMAC과 키 공유 — 저엔트로피 시크릿 오프라인 복구 → 관리자 탈취 | `api/index.py:209-210,224` |
| S-1c | 보안 | 관리자 로그인 **브루트포스 방어·상수시간 비교 부재** | `api/index.py:242-253` |
| R-1a | RAG | **NLRC 판례 본문 보강 100% 미작동** — `사건명` 등 한글 키로 읽으나 `search_precedent`는 영문 키 반환 | `nlrc_cases.py:229-236` |
| R-1b | RAG | **Pinecone 판례번호가 인용 화이트리스트에 미포함** — 주 RAG 경로 판례가 LLM 인용 목록에서 누락, 유효 판례까지 인용 억제 | `rag.py:316-321`, `pipeline.py:1103-1114` |
| C-1 | 계산 | **국민연금 기준소득월액 상·하한 outdated** — 617만/39만(2025 복사) → 실제 637만/40만(2025.7 개정) | `constants.py:230-231` |
| F-1a | 프론트 | **`.gitignore` 미비** — 신규 코퍼스 ~75MB+·pip 쓰레기(`=0.8.0` 등)·벤치마크 JSON이 무시목록에 없어 실수 커밋 위험 | `.gitignore` |
| F-1b | 배포 | **Vercel `maxDuration` 미설정** — 기본 10초 초과 시 긴 RAG 스트림 강제 중단 | `vercel.json` |

### 🟡 P2 — 중간 (인젝션·XSS·비용·품질)

| # | 영역 | 발견 | 위치 |
|---|------|------|------|
| S-2a | 보안 | 인메모리 rate-limit이 서버리스 다중 인스턴스에서 무력화 | `api/index.py:471-484,847-876` |
| S-2b | 보안 | Supabase PostgREST 필터 인젝션(공개 `board_search`) | `api/index.py:696,721` |
| S-2c | 보안 | `board_posts` 응답에 `_anonymize()` 미적용(규약 위반) | `api/index.py:724-733,794-804` |
| S-2d | 보안 | PII 마스킹 정규식 불완전(주민번호·계좌 누락) | `api/index.py:607-619` |
| S-2e | 보안 | `_sanitize_html()` 정규식 XSS 필터 우회 가능 | `api/index.py:858-862` |
| F-2a | 프론트 | `md()` 본문 미이스케이프 `innerHTML` 주입 → 렌더 XSS | `public/index.html:873-955,764` |
| F-2b | 프론트 | 게시판 `onclick` 속성 인젝션(`escHtml`이 `"` 미이스케이프) | `public/index.html:1411,1365` |
| F-2c | 프론트 | `calculator_flow`의 `sendPrompt` 전면 무동작(부모 함수 미정의) | `calculator_flow/*.html`, `calculators.html` |
| F-2d | 프론트 | 클라이언트 fetch 타임아웃/재시도 부재 | `public/index.html:1210-1241` |
| F-2e | 프론트 | 접근성(aria-live·label·키보드 조작) 결함 | `public/index.html` 전반 |
| F-2f | API | 예외→raw 500 + 페이지네이션 스키마 불일치 | `api/index.py` board/admin |
| R-2a | RAG | 비계산 질문 전량에 Sonnet 의도분석 **2회 순차 호출**(지연·비용) | `pipeline.py:366-385,875-901` |
| R-2b | RAG | `sources` SSE 이벤트 항상 빈 배열 + 프론트도 무시(이중 사문화) | `pipeline.py:1068`, `index.html:1018` |
| R-2c | RAG | BM25 코퍼스 미배포 → "Hybrid Search"가 사실상 Dense-only | `data/`, `rag.py:206-216` |
| C-2a | 계산 | 출산전후휴가 자동감지 죽은 코드(`pass`) | `facade/__init__.py:216-217` |
| C-2b | 계산 | 회귀 테스트 부재(CLI assert 없음, 배치 94.8% 비교불가) | `wage_calculator_cli.py`, `calculator_batch_test.py` |
| C-2c | 계산 | 음수 임금 입력 미검증 | `ordinary_wage.py:46-85` |

### 🟢 P3 — 낮음 (정리·강화)

| # | 영역 | 발견 |
|---|------|------|
| S-3 | 보안 | CORS 전면 개방·보안 헤더 전무 / CAPTCHA 토큰 재사용 / category 검증 누락 / base64 크기 사후검증 |
| C-3 | 계산 | 매직넘버 `209` 하드코딩·`WEEKS_PER_MONTH` 중복정의 / 월급제 유급공휴일 이중가산 소지 |
| R-3 | RAG | 죽은 코드: `composer.py`(AttributeError 잠복)·`converter.py`·`calculator.py` 오펀, pending·`follow_up` 플로우 미배선, circuit breaker half-open 완전초기화 |
| F-3 | 프론트 | `actionEmail`의 `prompt()` UX / 죽은 코드(`initHeroCalcs`, `escHtml` 중복정의) / `.git` 비대(86MB) / CORS 이중설정 |

---

## 3. 개선 계획 (웨이브별)

### Wave 0 — 긴급 조치 (P0 + 즉시 위험 P1) · 최우선

> 배포 여부와 무관하게 **지금 즉시**. 코드 한두 줄~설정 수준이나 영향이 치명적.

1. **오픈 메일 릴레이 차단 (S-0)** — `/api/send-email`에 최소 CAPTCHA 토큰 검증 필수화 + `body_html`을 클라이언트 신뢰 대신 **서버 보관 답변 원문**으로 렌더. 발송 대상을 요청 세션이 생성한 답변으로 한정.
2. **커밋된 실 API 키 폐기 (S-1a)** — `ODCLOUD_API_KEY`·`LAW_API_KEY` **즉시 재발급**, `.env.example`은 placeholder로 치환. 히스토리 정리(`git filter-repo`)는 별도 판단.
3. **ZeroDivision 가드 (C-0)** — `_get_base_hours()` 반환 하한 `max(monthly_hours, 1.0)` + `hourly = monthly / base if base else 0.0` 방어.

**예상 소요**: 0.5일

### Wave 1 — 보안 하드닝 (P1~P3 보안) · 우선순위 1

| 항목 | 조치 | 근거 |
|------|------|------|
| JWT 시크릿 (S-1b) | `ADMIN_JWT_SECRET` 필수·≥32B 강제(기본값 금지), CAPTCHA용 `CAPTCHA_HMAC_SECRET` 분리 | 키 재사용·저엔트로피 제거 |
| 로그인 보호 (S-1c) | IP별 rate-limit + 실패 백오프, `hmac.compare_digest` 상수시간 비교 | 브루트포스 차단 |
| 공유 rate-limit (S-2a) | 게시판·이메일 카운터를 Supabase/Redis 공유 스토어로 이전 | 서버리스 우회 방지 |
| PostgREST 이스케이프 (S-2b) | `board_search` 검색어의 `,%*()\` 이스케이프/화이트리스트, 길이·문자셋 검증 | 공개 인젝션 차단 |
| 게시판 익명화 (S-2c) | `board_posts`의 `question`·`nickname`에 `_anonymize()` 적용 | 규약 준수 |
| PII 정규식 확장 (S-2d) | 주민번호 `\d{6}[-\s]?\d{7}`·계좌 패턴 추가 | 노동상담 특성 |
| HTML 새니타이저 (S-2e) | 정규식 대신 `bleach`/`nh3` allowlist로 태그·속성·URL 스킴 처리 | 우회 차단 |
| CORS·헤더 (S-3) | `allow_origins` 실도메인 제한, 보안 헤더(HSTS·X-Frame·CSP) 추가, 이중설정 정리 | 방어심화 |
| CAPTCHA 1회용 (S-3) | 사용 토큰 jti 단기 저장으로 재사용 차단 | 봇 대량등록 방지 |

**예상 소요**: 2일

### Wave 2 — 계산 정확성·안정성 (P1~P3 계산) · 우선순위 1

1. **국민연금 값 갱신 (C-1)** — `pension_income_max=6_370_000`, `pension_income_min=400_000`, 건보 상·하한 재확인, "적용기간(7월~익년6월)" 주석.
2. **음수 임금 가드 (C-2c)** — `calculate()` 진입 시 임금·시간 필드 `max(0, ...)` 클램프 또는 경고.
3. **출산휴가 자동감지 (C-2a)** — `pass` 죽은 코드를 실제 조건으로 교체 또는 삭제.
4. **골든 테스트 도입 (C-2b)** — CLI 32케이스에 `expected` 핵심수치 + `assert` + 종료코드 반영, 2026/2025 요율 분기 케이스 추가. 배치는 "크래시/파싱 실패 감지" 용도로 성격 분리.
5. **매직넘버·이중가산 정리 (C-3)** — `MONTHLY_STANDARD_HOURS`·`WEEKS_PER_MONTH` 상수 사용, 월급제 유급공휴일 합산 분기.

**예상 소요**: 1.5일

### Wave 3 — RAG 기능결함 수정 (P1~P2 RAG) · 우선순위 2

1. **판례 인용 통일 (R-1b)** — `precedent_meta`를 `hits` 인자로 전달(각 항목 title+chunk 채움) 또는 `format_pinecone_hits`가 `case_name` 파싱. 인용목록 생성과 사후검증이 **동일 소스** 사용.
2. **NLRC 보강 키 교정 (R-1a)** — `case_name`/`court`/`date`로 수정, 없는 `사건번호` 제거.
3. **의도분석 2회 제거 (R-2a)** — 2차 `_extract_params`(괴롭힘)를 괴롭힘 토픽/키워드일 때만 게이팅, 또는 `HARASSMENT_TOOL`을 분석 도구셋에 통합해 단일 호출.
4. **sources 이벤트 실체화 (R-2b)** — `precedent_meta`를 `sources`로 실제 전송 + 프론트 출처 카드 렌더, 미채택 시 이벤트·문서에서 제거해 계약 정리.
5. **BM25 배포 (R-2c)** — `build_bm25_corpus.py` 산출물을 배포 번들에 포함(함수 크기 확인) 또는 CLAUDE.md 서술 현실화.

**예상 소요**: 1.5일

### Wave 4 — 프론트/UX/배포 견고성 (P1~P2 프론트) · 우선순위 2

1. **maxDuration (F-1b)** — `vercel.json`에 `"functions": {"api/index.py": {"maxDuration": 60}}`(플랜 확인), 미지원 시 조기 first-token 스트리밍.
2. **클라이언트 타임아웃·재시도 (F-2d)** — `AbortController`+45~60s 타임아웃, 실패 시 "다시 시도" 버튼.
3. **렌더 XSS 차단 (F-2a, F-2b)** — `md()` 진입부 `escapeHtml` 또는 DOMPurify, 게시판은 인라인 onclick→`addEventListener`+`dataset`.
4. **sendPrompt 복구 (F-2c)** — `calculators.html`에 `window.sendPrompt` 정의 또는 `postMessage` 방식, 미지원 노드는 onclick 제거.
5. **접근성 (F-2e)** — `#chat` `aria-live="polite"`, 입력창 `aria-label`, 게시판 항목 `<button>`, 메뉴 포커스 트랩.
6. **API 예외/스키마 (F-2f)** — 공용 예외 핸들러로 DB 오류 일관 503/500, 페이지네이션 응답 표준화, SMTP 미설정은 503.
7. **이메일 입력 UX (F-3)** — `prompt()` → 인라인 입력/모달.

**예상 소요**: 1.5일

### Wave 5 — 저장소 위생·죽은 코드 정리 (P1~P3) · 우선순위 3

1. **쓰레기 삭제** — `rm -f '=0.8.0' '=2.0.0' '=4.0.0' '=5.0.0'`, 루트 벤치마크/테스트 JSON 정리.
2. **`.gitignore` 보강 (F-1a)** — `output_*/`, `nodong_counsel/`, `documents/`, `benchmark_*.json`, `*_results.json`, `metadata*.json`, `*.jsonl`, `=*`, `.vscode/`, `.bkit/runtime/`, `.bkit/snapshots/` 등 추가(.vercelignore와 동기화). `metadata.json`·`supabase_fix_session_id.sql`은 런타임/마이그레이션 여부 확인 후 처리.
3. **죽은 코드 제거 (R-3, F-3)** — `composer.py`/`converter.py`/`calculator.py` 오펀 정리(또는 되살릴 계약 명시), pending·`follow_up` 미배선 결정(배선 or 제거), 프론트 `initHeroCalcs`·`escHtml` 중복정의 제거.
4. **PDCA 정합** — `chatbot-network-error-fix` verify 후 archive, `interactive-follow-up` 코드 실태 재점검.

**예상 소요**: 1일

---

## 4. 우선순위 및 일정

| Wave | 주제 | 우선순위 | 예상 소요 | 의존성 |
|------|------|:--------:|:---------:|--------|
| 0 | 긴급(릴레이·키·크래시) | **P0** | 0.5일 | 없음 |
| 1 | 보안 하드닝 | P1 | 2일 | Wave 0 후 |
| 2 | 계산 정확성·안정성 | P1 | 1.5일 | Wave 0 후(병렬 가능) |
| 3 | RAG 기능결함 | P2 | 1.5일 | 독립 |
| 4 | 프론트/UX/배포 | P2 | 1.5일 | 독립 |
| 5 | 저장소·죽은코드 정리 | P3 | 1일 | 전 웨이브 후 |

**총 예상**: 약 8일 (Wave 2·3·4는 상호 독립으로 병렬화 시 단축 가능)

---

## 5. 성공 기준

| 지표 | 현재 | 목표 | 측정 |
|------|------|------|------|
| P0 미해결 | 2건 | 0건 | 재현 테스트 통과 |
| 커밋된 시크릿 | 2건 | 0건 | `gitleaks` 스캔 |
| 계산기 크래시(엣지 입력) | 발생 | 0건 | 0/음수/경계 입력 회귀 테스트 |
| 판례 인용 화이트리스트 반영 | 0%(주경로) | 정상 | 통합 테스트에서 Pinecone 판례번호 노출 확인 |
| 계산 골든 테스트 | 없음 | ≥20 케이스 assert | `wage_calculator_cli.py` 종료코드 |
| 저장소 방치 파일 | ~75MB+ | 0(무시처리) | `git status` clean |
| 접근성 | aria-live 없음 | 핵심 경로 통과 | axe/스크린리더 점검 |

---

## 6. 리스크

| 리스크 | 영향 | 가능성 | 대응 |
|--------|------|:------:|------|
| 커밋된 키가 이미 오남용됨 | 높음 | 중 | 즉시 재발급 + 사용량 모니터링, 히스토리 정리 |
| 공유 rate-limit 도입 시 지연 증가 | 중 | 중 | 부작용 엔드포인트만 우선, 캐시 계층 활용 |
| 판례 인용 통일이 사후검증 로직과 충돌 | 중 | 중 | 생성·검증 동일 소스로 리팩터 후 통합 테스트 |
| BM25 배포로 함수 번들 초과 | 중 | 저 | JSON 직렬화·크기 확인, 초과 시 Dense-only 유지 |
| 골든 테스트 기대값 산정 오류 | 중 | 중 | 법령·판례 근거와 수기 대조, 소수 케이스부터 |
| 히스토리 재작성(force-push) 협업 충돌 | 높음 | 저 | 팀 합의 후, 백업·별도 판단 |

---

## 7. 제외 사항 (YAGNI)

- **인증 체계 전면 교체(OAuth/SSO)** — 현재 관리자 단일 인증 + 시크릿 강화로 충분, 과도.
- **Vector DB·임베딩 모델 교체** — Pinecone/text-embedding-3-small 현 성능 유지(RAG 품질은 기존 `rag-flow-quality-improvement` Plan에서 별도 다룸).
- **`.git` 히스토리 대용량 blob 완전 정리** — 파괴적이며 즉시 위험 아님, 별도 유지보수 과제로 분리.
- **계산기 신규 유형 추가** — 본 개선은 기존 25종의 정확성·안정성에 한정(신규는 `missing-calculators` Plan 참조).
- **프론트 프레임워크 도입(React 등)** — 단일 HTML 유지, 이번엔 보안·a11y·견고성만.

---

## 8. 아키텍처·컨벤션 고려사항

### 8.1 프로젝트 레벨

**Dynamic** — FastAPI + Vercel serverless + 외부 BaaS(Supabase/Pinecone) 조합. 본 개선은 신규 아키텍처가 아니라 **기존 구조의 하드닝·정합화**이므로 레벨 변경 없음.

### 8.2 주요 결정

| 결정 | 방향 | 근거 |
|------|------|------|
| rate-limit 저장소 | 인메모리 → Supabase/Upstash | 서버리스 다중 인스턴스 정합 |
| HTML 새니타이즈 | 정규식 → `bleach`/`nh3` + 프론트 DOMPurify | allowlist 방식 우회 방지 |
| 시크릿 관리 | 기본값 허용 → 필수·고엔트로피 강제 | 키 재사용·약한 시크릿 제거 |
| 테스트 | 스모크 → 골든(assert+종료코드) | 회귀 방지 |

### 8.3 컨벤션 준수 (CLAUDE.md 기반)

- 기존 규약(`_anonymize()` 필수, 보안 체인 순서, `app/core/*.py` 커밋 필수, 폴백 필수)은 **이미 문서화**되어 있으나 일부 위반(board 익명화 누락, sources 사문화)이 발견됨 → 본 개선으로 코드를 문서에 맞춤.
- 신규 도입 라이브러리(`bleach`/`nh3`, DOMPurify) `requirements.txt`/CDN 반영, 상한 핀 검토.

### 8.4 필요 환경변수

| 변수 | 용도 | 신규 |
|------|------|:----:|
| `ADMIN_JWT_SECRET` | JWT 서명(≥32B 필수) | 강제화 |
| `CAPTCHA_HMAC_SECRET` | CAPTCHA 서명 분리 | ☑ |
| `RATE_LIMIT_STORE_URL` | 공유 rate-limit(선택 Redis) | ☑ |

---

## 9. Next Steps

1. [ ] 본 Plan 검토·승인, 웨이브별 우선순위 확정
2. [ ] Wave 0(긴급) 즉시 착수 — 별도 승인 없이 진행 권장
3. [ ] 웨이브별 design 문서 분화 (`/pdca design <sub-feature>`)
4. [ ] `chatbot-network-error-fix` verify 후 archive 정리

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-07-02 | 4개 병렬 감사 종합 초안 | DrunkenZealnut |
