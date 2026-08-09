# precedent-corpus-followup Completion Report

> **Status**: Complete
>
> **Project**: laborconsult (한국 노동법 AI 상담 챗봇)
> **Version**: 1.0
> **Author**: DrunkenZealnut
> **Completion Date**: 2026-08-09
> **PDCA Cycle**: #2 (1일 단일 사이클, 선행: precedent-corpus-expansion)

---

## Executive Summary

### 1.1 Project Overview

| Item | Content |
|------|---------|
| Feature | 선행 사이클 후속 3트랙 — 프로덕션 검색 불가 유실 139건 복구(법제처 재수집) + 겹침 266건 쟁점 태깅 통일 + NFD 버그 봉인 |
| Duration | 2026-08-09 ~ 2026-08-09 (단일 일자, 선행과 연속) |
| Planning Phase | 완료 |
| Design Phase | 완료 |
| Implementation Phase | 완료 |
| Verification Phase | 완료 |

### 1.2 Results Summary

```
┌─────────────────────────────────────────────────────┐
│  Completion Rate: 100%                              │
├─────────────────────────────────────────────────────┤
│  ✅ Match Rate:       95% (≥90% 기준충족)            │
│  ✅ Files Changed:    11개 수정                      │
│  ✅ Lines Added:      +921 / −37                     │
│  ✅ Test Coverage:    84개 테스트 전부 통과          │
│  ✅ Vectors:          10,989 → 12,179 → 11,229      │
│  ✅ Data Collected:   274/286 (96%, 기존 미발견분)   │
│  ✅ Topic Enriched:   770건 태깅·통일               │
│  ✅ Commits:          e71f18c + 84b1c56 (PR #44)    │
└─────────────────────────────────────────────────────┘

Core Achievement:
- 파일 존재 ≠ 검색 가능의 구분 — 프로덕션 벡터 0개 유실군(139건) 회수
- 동일 판례 이중 히트(중복 벡터) 제거로 top-k 다양성 확보(950건 구벡터 삭제)
- NFD·16진법 폴백으로 재발 경로 차단 (T14~T16 회귀 25건)
```

### 1.3 Value Delivered

| Perspective | Content |
|-------------|---------|
| **Problem** | 선행 사이클이 겹침 266건을 "이미 코퍼스에 있음"으로 정당히 스킵했으나, 그 중 139건은 파일만 있고 프로덕션 벡터가 전혀 없어(미사용 `precedent` NS에만 업로드) 검색 불가다. 파일 존재는 안심이지만 검색 가능성은 별개. 나머지 127건도 쟁점 태그가 누락되고, 동일 판례 이중 히트로 순위 훼손 중. |
| **Solution** | 266건 전체를 법제처 API로 재수집해 검증된 기존 파이프라인(쟁점 태깅 → laborlaw-v2 업로드)으로 통일. 성공분의 기존 구벡터(127건)만 명시 ID로 삭제. NFD 버그는 정규식 확장 + NFC 정규화 + 45종 매핑으로 봉인, 조용한 폴백 제거. |
| **Function & UX Effect** | 최신 대법원 판례 139건(`2019두59349` 등)이 처음으로 검색 가능해지고, 교재 인용 판례 전체(~750건)가 동일 태그 체계로 통합. 프로덕션 E2E("채권추심원도...") 질의에서 신규 판례가 sources 상위 4건 차지. BM25 하이브리드 검색(점수 19.5) 확인. |
| **Core Value** | 선행 사이클이 남긴 갭 3종을 한 사이클에 완결 — 죽은 네임스페이스에 갇힌 표준 판례를 회수하고, 설계 원칙(벡터 ID 명시 제어·결정적 생성) 강화, 그리고 같은 실패의 재발 경로를 대무한 것으로 차단. 파일·벡터·삭제 3단 안전장치로 손실 불가능 구조 입증. |

---

## 2. 착수 조사 결과 (문제 재정의)

BM25 사본 전수 검증으로 겹침 266건의 실제 상태 파악:
- **139건**: `upload_new_precedents.py`가 `precedent` NS(프로덕션 미조회)에 업로드 → 검색 불가
- **127건**: ctx_precedent 벡터로 기존 검색되나, 쟁점 태그 누락 + 이중 히트 우려

선행 사이클의 중복 판정이 논리적으로 정당했으나, 파일 존재≠검색 가능이라는 구분이 누락된 맹점.

---

## 3. 단계별 수행 (Track 구분)

### Track A (NFD 버그 봉인)
- `pinecone_upload_legal.py::extract_post_id()`: NFC 정규화 + 45종 매핑(court_precedents 사본) + hex 폴백
- `upload_new_precedents.py`: 정규식 `[다두도가누]` → `[가-힣]{1,4}` + NFC 선행
- T14(NFD 파일명 11건), T14-e2(헌바), T14-g/h(hex 폴백) 회귀 추가

### Track B (유실 139건 복구 + 겹침 통일)
1. `sync_overlap_precedents.py --emit-targets`: 교재 ∩ 코퍼스 → _겹침대상.csv (286건, 추정 대비 +20)
2. `fetch_court_precedents.py --cases`: L2 생략 모드로 266건 재수집 → 274건 성공(96%), 12건 미발견
3. `enrich_court_precedents.py`: 신규분 자동 태깅 (770건)
4. `pinecone_upload_court_precedents.py`: precedent_{사건번호} ID로 업로드 → V1 12,179(정확)
5. `sync_overlap_precedents.py --delete-ctx`: 성공분 ctx 구벡터 950건 삭제 → V2 11,229(정확)
6. BM25 재빌드: 62,315문서(62,075+1,190−950 정확)

### Track C (F3 스파이크)
- portal.scourt.go.kr 접근성 판정: SPA 구조·헤드리스 차단 → **④ 영구 미수록 수용** (설계 §7)

---

## 4. 산출물 검증

| 산출물 | 결과 | 상태 |
|--------|------|------|
| 겹침 목록 재계산 | 286행(`_겹침대상.csv`) | ✅ CSV 파싱·게시글ID 매핑 일치 |
| 법제처 수집 | 274/286 (96%) | ✅ 정확일치 게이트, 실패 12건 ctx 보존 |
| 쟁점 태깅 | 770건 | ✅ enrich 무수정, 기존 파이프라인 재사용 |
| 벡터 업로드 | V0→V1 +1,190 | ✅ dry-run 청크수 − 1,901 = 신규분 일치 |
| 구벡터 삭제 | 950건 ID | ✅ _ctx_deleted.json 사전 기록, 라이브 prefix 재검증 |
| BM25 재빌드 | 62,315 문서 | ✅ (62,075+1,190−950) 수식 검증 완료 |
| 프로덕션 E2E | 신규 판례 sources 상위 4건 | ✅ "채권추심원도..." 질의 확인 |

---

## 5. 발견 사항 & 교훈

### 발견
1. **SDK `index.list()` 반환형 다형** (str/ListItem/ListResponse) — Do 중 런타임 발견, 예외 처리 추가
2. **BM25 qa 타임아웃** — 기존 gz 보존 로직이 폴백, 재시도 성공
3. **CodeRabbit 7건**: Critical 1(SDK ≥5.0.0), Major 3(hex 절단·미확인 삭제 게이트), Minor 3

### 교훈
1. **파일 존재는 검색 가능성 보장 아님** — 네임스페이스·벡터 생성 여부 확인 필수
2. **멱등성 설계의 가치** — 수집 실패분 ctx 유지로 "어떤 실패도 손실 아님" 구조 입증
3. **라이브 기준 원칙** — 로컬 gz 사본이 아니라 실행 시점 벡터 상태 직접 조회(`index.list()`)

---

## 6. 한계 & 후속

### 이번 범위 내 한계
- **미발견 12건**: 법제처 DB 미수록이나, ctx 벡터 보존으로 현상 유지 (손실 불가능)
- **F3 미발견 98건**: 설계 §7에서 ④ 수용 판정 (롱테일, 유료·수동 경로 대비 회수 낮음)

### 후속 과제 (우선순위)
- **F1/F2**: 이번 NFD 수정 외에도 기존 `precedent` NS 손상 추가 분석 (별도 판단)
- **교재 OCR 전처리**: 절 표제 인식율 개선(F5)

---

## 7. 완료 기준 체크 (Plan §6)

- [x] Track A: NFD 회귀 테스트 통과 (T14 11건, T14-e2/g/h 추가)
- [x] Track B: 유실 139건 중 확보분이 laborlaw-v2에서 검색 가능 (E2E 실증)
- [x] Track B: 성공분 ctx 구벡터 삭제 후 벡터 수 일치 (V1 12,179 → V2 11,229)
- [x] Track B: `data/bm25_corpus.json.gz` 재빌드·커밋
- [x] Track C: 후보 4종 판정 + 권고 기록 (설계 §7)

**최종 판정**: ✅ **전 항목 완료, Match Rate 95% ≥ 90%**

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-08-09 | PDCA 후속 사이클: 프로덕션 유실 139건 복구(재수집) + 겹침 266건 태깅 통일 + NFD 봉인. Match Rate 95%, 벡터 3단 검증(V0→V1→V2), 프로덕션 E2E 확인. 커밋 2개 +921/−37, 테스트 84건 통과 | DrunkenZealnut |
