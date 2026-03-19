# Project Rename: nodongok → laborconsult

> **Summary**: 프로젝트 식별자를 "nodongok"에서 "laborconsult"로 변경하고 전체 코드베이스에서 일괄 수정
>
> **Project**: laborconsult (구 laborconsult)
> **Author**: Claude
> **Date**: 2026-03-18
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 프로젝트명 "nodongok"이 서비스 정체성을 충분히 반영하지 못하며, 코드 전반에 하드코딩된 경로와 식별자가 산재 |
| **Solution** | "laborconsult"로 통합 리네이밍 — 소스코드, 문서, 설정 파일 일괄 수정 |
| **Function/UX Effect** | 외부 노출 서비스명이 "laborconsult"로 통일되어 브랜드 일관성 확보 |
| **Core Value** | 프로젝트 정체성 확립, 유지보수성 향상, 향후 도메인/배포 연동 기반 마련 |

---

## 1. Overview

### 1.1 Purpose

프로젝트 전반에서 "nodongok" 식별자를 제거하고 "laborconsult"로 교체하여 일관된 프로젝트 정체성을 확립한다.

### 1.2 Background

- 현재 폴더명: `laborconsult` (초기 크롤러 프로젝트에서 유래)
- 프로젝트가 RAG 챗봇 + 임금계산기 + 법률상담 서비스로 확장됨
- "boardcrawl"이라는 이름이 현재 서비스 범위를 반영하지 못함
- `nodong.kr`은 크롤링 대상 사이트 URL이므로 변경 대상이 아님

### 1.3 변경 대상 분류

| 유형 | 패턴 | 파일 수 | 변경 내용 |
|------|-------|---------|-----------|
| **A. Pinecone 인덱스명** | `nodongok-bestqna` 등 | 9개 | 환경변수 기본값 → `laborconsult` 접두어 |
| **B. 하드코딩 절대경로** | `/Users/.../laborconsult/` | 7개 | 상대경로로 전환 |
| **C. User-Agent 문자열** | `nodongok-chatbot/1.0` | 1개 | `laborconsult/1.0` |
| **D. 메타데이터 source** | `"source": "nodongok"` | 1개 (3곳) | `"source": "laborconsult"` |
| **E. CLAUDE.md** | 프로젝트 설명 | 1개 | 프로젝트명 갱신 |
| **F. PDCA 문서** | docs/ 내 참조 | ~60개 | `laborconsult` → `laborconsult` |
| **G. bkit 상태 파일** | .bkit/ JSON | ~10개 | 프로젝트 식별자 갱신 |
| **H. Claude 메모리** | .claude/ 메모리 | 2개 | 프로젝트명 갱신 |

---

## 2. Scope

### 2.1 In Scope

- [x] 소스코드 내 "nodongok" 식별자 → "laborconsult" 일괄 치환
- [x] 하드코딩 절대경로 → 상대경로 전환 (Path 안정성)
- [x] CLAUDE.md 프로젝트 설명 갱신
- [x] PDCA 문서 내 프로젝트명 참조 갱신
- [x] bkit 상태 파일 및 Claude 메모리 갱신

### 2.2 Out of Scope

- `nodong.kr` URL 참조 (크롤링 대상 사이트 — 변경 불가)
- 실제 Pinecone 인덱스 이름 변경 (인프라 작업 — 별도 마이그레이션 필요)
- Git 원격 저장소 이름 변경 (GitHub에서 별도 수행)
- 로컬 폴더명 변경 (`laborconsult/` → `laborconsult/` — 사용자 수동)
- Vercel 프로젝트 설정 변경

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 소스코드 .py 파일 내 "nodongok" 식별자 → "laborconsult" 치환 | High | Pending |
| FR-02 | 하드코딩 절대경로 7개 → `Path(__file__).parent` 또는 상대경로 전환 | High | Pending |
| FR-03 | CLAUDE.md 프로젝트 이름/설명 갱신 | High | Pending |
| FR-04 | docs/ 내 PDCA 문서 프로젝트명 참조 일괄 갱신 | Medium | Pending |
| FR-05 | .bkit/ 상태 파일 프로젝트 식별자 갱신 | Low | Pending |
| FR-06 | .claude/ 메모리 프로젝트명 갱신 | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement |
|----------|----------|-------------|
| 호환성 | 기존 Pinecone 인덱스 연결 유지 (환경변수 우선) | 챗봇 검색 동작 확인 |
| 안정성 | 하드코딩 경로 제거로 다른 환경에서도 실행 가능 | 상대경로 테스트 |
| 일관성 | grep "nodongok" 결과 0건 (nodong.kr 제외) | grep 검증 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] `grep -ri "nodongok" --include="*.py" | grep -v "nodong\.kr"` → 0건
- [ ] `grep -ri "laborconsult" CLAUDE.md` → 0건
- [ ] 기존 `wage_calculator_cli.py` 32개 테스트 통과
- [ ] `uvicorn api.index:app` 정상 기동

### 4.2 Quality Criteria

- [ ] `nodong.kr` URL 참조는 보존됨 (크롤링 대상 사이트)
- [ ] Pinecone 연결은 환경변수로 제어 (기본값만 변경)
- [ ] 절대경로 0개 (하드코딩 제거)

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Pinecone 인덱스 기본값 변경 시 기존 데이터 접근 불가 | High | Medium | 환경변수 `PINECONE_INDEX_NAME` 설정으로 기존 인덱스 유지. 기본값 변경은 코드에서만 |
| `nodong.kr` URL까지 실수로 변경 | Medium | Low | 치환 시 `nodong.kr` 명시적 제외 패턴 적용 |
| 문서 일괄 치환 시 의미 왜곡 | Low | Low | 문서는 프로젝트명 참조만 치환, 본문 내용은 보존 |
| 폴더명 미변경 시 CLAUDE.md와 실제 경로 불일치 | Medium | High | CLAUDE.md에 "laborconsult (구 laborconsult)" 병기, 폴더 변경은 사용자 수동 안내 |

---

## 6. Implementation Plan

### Phase 1: 소스코드 수정 (High Priority)

**1-1. Pinecone 인덱스명 기본값** (9개 파일)

| File | Old | New |
|------|-----|-----|
| `pinecone_upload.py` | `nodongok-bestqna` | `laborconsult-bestqna` |
| `pinecone_upload_legal.py` | `nodongok-bestqna` | `laborconsult-bestqna` |
| `pinecone_upload_counsel.py` | `nodongok-bestqna` | `laborconsult-bestqna` |
| `pinecone_upload_2025.py` | `nodongok-bestqna-2025` | `laborconsult-bestqna-2025` |
| `pinecone_upload_imgum.py` | `nodongok-imgum` | `laborconsult-imgum` |
| `upload_new_precedents.py` | `nodongok-bestqna` | `laborconsult-bestqna` |
| `test_precedent_search.py` | `nodongok-bestqna` | `laborconsult-bestqna` |
| `chatbot.py` | `nodongok-bestqna` | `laborconsult-bestqna` |
| `cleanup_remaining.py` | `nodongok-bestqna` | `laborconsult-bestqna` |

**1-2. User-Agent 및 메타데이터** (2개 파일)

| File | Old | New |
|------|-----|-----|
| `app/core/nlrc_cases.py` | `nodongok-chatbot/1.0` | `laborconsult/1.0` |
| `pinecone_upload_contextual.py` | `"source": "nodongok"` (3곳) | `"source": "laborconsult"` |

**1-3. 하드코딩 절대경로 → 상대경로** (6개 파일)

| File | Lines | Fix |
|------|-------|-----|
| `crawl_bestqna.py:17` | `OUTPUT_DIR = "/Users/.../output"` | `Path(__file__).parent / "output"` |
| `crawl_qna.py:22` | `DEFAULT_OUTPUT_DIR = "/Users/.../output_qna"` | `Path(__file__).parent / "output_qna"` |
| `analyze_qna.py:25-26` | 2개 경로 | 상대경로 전환 |
| `summarize_analysis.py:19-22` | 4개 경로 | 상대경로 전환 |
| `merge_analysis.py:18` | 1개 경로 | 상대경로 전환 |
| `cleanup_remaining.py:11` | 1개 경로 | 상대경로 전환 |

### Phase 2: CLAUDE.md 및 문서 갱신 (Medium Priority)

- CLAUDE.md: 프로젝트 이름을 "laborconsult"로 변경
- docs/ 내 ~60개 PDCA 문서에서 `laborconsult` → `laborconsult` 일괄 치환

### Phase 3: 상태 파일 정리 (Low Priority)

- `.bkit/state/pdca-status.json`: 프로젝트 식별자 갱신
- `.bkit/snapshots/`: 스냅샷 파일은 히스토리이므로 변경 불필요
- `.claude/agent-memory/`: 프로젝트명 참조 갱신

---

## 7. Next Steps

1. [ ] 이 Plan 승인 후 즉시 구현 시작
2. [ ] Phase 1 → Phase 2 → Phase 3 순서로 실행
3. [ ] 완료 후 `grep -ri "nodongok" | grep -v "nodong\.kr" | grep -v ".bkit/snapshots"` 으로 검증
4. [ ] 사용자에게 폴더명 변경 안내 (`mv laborconsult laborconsult`)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-18 | Initial draft | Claude |
