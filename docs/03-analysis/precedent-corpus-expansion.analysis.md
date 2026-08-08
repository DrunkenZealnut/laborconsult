# precedent-corpus-expansion Gap Analysis

> Check 단계 (gap-detector, 2026-08-09)
> 기준: `docs/02-design/features/precedent-corpus-expansion.design.md` (Do 중 실측 갱신 반영본)
> 대상: `fetch_court_precedents.py` · `enrich_court_precedents.py` · `pinecone_upload_court_precedents.py` · `test_precedent_ingest.py` · `.github/workflows/tests.yml` · `CLAUDE.md`

## Match Rate: 96%

| 구분 | 개수 |
|------|:----:|
| 총 체크 항목 | 94 (N/A 3건 제외) |
| ✅ 일치 | 87 |
| ⚠️ 부분일치 | 6 |
| ❌ 불일치 | 1 |
| ➕ 설계에 없는 추가 구현 | 17 (감점 없음) |

계산: (87 + 6×0.5) / 94 = 95.7% → **96%**

설계 §3~§7 명세가 코드에서 그대로 확인되고, Do 단계 실측으로 갱신된 부분
(페이지네이션·사건부호 라우팅·병합 사건번호·대표 사건번호 방식·관련 쟁점
태깅)이 모두 반영됨. 조용히 틀리는 실패 모드 셋(오매칭·ID 충돌·NFD)은
T1~T13 회귀로 고정됨.

---

## 갭 목록

### 🔴 G1. BM25 gz 재빌드됨·미커밋 (HIGH — 유일한 실질 갭)

프로덕션은 신규 판례 500건이 없는 **구 gz(2026-07-14 커밋)를 서빙 중**.
설계 §4가 `[관련 쟁점: …]` 프리픽스를 저장 텍스트에 넣은 이유가 BM25 색인인데,
구 gz에는 그 텍스트가 없어 **쟁점 태깅의 키워드 검색 절반이 무효** — 실패가
조용하다(Dense-only 폴백). → **커밋으로 해소** (사용자 커밋 지시 대기).

### 🔴 G2. 코드 4종 untracked + tests.yml만 tracked (HIGH)

`tests.yml`만 먼저 커밋되면 CI가 `ModuleNotFoundError`로 즉시 red.
→ 스크립트 4종 + tests.yml + CLAUDE.md + gz를 **단일 커밋**으로 묶을 것.

### 🟡 G3. enrich의 미문서화 의존 (MEDIUM)

`enrich_court_precedents.py`가 `pinecone_upload_textbook.py`(다른 기능의
untracked 파일)의 `load_body`를 import. enrich만 커밋하면 신규 클론에서 실행
불가(지연 import라 CI 테스트는 통과 — 실패가 안 잡힘).
→ **`pinecone_upload_textbook.py`를 같은 커밋에 포함** + 설계 §4에 의존 1줄 기재(정정 완료).

### 🟡 G4. Plan §7 완료 기준 550건 vs 실측 500건 (MEDIUM)

원인은 법제처 DB 미수록(외부, 98건 복구 불가 — 25건 표본 진단으로 확정)이라
구현 결함 아님. → Plan §7을 실측 근거와 함께 정정(완료).

### 🟢 G5~G7. 설계 문서 드리프트 (LOW — 코드 수정 불필요, 문서 정정 완료)

| # | 내용 | 처리 |
|---|------|------|
| G5 | `_미발견.csv` 설계는 4열, 구현은 2열(사건번호·사유) — 법원·날짜는 `누락_판례목록.csv` 조인으로 복구 가능 | 설계 §3.5 표를 2열로 정정 |
| G6 | §3.6 시그니처 3건 드리프트(`fetch_detail`이 Element 반환, `normalize_record` 인자, `--resume`→`--force`) — 구현이 §3.5 "재개=기본" 정책과 더 정합 | 설계 §3.6 정정 |
| G7 | §3.2 "어댑터 2개" → 단일 `normalize_record` 분기 (필드 매핑 7종 전부 정확) | 설계 §3.2 정정 |

## 주목할 추가 구현 (설계 초과, 17건 중 발췌)

- 상세 응답 **2차 정확일치 게이트** — 오염 경로 추가 차단 (fetch:468-473)
- `itertext()` — `<br/>`이 실제 XML 엘리먼트로 올 때 본문이 조용히 잘리는 것 방지, T7-e로 고정
- 병합 사건 파일명·벡터 ID를 요청 번호로 고정 → 601건 목록과 1:1 대응
- `_CASE_CODE_MAP` 45종(설계 예시 13종 대비 확장) + 업로드 실행 내 ID 충돌 탐지
- enrich의 OCR 내성 표제 파서(키릴 Ш, 깨진 편 표제, 범용 표제 14종 제거)

## 데이터 산출 검증 (코드 외, Do 단계 실측)

| 항목 | 결과 |
|------|------|
| 수집 | 500/601 (83%) — 잔여 98건 법제처 DB 미수록 확정 |
| 쟁점 태깅 | 496/500 (99.2%) |
| Pinecone | laborlaw-v2 9,088 → 10,989 (+1,901, 기대치 정확 일치) |
| Dense 검색 | 쟁점 질의 3종 상위 5위 내 신규 판례 히트 |
| BM25(로컬 신규 gz) | 62,075문서, 신규 판례·쟁점 태그 히트 확인 |
| 오프라인 테스트 | 56/56 통과 |

## 결론

실질 갭은 **커밋 누락 하나로 수렴** (G1+G2+G3 = 동일 커밋으로 해소).
문서 드리프트 G4~G7은 Check 단계에서 정정 완료. Match Rate 96% ≥ 90% —
Act(iterate) 불필요, 커밋 후 `/pdca report` 진행 가능.
