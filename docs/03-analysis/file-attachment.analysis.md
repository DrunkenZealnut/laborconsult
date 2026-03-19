# file-attachment Analysis Report

> **Analysis Type**: Gap Analysis (Design vs Implementation)
>
> **Project**: laborconsult (AI 노동상담 챗봇)
> **Analyst**: gap-detector
> **Date**: 2026-03-06
> **Design Doc**: [file-attachment.design.md](../02-design/features/file-attachment.design.md)

---

## 1. Analysis Overview

### 1.1 Analysis Purpose

Design 문서(`docs/02-design/features/file-attachment.design.md`)의 섹션 2.1~2.6, 3~6과 실제 구현 코드를 1:1 비교하여 누락/불일치/추가 구현 항목을 식별한다.

### 1.2 Analysis Scope

- **Design Document**: `docs/02-design/features/file-attachment.design.md`
- **Implementation Files**:
  - `app/core/file_parser.py` (신규)
  - `app/models/schemas.py` (수정)
  - `app/core/pipeline.py` (수정)
  - `api/index.py` (수정)
  - `public/index.html` (수정)
  - `requirements.txt` (수정)
- **Analysis Date**: 2026-03-06

---

## 2. Gap Analysis (Design vs Implementation)

### 2.1 `app/core/file_parser.py` (Design Section 2.1)

| Design Item | Design Spec | Implementation | Status |
|-------------|-------------|----------------|--------|
| 상수 MAX_IMAGE_SIZE | 10MB | 10MB | ✅ Match |
| 상수 MAX_PDF_SIZE | 20MB | 20MB | ✅ Match |
| 상수 MAX_TEXT_SIZE | 1MB | 1MB | ✅ Match |
| 상수 MAX_PDF_PAGES | 20 | 20 | ✅ Match |
| 상수 MAX_ATTACHMENTS | 3 | 3 | ✅ Match |
| 상수 ALLOWED_IMAGE_TYPES | {jpeg, png, webp, gif} | {jpeg, png, webp, gif} | ✅ Match |
| 상수 ALLOWED_TEXT_TYPES | {text/plain, text/markdown} | {text/plain, text/markdown} | ✅ Match |
| 상수 ALLOWED_PDF_TYPES | {application/pdf} | {application/pdf} | ✅ Match |
| MAGIC_BYTES 정의 | jpeg/png/webp/gif/pdf | jpeg/png/webp/gif/pdf | ✅ Match |
| ParsedAttachment dataclass | filename, content_type, vision_block, extracted_text | filename, content_type, vision_block, extracted_text | ✅ Match |
| FileValidationError class | Exception 상속 | Exception 상속 | ✅ Match |
| validate_file() | 크기+매직바이트 검증 | 크기+매직바이트 검증 | ✅ Match |
| parse_image() | base64 인코딩 + Vision block | base64 인코딩 + Vision block | ✅ Match |
| parse_pdf() | PyPDF2 + 페이지 제한 + 텍스트 추출 | PyPDF2 + 페이지 제한 + 텍스트 추출 | ✅ Match |
| parse_text() | UTF-8 + EUC-KR fallback | UTF-8 + EUC-KR fallback | ✅ Match |
| parse_attachment() | 통합 파서 (검증+분기) | 통합 파서 (검증+분기) | ✅ Match |
| 텍스트 추출 제한 | 15,000자 (하드코딩) | MAX_EXTRACTED_CHARS = 15,000 (상수화) | ✅ Match |

**추가 구현 (Design에 없음)**:

| Item | Implementation Location | Description |
|------|------------------------|-------------|
| MAX_EXTRACTED_CHARS 상수 | file_parser.py:14 | Design에서는 15,000을 리터럴로 사용했으나 구현에서 상수로 추출. 개선 사항으로 긍정적 deviation. |

**Section 2.1 Match Rate**: 17/17 = **100%** (추가 항목은 개선이므로 감점 없음)

---

### 2.2 `app/models/schemas.py` (Design Section 2.2)

| Design Item | Design Spec | Implementation | Status |
|-------------|-------------|----------------|--------|
| ChatRequest 유지 | message, session_id | message, session_id | ✅ Match |
| Attachment 모델 | filename, content_type, data(str) | filename, content_type, data(str) | ✅ Match |
| Attachment docstring | "Base64 인코딩된 첨부파일" | "Base64 인코딩된 첨부파일" | ✅ Match |
| ChatWithFilesRequest 모델 | message, session_id, attachments(list) | message, session_id, attachments(list) | ✅ Match |
| ChatWithFilesRequest docstring | "파일 첨부 가능한 채팅 요청 (JSON body)" | "파일 첨부 가능한 채팅 요청" | ⚠️ Partial |

**Partial Item Details**:
- ChatWithFilesRequest docstring: Design은 "(JSON body)"를 명시했으나 구현에서는 생략. 기능 영향 없음.

**Section 2.2 Match Rate**: (4 + 0.5) / 5 = **90%**

---

### 2.3 `api/index.py` (Design Section 2.3)

| Design Item | Design Spec | Implementation | Status |
|-------------|-------------|----------------|--------|
| GET /api/chat/stream 유지 | 하위 호환 유지 | 유지됨 (L74-94) | ✅ Match |
| POST /api/chat/stream 추가 | ChatWithFilesRequest body | 구현됨 (L97-142) | ✅ Match |
| 첨부파일 개수 검증 | MAX_ATTACHMENTS 초과 시 에러 | 구현됨 (L108-109) | ✅ Match |
| base64 디코딩 | att.data → bytes | 구현됨 (L113) | ✅ Match |
| parse_attachment 호출 | 디코딩된 데이터로 파싱 | 구현됨 (L114) | ✅ Match |
| FileValidationError 처리 | SSE error 이벤트로 반환 | 구현됨 (L116-117, L126-128) | ✅ Match |
| session 이벤트 전송 | event_generator 첫 yield | 구현됨 (L124) | ✅ Match |
| process_question에 attachments 전달 | parsed_attachments 리스트 전달 | 구현됨 (L130-131) | ✅ Match |
| StreamingResponse 반환 | SSE media_type | 구현됨 (L134-142) | ✅ Match |
| 일반 Exception 처리 | Design에 명시 안 됨 | 구현됨 (L119-121) | ✅ Match |

**추가 구현 (Design에 없음)**:

| Item | Implementation Location | Description |
|------|------------------------|-------------|
| validation_error 변수 패턴 | api/index.py:105 | Design은 에러 이벤트 반환을 `...`으로 축약. 구현은 validation_error 변수를 사용한 깔끔한 에러 처리 패턴 적용. 개선 사항. |
| 일반 Exception catch | api/index.py:119-121 | base64 디코딩 실패 등 예상치 못한 오류에 대한 catch. Design은 "400 Bad Request"를 언급했으나 구현은 SSE error 이벤트로 일관성 있게 처리. |

**Section 2.3 Match Rate**: 9/9 = **100%** (추가 항목은 개선)

---

### 2.4 `app/core/pipeline.py` (Design Section 2.4)

| Design Item | Design Spec | Implementation | Status |
|-------------|-------------|----------------|--------|
| 시그니처 변경 | attachments: list[ParsedAttachment] \| None = None | attachments: list[ParsedAttachment] \| None = None (L232-233) | ✅ Match |
| (A) 첨부 텍스트 병합 | attachment_text 구성 + combined_query | 구현됨 (L242-253) | ✅ Match |
| (A) _extract_calc_params에 combined_query 전달 | combined_query 사용 | 구현됨 (L257) | ✅ Match |
| (B) RAG 검색 — query만 사용 | _search(query, config) | 구현됨 (L268) | ✅ Match |
| (C) Vision blocks 수집 | attachments에서 vision_block 추출 | 구현됨 (L294-298) | ✅ Match |
| (C) content_blocks 구성 | vision + text 블록 혼합 | 구현됨 (L300-305) | ✅ Match |
| (C) messages에 multi-content 추가 | messages.append({role:user, content:blocks}) | 구현됨 (L303) | ✅ Match |
| 기존 호출 하위 호환 | attachments=None 기본값 | 기본값 유지 | ✅ Match |
| 첨부 텍스트 컨텍스트 포함 | 3단계 컨텍스트에 attachment_text 병합 | 구현됨 (L285-286) | ✅ Match |

**추가 구현 (Design에 없음)**:

| Item | Implementation Location | Description |
|------|------------------------|-------------|
| has_attachments 분기 | pipeline.py:273-274 | 첨부파일만 있고 RAG 결과/계산기 결과 없을 때도 답변 생성 계속. Design에 미언급이나 합리적 로직. |
| vision_block 없을 때 plain text fallback | pipeline.py:304-305 | 이미지 첨부 없으면 기존 string content 방식 유지. Design은 항상 content_blocks를 사용하는 것처럼 기술했으나, 구현은 이미지가 없을 때 단순 string으로 최적화. |

**Section 2.4 Match Rate**: 9/9 = **100%**

---

### 2.5 `public/index.html` (Design Section 2.5)

#### CSS

| Design Item | Implementation | Status |
|-------------|----------------|--------|
| #attach-btn 스타일 | 구현됨 (L56-57) | ✅ Match |
| #file-preview 스타일 | 구현됨 (L49-50) | ✅ Match |
| .file-chip 스타일 | 구현됨 (L51-54) | ✅ Match |
| #drop-overlay 스타일 | 구현됨 (L64-65) | ✅ Match |
| #input-wrapper 래퍼 | Design에 없음, 구현에 추가 (L48) | ⚠️ Added |

#### HTML

| Design Item | Implementation | Status |
|-------------|----------------|--------|
| #file-preview div | 구현됨 (L96) | ✅ Match |
| #attach-btn 버튼 + SVG 아이콘 | 구현됨 (L98-101) | ✅ Match |
| file-input hidden | 구현됨 (L103) | ✅ Match |
| msg-input | 구현됨 (L104) | ✅ Match |
| send-btn | 구현됨 (L105) | ✅ Match |
| #drop-overlay | 구현됨 (L109) | ✅ Match |
| send-btn onclick="send()" | Design: onclick="send()" / 구현: addEventListener (L126) | ⚠️ Partial |
| 초기 인사 메시지에 첨부파일 안내 | Design에 없음 / 구현: "근로계약서, 급여명세서 등 파일을 첨부하면..." (L87) | ⚠️ Added |

#### JavaScript

| Design Item | Implementation | Status |
|-------------|----------------|--------|
| pendingFiles 상태 | 구현됨 (L122) | ✅ Match |
| MAX_FILES = 3 | 구현됨 (L123) | ✅ Match |
| DOM 요소 참조 (attachBtn, fileInput 등) | 구현됨 (L117-120) | ✅ Match |
| 파일 선택 이벤트 | 구현됨 (L131-134) | ✅ Match |
| 드래그앤드롭 | 구현됨 (L137-146) | ✅ Match |
| addFiles() 함수 | 구현됨 (L148-170) | ✅ Match |
| addFiles() 형식 검증 | 구현됨 (L154-157) | ✅ Match |
| addFiles() 크기 검증 | 구현됨 (L162-166) | ✅ Match |
| renderPreview() 함수 | 구현됨 (L172-193) | ✅ Match |
| renderPreview() 이미지 썸네일 | 구현됨 (L177-180) | ✅ Match |
| renderPreview() 파일 크기 표시 | 구현됨 (L183-184) | ✅ Match |
| renderPreview() 삭제 버튼 | 구현됨 (L186-189) | ✅ Match |
| fileToBase64() 함수 | 구현됨 (L195-202) | ✅ Match |
| send() 빈 입력 체크 | 구현됨 (L363) | ✅ Match |
| send() 사용자 메시지에 파일명 표시 | 구현됨 (L366-372) | ✅ Match |
| send() base64 인코딩 루프 | 구현됨 (L375-382) | ✅ Match |
| send() 상태 초기화 | 구현됨 (L384-387) | ✅ Match |
| send() POST (파일 있음) | 구현됨 (L391-400) | ✅ Match |
| send() GET (파일 없음) | 구현됨 (L401-404) | ✅ Match |
| SSE 읽기 로직 | 구현됨 (readSSE 함수, L318-357) | ✅ Match |

**변경/추가 구현 (Design 대비)**:

| Item | Implementation Location | Description |
|------|------------------------|-------------|
| #input-wrapper 래퍼 div | index.html:95 | file-preview와 input-area를 감싸는 래퍼. Design에 미언급이나 CSS 구조 개선. |
| 드래그앤드롭 dragCounter 패턴 | index.html:137-139 | Design은 relatedTarget === null 체크. 구현은 dragCounter 패턴으로 더 안정적. |
| readSSE 함수 분리 | index.html:318-357 | Design은 send() 내에 SSE 읽기를 인라인으로 기술. 구현은 readSSE() 별도 함수로 분리. 코드 품질 개선. |
| error 이벤트 UI 처리 | index.html:343-344 | Design은 SSE error 이벤트를 정의했으나 프론트 처리 로직 미기술. 구현에서 처리 완성. |
| remove 버튼 문자 | Design: 'x' / 구현: '\u00d7' (multiplication sign) | 미세한 차이, UX 개선. |
| 초기 인사 메시지에 파일 첨부 안내 | index.html:87 | UX 개선으로 사용자가 파일 첨부 가능 여부를 인지할 수 있게 함. |

**Section 2.5 Match Rate**: (22 + 0.5) / 24 = **93.8%**

---

### 2.6 `requirements.txt` (Design Section 2.6)

| Design Item | Implementation | Status |
|-------------|----------------|--------|
| PyPDF2>=3.0.0 | PyPDF2>=3.0.0 (L12) | ✅ Match |
| python-multipart>=0.0.9 | python-multipart>=0.0.9 (L13) | ✅ Match |

**Section 2.6 Match Rate**: 2/2 = **100%**

---

### 2.7 Data Flow (Design Section 3)

| Design Flow Item | Implementation | Status |
|------------------|----------------|--------|
| GET 경로: query param -> process_question | api/index.py GET 엔드포인트 유지 | ✅ Match |
| POST 경로: JSON body -> parse -> process_question | api/index.py POST 엔드포인트 | ✅ Match |
| Step 1: 임금계산기 추출에 attachment_text 병합 | pipeline.py combined_query 사용 | ✅ Match |
| Step 2: RAG 검색은 query만 사용 | pipeline.py _search(query, config) | ✅ Match |
| Step 3: Vision block + text 혼합 messages | pipeline.py content_blocks 구성 | ✅ Match |

**Section 3 Match Rate**: 5/5 = **100%**

---

### 2.8 Error Handling (Design Section 4)

| Error Scenario | Design Handling | Implementation | Status |
|----------------|-----------------|----------------|--------|
| 지원하지 않는 파일 형식 | Client: alert + 차단 / Server: SSE error | Client: alert (index.html:159) / Server: FileValidationError -> SSE error | ✅ Match |
| 파일 크기 초과 | Client: alert + 차단 / Server: SSE error | Client: alert (index.html:163-165) / Server: FileValidationError -> SSE error | ✅ Match |
| PDF 페이지 초과 (>20) | Server: FileValidationError -> SSE error | file_parser.py:92-96 -> api/index.py SSE error | ✅ Match |
| PDF 텍스트 추출 실패 | Server: "이미지 파일로 첨부해 주세요" 안내 | file_parser.py:106-109 | ✅ Match |
| 텍스트 인코딩 인식 불가 | Server: FileValidationError -> SSE error | file_parser.py:127-128 | ✅ Match |
| base64 디코딩 실패 | Server: 400 Bad Request | Server: SSE error 이벤트 (api/index.py:119-121) | ⚠️ Partial |
| SSE 에러 이벤트 형식 | {"type":"error","text":"..."} | api/index.py:127 json.dumps({'type':'error','text':...}) | ✅ Match |

**Partial Item Details**:
- base64 디코딩 실패: Design은 "400 Bad Request"를 명시했으나, 구현은 일반 Exception catch로 SSE error 이벤트 전달. 사용자 경험 측면에서는 구현이 더 일관적 (SSE 스트림 내에서 에러 전달). 기능적 차이는 있으나 개선된 방향.

**Section 4 Match Rate**: (6 + 0.5) / 7 = **92.9%**

---

### 2.9 Backward Compatibility (Design Section 6)

| Design Item | Implementation | Status |
|-------------|----------------|--------|
| GET /api/chat/stream 유지 | 유지됨 (api/index.py:74-94) | ✅ Match |
| process_question 기존 호출 호환 | attachments=None 기본값 | ✅ Match |
| ChatRequest 모델 유지 | 유지됨 (schemas.py:6-8) | ✅ Match |
| 파일 없이 텍스트만 전송 시 기존 동작 | GET fallback (index.html:401-404) | ✅ Match |

**Section 6 Match Rate**: 4/4 = **100%**

---

## 3. Summary Tables

### 3.1 Missing Features (Design O, Implementation X)

| Item | Design Location | Description |
|------|-----------------|-------------|
| (없음) | - | 모든 Design 항목이 구현됨 |

### 3.2 Added Features (Design X, Implementation O)

| Item | Implementation Location | Description | Impact |
|------|------------------------|-------------|--------|
| MAX_EXTRACTED_CHARS 상수 | file_parser.py:14 | 매직 넘버를 상수로 추출 | Low (긍정적) |
| #input-wrapper 래퍼 | index.html:95 | CSS 구조 개선 | Low (긍정적) |
| dragCounter 드래그 패턴 | index.html:137-139 | relatedTarget 대신 counter 패턴 사용, 더 안정적 | Low (긍정적) |
| readSSE() 함수 분리 | index.html:318-357 | SSE 읽기 로직을 send()에서 분리 | Low (긍정적) |
| error 이벤트 UI 처리 | index.html:343-344 | SSE error 이벤트의 프론트 표시 로직 | Low (긍정적) |
| has_attachments 분기 | pipeline.py:273-274 | 첨부만 있고 RAG/계산기 없을 때 처리 | Low (긍정적) |
| vision_block 없을 때 string fallback | pipeline.py:304-305 | 불필요한 content_blocks 래핑 방지 | Low (긍정적) |
| validation_error 패턴 | api/index.py:105 | 에러 처리 구조화 | Low (긍정적) |
| 일반 Exception catch | api/index.py:119-121 | 예상치 못한 오류 방어 | Low (긍정적) |
| 초기 인사 메시지 첨부 안내 | index.html:87 | 사용자 UX 향상 | Low (긍정적) |

### 3.3 Changed Features (Design != Implementation)

| Item | Design | Implementation | Impact |
|------|--------|----------------|--------|
| ChatWithFilesRequest docstring | "파일 첨부 가능한 채팅 요청 (JSON body)" | "파일 첨부 가능한 채팅 요청" | Low |
| send-btn 이벤트 바인딩 | onclick="send()" 인라인 | addEventListener (L126) | Low (긍정적) |
| base64 디코딩 실패 처리 | 400 Bad Request | SSE error 이벤트 | Low (개선된 방향) |
| 드래그 leave 감지 방식 | relatedTarget === null | dragCounter 패턴 | Low (개선된 방향) |
| remove 버튼 문자 | 'x' | '\u00d7' (multiplication sign) | Negligible |

---

## 4. Match Rate Summary

### 4.1 Section-wise Match Rate

| Section | Design Items | Match | Partial | Missing | Match Rate |
|---------|:-----------:|:-----:|:-------:|:-------:|:----------:|
| 2.1 file_parser.py | 17 | 17 | 0 | 0 | 100.0% |
| 2.2 schemas.py | 5 | 4 | 1 | 0 | 90.0% |
| 2.3 api/index.py | 9 | 9 | 0 | 0 | 100.0% |
| 2.4 pipeline.py | 9 | 9 | 0 | 0 | 100.0% |
| 2.5 index.html | 24 | 22 | 1 | 0 | 93.8% |
| 2.6 requirements.txt | 2 | 2 | 0 | 0 | 100.0% |
| 3. Data Flow | 5 | 5 | 0 | 0 | 100.0% |
| 4. Error Handling | 7 | 6 | 1 | 0 | 92.9% |
| 6. Backward Compat. | 4 | 4 | 0 | 0 | 100.0% |

### 4.2 Overall Match Rate

```
Total Design Items: 82
  Match:    78
  Partial:   3  (x0.5 = 1.5)
  Missing:   0

Match Rate = (78 + 1.5) / 82 * 100 = 96.95%
```

```
+-------------------------------------------------+
|  Overall Match Rate: 97%                        |
+-------------------------------------------------+
|  Match:          78 items (95.1%)               |
|  Partial:         3 items ( 3.7%)               |
|  Missing:         0 items ( 0.0%)               |
|  Added (impl):   10 items (all positive)        |
+-------------------------------------------------+
```

---

## 5. Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| Design Match | 97% | ✅ |
| Architecture Compliance | 100% | ✅ |
| Convention Compliance | 95% | ✅ |
| **Overall** | **97%** | ✅ |

**Architecture Compliance Notes**:
- 레이어 구분 준수: file_parser(core) -> schemas(models) -> pipeline(core) -> index(api) -> index.html(presentation)
- 의존성 방향 정확: api -> file_parser, api -> pipeline -> file_parser
- 파싱은 API 레이어에서 수행, pipeline에는 ParsedAttachment만 전달 (Design 의도와 일치)

**Convention Compliance Notes**:
- 파일명: snake_case.py (Python 컨벤션 준수)
- 함수명: snake_case (Python 컨벤션 준수)
- 상수: UPPER_SNAKE_CASE 준수
- import 순서: 표준 라이브러리 -> 외부 패키지 -> 프로젝트 내부 (준수)
- docstring: 한국어 통일 (프로젝트 컨벤션)
- -5%: ChatWithFilesRequest docstring 미세 불일치

---

## 6. Intentional Deviations

다음 항목은 Design 대비 의도적으로 변경/추가된 것으로 Gap이 아닌 개선 사항이다:

| # | Item | Reason | Assessment |
|---|------|--------|------------|
| 1 | MAX_EXTRACTED_CHARS 상수 추출 | 매직 넘버 제거, 유지보수성 향상 | 긍정적 |
| 2 | readSSE() 함수 분리 | DRY 원칙, 코드 재사용성 향상 | 긍정적 |
| 3 | dragCounter 패턴 | relatedTarget null 체크보다 안정적 | 긍정적 |
| 4 | base64 실패 시 SSE error | HTTP 400 대신 SSE 일관성 유지 | 긍정적 |
| 5 | has_attachments 분기 추가 | 첨부만 있을 때 조기 종료 방지 | 긍정적 |
| 6 | vision_block 없으면 string content | 불필요한 content_blocks 래핑 방지, API 호환성 | 긍정적 |
| 7 | 초기 인사 메시지 첨부 안내 | 사용자가 기능 존재를 인지할 수 있도록 | 긍정적 |

---

## 7. Recommended Actions

### 7.1 Design Document Update (선택)

| Priority | Item | Location | Action |
|----------|------|----------|--------|
| Low | ChatWithFilesRequest docstring 통일 | design.md:216 | "(JSON body)" 삭제하여 구현과 일치시키거나, 구현에 "(JSON body)" 추가 |
| Low | base64 실패 에러 처리 방식 | design.md:587 | "400 Bad Request" -> "SSE error 이벤트"로 수정 |
| Low | 드래그 leave 처리 | design.md:402-404 | dragCounter 패턴으로 업데이트 |
| Low | readSSE 분리 반영 | design.md:530 | SSE 읽기 코드를 별도 함수로 기술 |

### 7.2 Immediate Actions

없음. Match Rate 97%로 Design과 Implementation이 매우 잘 일치함.

---

## 8. Conclusion

Match Rate **97%**로 Design 문서와 실제 구현 코드가 매우 높은 수준으로 일치한다. 누락된 기능은 **0건**이며, 3건의 Partial 항목은 모두 docstring 미세 차이 또는 에러 처리 방식의 개선적 변경이다. 추가 구현된 10개 항목은 모두 코드 품질/UX를 개선하는 방향의 긍정적 deviation이다.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-06 | Initial gap analysis | gap-detector |
