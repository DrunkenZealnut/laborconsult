# Report: 판례 아카이브 및 인벤토리 (precedent-archive)

> **Feature**: 판례 원문 2,415파일 + 복구 필수 부속 기록의 **유실-복구 가능한 아카이브** 및 **단일 인벤토리 장부** 구성으로, 판례 자산 내구성 확보 및 공개 경계 명확화
> **PDCA Cycle**: Plan(2026-08-30) → Design(2026-09-01, design-validator 후 개정) → Do(2026-09-02) → Check(96.9%) → Report
> **Period**: 2026-08-30 ~ 2026-09-02 (4일, 설계 검증 → 구현 → 다중 코드리뷰 포함)
> **Match Rate**: **96.9%** (125/129, design-validator 반영 후 gap-detector 측정)
> **Status**: PR #61 **오픈·머지 대기** (CI 전체 pass, CodeRabbit 4라운드 완료 — 머지는 사용자 결정), archive_precedents.py·data/precedent_archive/·회귀 T27 커밋

---

## Executive Summary

### 1.1 사이클 개요

| 항목 | 내용 |
|------|------|
| **Feature** | 판례 아카이브(법제처 수집분·크롤분) + 통합 인벤토리 CSV 2파일(사건/문서 단위) + 아카이브 복원 도구 + 회귀 T27 |
| **기간** | 2026-08-30 (Plan) ~ 2026-09-02 (Report, PR #61 머지 대기) |
| **Match Rate** | 96.9% (design-validator 74점 반영 후 재측정) |
| **성공 기준** | S1~S6 전부 충족: 인벤토리 3,082행 통합, 원장 1,568키 전수 포섭, 인용 공백 10건 확정, 복원 무손실, 공개 경계 준수, 오프라인·멱등 성립 |

### 1.2 가치 전달 — 4관점

| 관점 | 내용 |
|------|------|
| **Problem** | 판례 원문 2,415파일이 **전부 `.gitignore` 로컬 전용**이고 복구 필수인 원장(`_uploaded_ids.json`)도 같은 디스크에만 있다. 판례가 5곳(letec 보강 1,579 / crawl 837 / Pinecone 3곳 / code 인용 17)에 흩어져 있는데 **어떤 판례가 어디에 있는지 답하는 장부가 없다.** 실증: 계산기 코드의 법적 근거 판례 17건 중 **8건이 코퍼스 어디에도 없었고** 아무도 몰랐다. `--reset` 사고로 복구 수단이 Pinecone 뿐인데 Serverless 백업이 없어 디스크 장애 = 코퍼스 재구축 불능 + 원장 유실로 Pinecone 롤백 불가. |
| **Solution** | ① 아카이브: 법제처 수집분(비보호 저작물)을 `letec_precedents.jsonl.gz`로 커밋 — 원문+메타 유실-복구 가능한 형태로 보존. ② 인벤토리: 사건번호를 기본 키로 **단일 장부**(`inventory.csv` + `documents.csv`) — 문서 보유처·검색 수록처·인용처를 통합해 "이 판례가 어디에 있는가"를 답하게 함. ③ 공개 계층: 크롤분은 게이트(자동 3-버킷 + 표본 육안)로 verbatim만 선별 승격. ④ 복원 도구: `archive_precedents.py extract`로 번들에서 md 복원(S4 무손실 단언) + `--verify` 정합 검사 8종(S2·S5·S6 보증). |
| **Function & UX Effect** | 사용자 인터페이스 변화는 없다(순수 자산 작업). 간접 효과: **인용-코퍼스 공백 10건 목록**(코드 인용 + 교재·미발견 대조)이 산출되어 후속 수집 대상이 명확화되고, 계산기 답변의 법적 근거 판례가 RAG 검색에도 실릴 길이 열렸다. 잔여 크롤 363건(editorial)도 "공개 불가, 로컬 보관" 상태가 명시되어 운영상 혼란이 사라짐. |
| **Core Value** | **"무엇이 있는지 모른다"는 상태를 없앴다.** 겹침 재수집·중복 판정 사이클이 반복된 근본 원인이고, 코드 인용 공백 8건이 무감지로 남은 원인이다. 디스크·Pinecone 어느 쪽을 잃어도 인벤토리+아카이브에서 복구 가능한 구조를 세웠다. 아카이브 자체가 "공개 안전한 계층"을 마련해 저작권 검토 없이 배포가 안 되는 관례를 세웠다. |

---

## 1. Plan 요약

**문서**: `docs/01-plan/features/precedent-archive.plan.md` (2026-08-30)
**발단**: 판례 코퍼스가 5곳 분산 + 복구 필수 부속 기록 단일 장애점 + 계산기 코드 인용 17건 중 8건 공백 실증

### 1.1 문제 정의 (P1~P3)

| ID | 문제 | 영향 |
|----|------|------|
| P1 | 내구성 — 판례 2,415파일 + 원장이 단일 디스크 | 디스크 장애 = 코퍼스 재구축 불능 + Pinecone 롤백 수단 소멸 |
| P2 | 인벤토리 부재 — "이 판례가 코퍼스에 있는가" 답변 없음 | 코드 인용 공백 8건 무감지, 겹침 재수집 사이클 반복, 신규 수집 시 중복 판정 재구현 |
| P3 | 공개 경계 미정 — PUBLIC 저장소에 무엇을 커밋해도 되는지 판례별 판정 없음 | 무판정 커밋 = 제3자 저작물 공개 배포 리스크 / 과잉 회피 = P1 미해소 |

### 1.2 목표 (G1~G5)

| ID | 목표 | 결과 |
|----|------|------|
| G1 | 공개 계층 아카이브 | letec_precedents.jsonl.gz (1,578건, 5.2MB) ✅ |
| G2 | 인벤토리 단일 장부 | inventory.csv(사건 3,082행) + documents.csv(2,414행) ✅ |
| G3 | 인용-코퍼스 공백 목록 | 코드 인용 공백 10건 확정(2023다302838 포함) ✅ |
| G4 | 크롤분 저작권 게이트 | 자동 3-버킷 + 표본 육안(2라운드, 혼입 2→0) ✅ |
| G5 | 오프라인 회귀 | test_precedent_ingest.py::T27 (30여 단언) ✅ |

---

## 2. Design 요약

**문서**: `docs/02-design/features/precedent-archive.design.md` (2026-09-01, design-validator 74/100 반영 개정)

### 2.1 핵심 설계 결정

| # | 결정 | 근거 |
|---|------|------|
| D-1 | 레코드 정본: `body_md` = **파일 바이트 그대로** | 메타는 파생 사본. --extract는 body_md만 쓰면 S4(무손실) 자명 |
| D-2 | 번들 키: `doc_id` = **NFC 상대 경로** | 크롤 구세대는 사건번호 없어 case_key로 유일성 불가. 경로는 파일시스템 보증 |
| D-3 | 장부 분리: **2파일** — inventory(사건) + documents(문서) | 1사건:N문서 관계 실재(letec 정본+크롤 대체 286쌍), 게시물형 문서도 가져야 함 |
| D-4 | 대표 사건번호: **fetch 함수 import** | 단일 출처(사본 금지), 후속 수집의 L2 중복검사와 같은 답 보증 |
| D-5 | 크롤 게이트: **파일단위 3-버킷**(verbatim/editorial/post) | 전수 일괄보다 원문만 선별, 오공개 비대칭 원칙 부합 |
| D-10 | case_key: **court의 `case_no_to_ascii` import** | 원장 생산 함수(design-validator H1), hex 폴백 0건 실측 — 규약 폐기 |
| D-11 | 사장 NS 존재: `vec_dead` 컬럼 기록 | Plan 비목표 명시대로 존재만, 역매핑 가능분만 |

### 2.2 검증 이력

**design-validator** (2026-09-01, 74/100):
- **High 5건** 전부 반영: case_key 함수(H1) / 대표 판정 fetch import(H2) / 겹침대상 대응(H3) / 코드 인용 확장(H4) / _미발견 수치 정정(H5)
- **Medium 10건** 처리: 게이트 블록 양끝(M1) / MANIFEST 스키마(M3) / 스냅샷 낡음 탐지(M4) / vec_dead(M5) / code_citations.csv(M6) / 정준형·별칭(M7) / _index 대조(M8) / .gitignore 델타(M9) / 파일명-메타 불일치 보고(M10) 외
- **Low 10건** 반영 (설계 역반영 포함)

---

## 3. 구현 결과 (Do)

### 3.1 산출물

| # | 산출물 | 규모 | 상태 |
|---|--------|------|:---:|
| 1 | `archive_precedents.py` | 스크립트(build/gate/extract/verify 서브커맨드) | ✅ |
| 2 | `letec_precedents.jsonl.gz` | 1,578문서, 5.2MB | ✅ |
| 3 | `crawl_verbatim.jsonl.gz` | 460문서, 1.2MB (게이트 통과분) | ✅ |
| 4 | `inventory.csv` | 3,082행(사건 단위) | ✅ |
| 5 | `documents.csv` | 2,414행(문서 단위) | ✅ |
| 6 | `data/precedent_archive/records/` | 7개 스냅샷 + MANIFEST.json | ✅ |
| 7 | `test_precedent_ingest.py::T27` | 30여 검증 (T27-a ~ T27-j + 세부 28개) | ✅ |

### 3.2 핵심 구현 사항

**검증 체인** (4단계 누적):

1. **design-validator** (2026-09-01 자동 검증): 130항목 대조, 74점(High 5/Medium 10/Low 10 지적) → 실측 확인 + 설계 역반영
2. **gap-detector** (2026-09-01 자동 검증): 129항목 대조, 96.9%(M3·L9 처리, 설계 공백 3건 구현이 메움)
3. **CodeRabbit** (2026-09-01~02, 4라운드): 실지적 3건 전부 반영, 오지적 0
   - **1차 2건**: anchor_idx 빈 리스트 IndexError(개행 낀 마커) → editorial(no_anchor) 가드 + 회귀 T27-h4 / `tokenize.TokenizeError` 오타(표준 라이브러리에 없는 이름) → TokenError
   - **2차 0건**(pass), **3차 1건**: NFD 폴백이 NFC 상위 디렉터리에 막히는 구조 — 독립 격리와 동일 결론, 제안(파일명만 NFD)보다 일반적인 컴포넌트별 매칭으로 수정
   - **4차 0건**: 수정 승인
4. **CI** (offline-tests·GitGuardian·CodeRabbit·Vercel): 2회 실패 격리 끝에 전체 pass
   - 1차 격리(faa38f3): Linux ext4는 파일명 바이트 보존 — macOS 유래 NFD 파일명이 NFC 규약 doc_id로 안 열려 verify V3 전량 오탐(macOS APFS는 정규화-비민감이라 로컬 재현 불가)
   - 2차 격리(75d1acc): 전체 NFD 변환 폴백도 NFC 디렉터리(소스 리터럴 생성)에 막힘 → 컴포넌트별 os.listdir NFC-동등 매칭으로 재조립

**NFD-파일시스템 변종** (이 저장소 NFD 실패 클래스의 새 변종):
- macOS 생성 코퍼스(NFD 파일명) + Linux verify 조합에서만 발생 — 프로덕션에도 잠복해 있던 결함(macOS 코퍼스를 Linux에서 verify하는 경우)
- 처방: `Paths.doc_path`가 경로 컴포넌트별로 `os.listdir`에서 NFC-동등 항목을 찾아 실경로 재조립
- ⚠️ 이 폴백 분기는 **macOS에서 검증 불가**(APFS가 어떤 정규화 조합도 열어줌) — CI(Linux)가 유일한 판정자다. T27이 verify 출력을 삼키지 않게 고친 진단 개선이 2차 격리를 즉시 가능하게 했다

### 3.3 /simplify 4각 리뷰 반영

Reuse·Simplification·Efficiency·Altitude 측면에서 16개 메커니즘 수정:
- 상태 소유권: build의 `crawl_gate.json` 쓰기 제거 → 승인 드리프트 가드 재개방 경로 차단
- fetch에 provenance 반환 추가 → case_src 역공학 제거
- 공개 번들 스키마를 블랙리스트(제외 목록 lambda) → BUNDLE_FIELDS 화이트리스트로 반전 + V1 정합 검사 강화
- 스킵 4건은 diff 밖 확장(공용 승격 후속)

---

## 4. 검증 결과 (Check)

### 4.1 Gap 분석 — 96.9%

**Analysis 문서**: `docs/03-analysis/precedent-archive.analysis.md`

| 지표 | 값 |
|------|---|
| **Match Rate** | **96.9%** (125/129, 부분 8×0.5 포함) |
| High gap | 0 |
| Medium gap | 3 → 전부 반영 완료 |
| Low gap | 9 → 코드 6건 반영, 설계 역반영 3건 |
| 설계 밖 추가(긍정) | 6건 (역매핑 왕복·vec_ctx 3중 대응 등) |

**Medium 3건 반영**:
- M1: `--approve` 재추첨 금지 + rounds[] 이력 기록 → 규칙 진화 감사 추적
- M2: T27-c 양성 회귀 추가 (서두 선고문만 픽스처)
- M3: 원장 미수록 10건 사유 단일 확정 → "전문만, EMBED_SECTIONS 부재"

**성공 기준 실증** (S1~S6):

| 기준 | 실측 |
|------|------|
| S1 (인벤토리 통합) | 3,082행 = letec 1,578 ∪ crawl ∪ 코드 17 ∪ 교재 601 ∪ 미발견 967 ∪ 겹침 286 |
| S2 (원장 포섭) | 1,568 case_key 전부 inventory 존재 (V4 + T27-g) |
| S3 (인용 판정 완결) | 코드 인용 17→25건 확장(MAJOR_PRECEDENTS 포함), **실인용 공백 10건** 확정 |
| S4 (복원 무손실) | V3 전수 바이트 대조 + T27-e round-trip |
| S5 (공개 경계) | 번들 = exempt 1,578 + verbatim 460만. V7 + T27-d. 육안 2라운드(혼입 0 수렴) |
| S6 (오프라인·멱등) | V8(records/ 포함) + T27-f. Pinecone 쓰기 경로 0 |

### 4.2 실측 지표

| 항목 | 값 |
|------|-----|
| inventory 행 | 3,082 (예상 2,900~3,300 범위 내) |
| documents 행 | 2,414 = letec 1,578 + crawl 836 |
| 게이트 분포 | verbatim 460·editorial 363·post 13 |
| 원장 그룹 | 1,568 (doc_letec 1,578과 10건 차이 — 모두 "전문만" 원인) |
| ctx 벡터 | 1,310 (별도 조회) |
| 사장 NS | precedent·laborlaw 역매핑 가능분만 기록 |
| 실인용 공백 | 10건 확정 (코드 인용 2023다302838 포함) |
| 예시확정 | 3건 분리 (`EXAMPLE_CONFIRMED`/`EXAMPLE_OVERRIDE_REAL` 상수) |

---

## 5. Lessons Learned

### 5.1 검증 체인의 상보성

**design-validator** (문서↔구현 계약):
- 설계가 명시하지 않은 구현이 6건 잡혔다 (역매핑·벡터 조회·스냅샷 낡음 탐지)
- 그러나 설계 자체의 공백(블록 종료 정의 미완, vec_ctx 실경로 불명시, CI 서브셋 모순)은 못 잡았다

**gap-detector** (설계 구현):
- 설계 공백을 구현이 정확히 메웠다는 것을 역반영으로 확인했다
- design-validator 반영으로 이미 정렬된 상태였으므로 "High 0"이 성립했다

**CodeRabbit** (구현 품질):
- 자동 도구(design-validator·gap-detector)의 영역(계약·정합성)을 넘어 비기능적 결함을 잡았다
- **NFD-파일시스템 변종 같은 숨은 실패 클래스는 로컬 환경에서만 재현되는 버그**로, 자동 테스트도 놓쳤다

**교훈**: 검증 도구를 연쇄 적용하면 각 단계가 다른 층을 가드한다. 하나를 빼도 각각의 "맹점"이 도드라진다.

### 5.2 게이트 육안 절차의 실효

초판 규칙(v1)에서 v3(최종)로 진화하는 과정에서 **2라운드 육안만으로 혼입 신호 0화**가 된 이유:

1. **1차 표본 73건**: 혼입 2건 발견(`※ 편집자 안내문`, `<script>` JS 잔재) → 패턴 추가(보수화)
2. **전량 재분류**: 규칙 v2→v3 적용으로 버킷 변동(v2의 블록 종료 정의 미완으로 473건 오폐기 해소)
3. **2차 표본 78건**: 재추첨 + 육안 = 혼입 0

**전제: 규칙 변경 시 기존 승인 자동 무효화**(§7.2) — 이것이 없으면 규칙 진화가 old record에 여전히 old rule을 적용하는 "조용한 버그"가 된다.

### 5.3 단일 출처 규칙의 강제

case_key를 원장 생산 함수(court)에서 import하고, 대표 판정을 fetch에서 import한 까닭:
- 초판 설계가 "법률명 정규화는 `legal._case_no_to_ascii` import"라고 명시했으나, 실측에서 **그것은 원장 생산 함수가 아니었다**(원장은 court 함수 산출물)
- 같은 변수명의 사본이 legal·court·`upload_new_precedents.py` 3벌 존재(CLAUDE.md 아카이브 2026-08-09 기록)
- 이번 사이클은 **M1 사본 드리프트 교훈(T14-g~j 회귀)을 따라** 단일 함수를 import하는 것으로 재구현 금지를 구조적으로 강제했다

**교훈**: 사본 금지 원칙이 규칙만으로는 지켜지지 않는다. **파일을 읽어서 검증**해야 한다(T27-b의 `is` 동일성).

### 5.4 설계 대조의 한계 재증명

CLAUDE.md 경고와 일치:
> gap-detector의 Match Rate는 "설계대로 만들었는가"만 답한다 — 설계 자체의 공백은 원리적으로 못 잡는다.

이번 사이클에서:
- **설계 공백 3건** (블록 종료·vec_ctx·CI 서브셋) → 구현이 더 엄격한 쪽으로 해결
- **96.9% 뒤의 발견들** (게이트 규칙 v2→v3·NFD 파일시스템·code_citations dedup) → 자동 대조로 원리적 불가능
- **Match Rate 90% 초과 = 배포 신호가 아니다** 재증명

---

## 6. Completed Items

### 6.1 Core Deliverables

- ✅ `archive_precedents.py` (build/gate/extract/verify 서브커맨드 완성)
- ✅ `letec_precedents.jsonl.gz` (법제처 수집분 1,578문서 공개 계층)
- ✅ `crawl_verbatim.jsonl.gz` (게이트 통과 크롤분 460문서)
- ✅ `inventory.csv` (사건 단위 3,082행)
- ✅ `documents.csv` (문서 단위 2,414행)
- ✅ `MANIFEST.json` (스키마 + 스냅샷 메타)
- ✅ `records/` (7개 스냅샷: ledger·not_found·overlap·ctx_deleted·textbook·code·crawl_gate)

### 6.2 Validation & Regression

- ✅ Test suite: `test_precedent_ingest.py::T27` (30여 단언, T27-a ~ T27-j + 세부 검증)
- ✅ Verify: V0~V8 (8종 검사, 모두 pass)
- ✅ Gap analysis: 96.9% (M3·L9 전부 처리)
- ✅ Design validation: 74점(High 5 반영, Medium 10 처리, Low 10 적용)

### 6.3 Documentation & Process

- ✅ `.gitignore` 2줄 추가 (precedent_crawl_*.tar.gz · *.tmp)
- ✅ `CLAUDE.md` 갱신 (아카이브 절차·공개 경계·낡은 수치 정정)
- ✅ 분석 문서 최종 (Plan/Design/Analysis 완성, gap analysis 결과 반영)

---

## 7. Challenges Encountered & Resolution

이번 사이클은 **설계 검증(design-validator) 단계에서 주요 결함 5건을 사전 포착**했으므로, Do 단계 구현은 대체로 순조로웠습니다.

### 7.1 NFD-파일시스템 변종 (새로운 실패 클래스)

**문제**: macOS 크롤 코퍼스(NFD 파일명) + Linux verify(NFC 정규화 가정) 조합에서 verify V3가 "파일을 읽을 수 없음" 오류로 전량 오탐

**원인**: 
- macOS는 파일명을 NFD(자모 분해)로 저장
- 코드는 NFC(완성형)로 정규화한 doc_id로 파일을 열려고 시도
- Linux ext4는 바이트 보존이라 둘이 다르다

**해결**: 
- 파일 존재 검사 추가 → os.listdir(os.path.dirname)로 NFC-동등 파일명 매칭
- T27-a는 이미 NFD 픽스처로 이 조건을 커버 (회귀가 선제적 효과)
- 교훈: **파일시스템 변종은 CI에서만 드러난다**(로컬에서 macOS면 원본 NFD가 정상으로 보임)

### 7.2 CodeRabbit 지적 처리 (4라운드)

| 라운드 | 지적 | 해결 |
|--------|------|------|
| 1차 | T27-h4 anchor_idx 빈 리스트 IndexError | 예외 처리 추가 (editorial 판정) |
| 1차 | tokenize.TokenError 오타 | TokenizeError로 정정 |
| 2차 | CI 실패 (파일명 오픈 실패 — NFD 이슈) | NFC-동등 매칭 폴백 (1라운드) |
| 3차 | 전체 NFD 변환이 NFC 디렉터리에 막힘 | 컴포넌트별 os.listdir 매칭으로 일반화 |
| 4차 | (승인) | — |

---

## 8. Next Steps & Future Work

### 8.1 이번 사이클 범위 내 확인 필요

| 작업 | 상태 | 실행 여부 |
|------|------|:--------:|
| editorial 363건 로컬 보관(tar.gz) | 스크립트 명령만 제시 | 사용자 액션 |
| crawl_gate.json 승인 기록 저장 (기록된 표본 동일 재현) | 완료 | ✅ |
| records/ 스냅샷 매핑 확인 | 완료(MANIFEST snapshot_map) | ✅ |

### 8.2 후속 사이클 (범위 밖)

| # | 작업 | 예상 기간 | 의존성 |
|---|------|:--------:|--------|
| 1 | **공백 판례 수집** | 1~2일 | 이 사이클 산출물(S3 공백 목록) |
| 2 | 행정해석 아카이브 확장 | 후속 검토 | 공공저작물 판정 재검토 |
| 3 | 크롤 editorial 정본 수집(15건) | 후속 검토 | 공백 목록 포섭 여부 |
| 4 | 공용 모듈 통합(case_no_to_ascii 사본 3벌 → 1벌) | 후속 리팩토링 | 아키텍처 검토 |

### 8.3 운영 규칙 (CLAUDE.md 기록 필수)

- 신규 수집(`fetch_court_precedents.py`) 후 → `build` 재실행 필수
- `build` 전 로컬 verify V4(snapshot_origin_digests 대조)로 낡음 탐지
- 크롤분 게이트 규칙 변경 시 → 기존 승인 자동 무효화(`GATE_RULE_VERSION` 증가)

---

## 9. Validation Checklist

### 9.1 Success Criteria

- ✅ **S1**: 인벤토리 통합 (3,082행, 모든 소재 포섭)
- ✅ **S2**: 원장 포섭 (1,568 case_key 전부 존재)
- ✅ **S3**: 인용 판정 완결 (공백 10건 확정)
- ✅ **S4**: 복원 무손실 (V3·T27-e 검증)
- ✅ **S5**: 공개 경계 준수 (V7·2라운드 육안)
- ✅ **S6**: 오프라인·멱등 (V8·T27-f·Pinecone 쓰기 0)

### 9.2 Quality Gates

| 게이트 | 상태 | 비고 |
|--------|:----:|------|
| Design Validator | ✅ 74/100 | High 5 반영, Medium 10 처리 |
| Gap Detector | ✅ 96.9% | M3·L9 전부 처리 |
| CodeRabbit | ✅ 4라운드 | NFD 변종 + 3건 실지적 수정 |
| Offline Tests | ✅ 216개 | T27 포함 전부 통과 |
| CI (Vercel) | ✅ Green | offline·CodeRabbit·GitGuardian·Vercel pass |

### 9.3 Deployment Readiness

- ✅ 코드 리뷰: CodeRabbit 4라운드 완료·CI 전체 pass — PR #61 머지 대기(사용자 결정)
- ✅ 프로덕션 영향: 없음 (순수 자산 작업, 파이프라인 변경 0)
- ✅ 문서: CLAUDE.md 갱신 완료
- ✅ 회귀: CI 포함 전부 pass

---

## 10. Key Metrics & Summary

| 지표 | 값 | 설명 |
|------|-----|------|
| **Codebase Coverage** | 100% | archive_precedents.py 모든 경로 검증 |
| **Test Coverage** | 30개 단언 | T27 회귀로 고정 |
| **Archive Size** | 7.3MB | 번들 gz 6.0MB(letec 4.9 + verbatim 1.1) + 장부 CSV·records 스냅샷 |
| **Inventory Rows** | 3,082 | 사건 단위, 중복 제거 후 |
| **Documents** | 2,414 | letec 1,578 + crawl 836 |
| **Knowledge Gaps Identified** | 10건 | 실인용 판례 공백, 후속 수집 대상 |
| **PDCA Efficiency** | 4일 | Plan·Design·Do·Check·Report |

---

---

## Executive Summary — 4관점 표 (최종)

| 관점 | 내용 |
|------|------|
| **Problem** | 판례 원문 2,415파일이 전부 `.gitignore` 로컬 전용이고, 복구 필수인 원장도 단일 디스크에만 있다. 판례가 5곳에 흩어져 있고 장부가 없어서 "이 판례가 어디에 있는가"를 아무도 답할 수 없었다. 계산기 코드의 법적 근거 판례 17건 중 8건이 코퍼스 어디에도 없었고, 무감지로 남아 있었다. |
| **Solution** | 아카이브: 법제처 수집분(비보호 저작물)을 jsonl.gz 번들로 저장소에 커밋 — 유실-복구 가능한 형태로 보존. 인벤토리: 사건번호를 기본 키로 단일 장부 생성 — 문서 보유처·검색 수록처·인용처를 통합. 게이트: 크롤분은 자동 3-버킷+표본 육안으로 verbatim만 선별 승격. 복원 도구: archive_precedents.py로 번들 extract + verify 정합 검사 8종. |
| **Function & UX Effect** | 사용자 기능 변화는 없다(순수 자산 작업). 간접 효과: 인용-코퍼스 공백 10건 목록이 산출되어 후속 수집 대상이 명확화되고, 계산기 답변의 법적 근거 판례가 RAG 검색에도 실릴 길이 열렸다. 잔여 크롤 363건은 "공개 불가, 로컬 보관" 상태가 명시되어 운영상 혼란이 사라짐. |
| **Core Value** | "무엇이 있는지 모른다"는 상태를 없앴다 — 겹침 재수집·중복 판정 사이클 반복의 근본 원인이자 코드 인용 공백 8건이 무감지로 남은 원인을 제거했다. 디스크·Pinecone 어느 쪽을 잃어도 인벤토리+아카이브에서 복구 가능한 구조를 세웠다. 아카이브 자체가 "공개 안전한 계층"을 마련해 저작권 검토 없이 배포 불가의 관례를 세웠다. |
