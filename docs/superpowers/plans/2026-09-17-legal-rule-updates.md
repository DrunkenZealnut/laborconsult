# Legal Rule Updates Implementation Plan

**Goal:** Pinecone 변경 후보 검색, 관리자 검토·승인, 시행일별 계산 반영과 감사 이력을 구현한다.

**Architecture:** 순수 도메인/계산 스냅샷, Pinecone/Supabase 어댑터, 인증된 API·관리 화면, 정기 검색 CLI를 분리한다.

**Tech Stack:** Python dataclasses/contextvars/unittest, 기존 FastAPI/Pydantic, Supabase PostgreSQL, Pinecone, vanilla JS.

**Spec:** `docs/superpowers/specs/2026-09-17-legal-rule-updates-design.md`

## Constraints

- 사용자 승인 정책: 검색만 자동, 적용은 관리자 승인.
- 법적 데이터는 laborlaw-v2 서버 조회에서만 가져온다. 승인되지 않은 법률값을 새로 심지 않는다.
- 기존 작업 트리의 사용자 변경은 보존한다. 이 세션에서 직접 구현·검증하며 운영 반영은 하지 않는다.

## Tasks

- [x] 1. `test_legal_rule_updates.py`: 수동 등록/수정/승인/반려/취소, 출처 및 재검증, 날짜 경계·중복·충돌 테스트를 먼저 추가한다. `python -m unittest test_legal_rule_updates -v` 실패 확인 후 도메인을 구현한다.
  - `wage_calculator/legal_rules.py`: `RuleSnapshot(records, reference_date)`, `parameter(key, legacy)`; 읽기 전용 요청 스냅샷.
  - `app/core/legal_updates.py`: `LegalUpdateService(store, evidence)`; store `load()/save(revision, document, actor, action)`; evidence `fetch(id)/search(query)`.
  - 등록은 pending, 승인은 원문 재조회/기간 검증 후 approved, 취소는 revoked. 같은 revision만 저장된다.
- [x] 2. `supabase_legal_rules.sql`과 어댑터: registry CAS RPC와 append-only 이벤트, service-role 전용 권한. 서버 어댑터가 SQL revision 충돌을 409로 변환하도록 테스트한다.
- [x] 3. 계산기: facade에서 스냅샷 scope를 열고 최소임금/보험/출산급여 허용 키를 조회한다. 원금/금액보다 먼저 관리기준 검증. `reference_date` 배선 및 결과 provenance 추가. 승인 후 실제 계산 금액이 바뀌며 다른 요청에는 누수하지 않는 테스트.
- [x] 4. `api/legal_updates.py`, `public/admin_legal_rules.js`: 기존 JWT 인증으로 목록/검색/등록/수정/승인/반려/취소·감사 이력. UI 입력과 오류·충돌 및 XSS 검증.
- [x] 5. `sync_legal_rules.py`와 `.github/workflows/legal-rule-scan.yml`: 주간 검색 및 수동 실행. 한 주제 실패해도 나머지 진행, 실패는 종료코드로 보고, 후보만 저장.
- [x] 6. `docs/calculator-audit/2026-09-17-comprehensive-audit.md`: 기존 감사, 갱신 구조 감사, 구현 완료/기존 미해결/운영 미실행 분리. 배포 절차 및 검증 결과 기록.
- [x] 7. 새 테스트, 기존 계산·배선·관리자 테스트 실행. diff와 보안·동시성 자체 검토 후 결과 보고.

구현 중 변경사항과 검증 결과는 종합 보고서에 기록한다. 현재 기능 브랜치에서 작업하며 커밋·배포는 별도 수행하지 않는다.
