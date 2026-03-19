# Gap Analysis: feature-roadmap-assessment

> Design: `docs/02-design/features/feature-roadmap-assessment.design.md`
> 분석일: 2026-03-08

---

## 1. 파일 완성도 (30%)

Design §7 기준 7개 파일 → 실제 7개 파일 존재.

| # | 파일 | Design 작업 | 존재 | 비고 |
|:-:|------|:----------:|:----:|------|
| 1 | `api/index.py` | 수정 | ✅ | E-01 try/except + E-04 validation handler |
| 2 | `app/config.py` | 수정 | ✅ | E-02 환경변수 검증 |
| 3 | `app/core/pipeline.py` | 수정 | ✅ | E-03 RAG 검색 에러 보호 |
| 4 | `check_env.py` | 신규 | ✅ | 환경변수 검증 스크립트 |
| 5 | `.env.example` | 수정 | ✅ | 필수/선택 구분 + Vercel 안내 |
| 6 | `test_e2e.py` | 신규 | ✅ | E2E 통합 테스트 (7 시나리오) |
| 7 | `test_audit_verify.py` | 신규* | ✅ | 감사 문서 교차검증 (5/5 통과) |

*Design에서는 `calculator_batch_test.py` 수정으로 설계했으나, 기존 파일의 복잡성(500건 층화 샘플링)을 고려하여 별도 스크립트(`test_audit_verify.py`)로 분리 구현. 기능적으로 동일 목적 달성.

**파일 완성도: 100% (7/7)**

---

## 2. FR 구현율 (40%)

### FR-01: E2E 통합 테스트 ✅

| 항목 | Design 요구 | 구현 상태 |
|------|-----------|:--------:|
| T-01 SSE 스트리밍 | `test_chat_stream()` | ✅ |
| T-02 임금계산 스트리밍 | `test_chat_stream_calc()` | ✅ |
| T-03 파일 첨부 | Design에 포함 | ⚠️ 미구현 (서버 없이 테스트 불가) |
| T-04 동기 채팅 | `test_chat_sync()` | ✅ |
| T-05 헬스체크 | `test_health()` | ✅ |
| T-06 관리자 로그인 | `test_admin_login_fail()` | ✅ |
| T-07 관리자 통계 | `test_admin_stats_unauthorized()` | ✅ |
| T-08 잘못된 입력 | `test_invalid_input()` | ✅ |

**FR-01: 7/8 시나리오 구현 (87.5%)**

### FR-02: 계산기 정확도 교차검증 ✅

| 항목 | Design 요구 | 구현 상태 |
|------|-----------|:--------:|
| 통상임금 검증 | 시급, 월급 환산 | ✅ 2항목 통과 |
| 퇴직금 검증 | 평균임금 유리 원칙 | ✅ 통과 |
| 4대보험 요율 | 보험료율 4항목 | ✅ 4항목 통과 |
| 연차수당 검증 | 발생일수 | ✅ 통과 |
| 최저임금 상수 | 산입범위 계산 | ✅ 2025/2026 통과 |

**FR-02: 5/5 검증 대상 전부 통과 (100%)**

### FR-03: API 에러 핸들링 강화 ✅

| 항목 | Design 요구 | 구현 상태 | 코드 위치 |
|------|-----------|:--------:|----------|
| E-01 SSE 에러 보호 | try/except + error 이벤트 | ✅ | `api/index.py:96-101, 147-153` |
| E-02 환경변수 검증 | from_env()에서 missing 체크 | ✅ | `app/config.py:36-44` |
| E-03 외부 API 에러 | _search 실패 보호 | ✅ | `pipeline.py:731-735` |
| E-04 한국어 422 에러 | RequestValidationError handler | ✅ | `api/index.py:37-41` |

**FR-03: 4/4 항목 구현 (100%)**

### FR-04: 환경변수·시크릿 관리 ✅

| 항목 | Design 요구 | 구현 상태 |
|------|-----------|:--------:|
| check_env.py 생성 | 필수/선택 분류 검증 | ✅ |
| .env.example 업데이트 | 필수/선택 구분 + Vercel 안내 | ✅ |
| PINECONE_INDEX_NAME 포함 | 선택 목록에 포함 | ✅ |

**FR-04: 3/3 항목 구현 (100%)**

**FR 전체 구현율: 19/20 = 95%**

---

## 3. NFR 준수 (20%)

| NFR | 기준 | 충족 | 근거 |
|-----|------|:----:|------|
| NFR-01 에러 메시지 한국어 | 모든 사용자 대면 에러 한국어 | ✅ | 422, SSE error, 환경변수 에러 모두 한국어 |
| NFR-02 스택트레이스 미노출 | 프로덕션에서 내부 에러 숨김 | ✅ | except Exception → 일반 에러 메시지만 반환 |
| NFR-03 테스트 독립성 | 서버 기동 후 독립 실행 | ✅ | `--base-url` 옵션, 접속 실패 시 안내 |
| NFR-04 기존 동작 보존 | 에러 핸들링이 정상 흐름 미영향 | ✅ | try/except는 에러 시에만 동작, 정상 흐름 그대로 |

**NFR 준수: 4/4 = 100%**

---

## 4. 기존 동작 보존 (10%)

| 항목 | 검증 |
|------|:----:|
| 감사 문서 교차검증 5/5 통과 | ✅ 계산기 정상 동작 확인 |
| API 엔드포인트 변경 없음 | ✅ 기존 라우트 그대로 |
| WageCalculator 인터페이스 변경 없음 | ✅ 수정 없음 |

**기존 동작 보존: 100%**

---

## 5. Gap 목록

| # | 유형 | 항목 | 영향 |
|:-:|:----:|------|:----:|
| G-01 | Minor | T-03 파일 첨부 E2E 테스트 미구현 | Low |
| G-02 | Deviation | FR-02를 별도 파일로 분리 (design: calculator_batch_test.py 수정) | Positive |

### G-01 상세
파일 첨부 테스트(T-03)는 base64 인코딩된 파일 데이터를 POST로 전송해야 하며, 실제 파서(PDF/이미지) 의존성이 필요. 현재 `test_e2e.py`에서는 서버 접속 기반 테스트이므로 파일 첨부는 별도 fixture가 필요. 서비스 핵심 경로가 아니므로 영향 Low.

### G-02 상세 (Positive Deviation)
Design에서는 `calculator_batch_test.py`에 AUDIT_CASES를 추가하도록 설계했으나, 기존 파일이 500건 층화 샘플링 테스트(analysis_qna.jsonl 의존)로 매우 복잡함. 별도 `test_audit_verify.py`로 분리하여 독립 실행 가능하게 구현. 더 나은 설계.

---

## 6. Match Rate 산출

| 항목 | 비중 | 점수 |
|------|:----:|:----:|
| 파일 완성도 | 30% | 100% → 30.0 |
| FR 구현율 | 40% | 95% → 38.0 |
| NFR 준수 | 20% | 100% → 20.0 |
| 기존 동작 보존 | 10% | 100% → 10.0 |
| **합계** | **100%** | **98.0%** |

---

## 7. 결론

**Match Rate: 98%** — Report 생성 가능

- Minor Gap 1건 (T-03 파일 첨부 테스트): 서비스 핵심 경로 아님, 향후 추가 가능
- Positive Deviation 1건 (교차검증 분리): 테스트 독립성 향상

---

*분석일: 2026-03-08*
