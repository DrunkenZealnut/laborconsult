# Plan: file-attachment

> 이미지, PDF, TXT 파일을 첨부하면 읽어들여 질문 데이터로 활용하는 기능

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | file-attachment (파일 첨부 질문) |
| 시작일 | 2026-03-06 |
| 예상 기간 | 2-3일 |

| 관점 | 설명 |
|------|------|
| Problem | 사용자가 근로계약서, 급여명세서 등 문서를 직접 텍스트로 옮겨야 해서 질문이 불편하고 정보 누락이 발생함 |
| Solution | 이미지/PDF/TXT 파일 업로드 후 자동 텍스트 추출하여 질문 컨텍스트로 활용 |
| Function UX Effect | 파일 첨부 버튼 클릭 또는 드래그앤드롭으로 문서를 바로 전송, 추출된 내용 기반 정확한 답변 제공 |
| Core Value | 근로계약서/급여명세서 원본 기반 상담으로 정보 정확도 향상 및 사용자 편의성 대폭 개선 |

## 1. 배경 및 목적

### 1.1 현재 상태
- 사용자는 텍스트로만 질문 가능
- 근로계약서, 급여명세서 등 문서 내용을 직접 타이핑해야 함
- 정보 누락/오기가 빈번하여 부정확한 답변 유발

### 1.2 목표
- 이미지(JPG/PNG), PDF, TXT 파일 첨부 지원
- 파일에서 텍스트를 자동 추출하여 질문과 함께 LLM에 전달
- 기존 RAG + 임금계산기 파이프라인과 자연스럽게 통합

## 2. 지원 파일 형식 및 처리 방식

| 파일 형식 | 처리 방식 | 라이브러리/API |
|-----------|-----------|---------------|
| 이미지 (JPG/PNG/WEBP) | Claude Vision API (base64 인코딩) | anthropic SDK (기존) |
| PDF | 텍스트 추출 | PyPDF2 또는 pdfplumber |
| TXT/MD | 직접 읽기 | 내장 (utf-8) |

### 2.1 제한 사항
- **파일 크기**: 최대 10MB (이미지), 20MB (PDF), 1MB (TXT)
- **PDF 페이지**: 최대 20페이지
- **동시 첨부**: 최대 3개 파일
- **이미지 해상도**: Claude Vision 제한 따름 (최대 ~20MP)

## 3. 아키텍처 변경

### 3.1 Frontend (public/index.html)
- 파일 첨부 버튼 추가 (클립 아이콘)
- 드래그 앤 드롭 지원
- 파일 미리보기 (이미지 썸네일, 파일명+크기 표시)
- 첨부 파일과 텍스트 메시지를 `multipart/form-data` 또는 base64 JSON으로 전송

### 3.2 Backend API (api/index.py)
- `POST /api/chat/stream` 엔드포인트 수정 (현재 GET → POST 전환 또는 별도 엔드포인트)
- 파일 업로드 수신 및 validation (형식, 크기)
- 파일별 텍스트 추출 라우팅

### 3.3 Pipeline (app/core/pipeline.py)
- `process_question()` 시그니처 확장: `attachments` 파라미터 추가
- 이미지: Claude messages API의 `image` content block으로 직접 전달
- PDF/TXT: 추출된 텍스트를 질문 컨텍스트에 추가
- 기존 RAG 검색 + 임금계산기 흐름 유지

### 3.4 새로운 모듈
- `app/core/file_parser.py` — 파일 형식별 텍스트 추출 로직
  - `parse_image(data: bytes) -> dict` — base64 인코딩 + content block 생성
  - `parse_pdf(data: bytes) -> str` — PDF 텍스트 추출
  - `parse_text(data: bytes) -> str` — UTF-8 디코딩

## 4. 데이터 흐름

```
사용자 → [파일 + 질문 텍스트]
         ↓
   API 엔드포인트 (파일 수신 + validation)
         ↓
   file_parser.py (형식별 텍스트 추출)
         ↓
   pipeline.py:process_question()
     ├─ 이미지 → Claude Vision content block으로 직접 전달
     ├─ PDF/TXT 추출 텍스트 → 질문 컨텍스트에 병합
     ├─ 임금계산기 파라미터 추출 (추출 텍스트 포함)
     ├─ RAG 검색 (질문 텍스트 기반)
     └─ Claude 스트리밍 답변 생성
```

## 5. 의존성 추가

| 패키지 | 용도 | 비고 |
|--------|------|------|
| PyPDF2 | PDF 텍스트 추출 | 가볍고 순수 Python |
| python-multipart | FastAPI 파일 업로드 | FastAPI UploadFile 지원에 필요 |

## 6. 보안 고려사항

- 파일 형식 검증: Content-Type + 매직 바이트 확인 (확장자만 믿지 않음)
- 파일 크기 제한 서버사이드 강제
- 업로드 파일 디스크 저장 안 함 (메모리에서 처리 후 폐기)
- 악성 PDF 방어: PyPDF2는 JavaScript 실행 없는 순수 파서
- 개인정보: 파일 내용을 로깅하지 않음

## 7. 구현 우선순위

1. **P0**: `file_parser.py` — 파일별 텍스트 추출 핵심 로직
2. **P0**: API 엔드포인트 — 파일 업로드 수신
3. **P0**: `pipeline.py` — attachments 통합
4. **P1**: Frontend — 파일 첨부 UI + 전송 로직
5. **P2**: 드래그앤드롭, 미리보기 등 UX 개선

## 8. 성공 기준

- [ ] JPG/PNG 이미지 첨부 시 Claude Vision으로 내용 인식 후 답변 생성
- [ ] PDF 첨부 시 텍스트 추출 후 질문 컨텍스트로 활용
- [ ] TXT 첨부 시 내용을 질문에 포함하여 답변
- [ ] 기존 텍스트 전용 질문 흐름에 영향 없음 (하위 호환)
- [ ] 파일 크기/형식 제한 초과 시 사용자에게 명확한 에러 메시지
