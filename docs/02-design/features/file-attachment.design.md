# Design: file-attachment

> Plan 문서 참조: `docs/01-plan/features/file-attachment.plan.md`

## 1. 변경 파일 목록

| 파일 | 변경 유형 | 설명 |
|------|-----------|------|
| `app/core/file_parser.py` | 신규 | 파일 형식별 파싱 (이미지/PDF/TXT) |
| `api/index.py` | 수정 | POST 스트리밍 엔드포인트 추가, 파일 업로드 수신 |
| `app/core/pipeline.py` | 수정 | `process_question()` attachments 파라미터 추가, Claude Vision 통합 |
| `app/models/schemas.py` | 수정 | `Attachment` 모델 추가 |
| `public/index.html` | 수정 | 파일 첨부 UI, 드래그앤드롭, 미리보기, POST 전송 |
| `requirements.txt` | 수정 | PyPDF2, python-multipart 추가 |

## 2. 상세 설계

### 2.1 `app/core/file_parser.py` (신규)

```python
"""파일 첨부 파싱 — 이미지/PDF/TXT에서 텍스트 또는 Vision 블록 추출"""

import base64
import io
from dataclasses import dataclass

# ── 상수 ──────────────────────────────────────────────────────────────────────

MAX_IMAGE_SIZE = 10 * 1024 * 1024   # 10MB
MAX_PDF_SIZE = 20 * 1024 * 1024     # 20MB
MAX_TEXT_SIZE = 1 * 1024 * 1024     # 1MB
MAX_PDF_PAGES = 20
MAX_ATTACHMENTS = 3

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_TEXT_TYPES = {"text/plain", "text/markdown"}
ALLOWED_PDF_TYPES = {"application/pdf"}

# 매직 바이트 검증
MAGIC_BYTES = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/webp": [b"RIFF"],       # RIFF....WEBP
    "image/gif": [b"GIF87a", b"GIF89a"],
    "application/pdf": [b"%PDF"],
}


@dataclass
class ParsedAttachment:
    """파싱된 첨부파일 결과"""
    filename: str
    content_type: str
    # 이미지: Claude Vision content block dict
    # PDF/TXT: 추출된 텍스트
    vision_block: dict | None = None   # {"type": "image", "source": {...}}
    extracted_text: str | None = None


class FileValidationError(Exception):
    """파일 검증 실패"""
    pass


# ── 검증 ──────────────────────────────────────────────────────────────────────

def validate_file(data: bytes, content_type: str, filename: str) -> None:
    """파일 크기 + 매직 바이트 검증. 실패 시 FileValidationError raise."""

    # 크기 검증
    if content_type in ALLOWED_IMAGE_TYPES:
        if len(data) > MAX_IMAGE_SIZE:
            raise FileValidationError(f"이미지 파일은 10MB 이하만 가능합니다. ({filename})")
    elif content_type in ALLOWED_PDF_TYPES:
        if len(data) > MAX_PDF_SIZE:
            raise FileValidationError(f"PDF 파일은 20MB 이하만 가능합니다. ({filename})")
    elif content_type in ALLOWED_TEXT_TYPES:
        if len(data) > MAX_TEXT_SIZE:
            raise FileValidationError(f"텍스트 파일은 1MB 이하만 가능합니다. ({filename})")
    else:
        raise FileValidationError(
            f"지원하지 않는 파일 형식입니다: {content_type} ({filename}). "
            "이미지(JPG/PNG/WEBP/GIF), PDF, TXT 파일만 가능합니다."
        )

    # 매직 바이트 검증 (텍스트 파일 제외)
    if content_type in MAGIC_BYTES:
        prefixes = MAGIC_BYTES[content_type]
        if not any(data[:len(p)] == p for p in prefixes):
            raise FileValidationError(
                f"파일 내용이 확장자와 일치하지 않습니다. ({filename})"
            )


# ── 파싱 ──────────────────────────────────────────────────────────────────────

def parse_image(data: bytes, content_type: str, filename: str) -> ParsedAttachment:
    """이미지 → Claude Vision content block (base64)"""
    # content_type에서 media_type 추출 (예: "image/jpeg")
    media_type = content_type.split(";")[0].strip()
    b64 = base64.standard_b64encode(data).decode("ascii")

    return ParsedAttachment(
        filename=filename,
        content_type=content_type,
        vision_block={
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": b64,
            },
        },
    )


def parse_pdf(data: bytes, filename: str) -> ParsedAttachment:
    """PDF → 텍스트 추출 (PyPDF2)"""
    from PyPDF2 import PdfReader

    reader = PdfReader(io.BytesIO(data))

    if len(reader.pages) > MAX_PDF_PAGES:
        raise FileValidationError(
            f"PDF는 {MAX_PDF_PAGES}페이지 이하만 가능합니다. "
            f"({filename}: {len(reader.pages)}페이지)"
        )

    pages_text = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages_text.append(f"[{i+1}페이지]\n{text.strip()}")

    extracted = "\n\n".join(pages_text)
    if not extracted.strip():
        raise FileValidationError(
            f"PDF에서 텍스트를 추출할 수 없습니다. 스캔된 이미지 PDF라면 이미지 파일로 첨부해 주세요. ({filename})"
        )

    # 텍스트가 너무 긴 경우 잘라냄 (약 15,000자 = Claude 컨텍스트 부담 방지)
    if len(extracted) > 15000:
        extracted = extracted[:15000] + f"\n\n... (이하 생략, 총 {len(extracted):,}자)"

    return ParsedAttachment(
        filename=filename,
        content_type="application/pdf",
        extracted_text=extracted,
    )


def parse_text(data: bytes, filename: str) -> ParsedAttachment:
    """TXT/MD → UTF-8 디코딩"""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("euc-kr")
        except UnicodeDecodeError:
            raise FileValidationError(f"텍스트 파일 인코딩을 인식할 수 없습니다. ({filename})")

    if len(text) > 15000:
        text = text[:15000] + f"\n\n... (이하 생략, 총 {len(text):,}자)"

    return ParsedAttachment(
        filename=filename,
        content_type="text/plain",
        extracted_text=text,
    )


# ── 통합 파서 ─────────────────────────────────────────────────────────────────

def parse_attachment(data: bytes, content_type: str, filename: str) -> ParsedAttachment:
    """파일 데이터를 받아 검증 + 파싱하여 ParsedAttachment 반환"""
    validate_file(data, content_type, filename)

    if content_type in ALLOWED_IMAGE_TYPES:
        return parse_image(data, content_type, filename)
    elif content_type in ALLOWED_PDF_TYPES:
        return parse_pdf(data, filename)
    elif content_type in ALLOWED_TEXT_TYPES:
        return parse_text(data, filename)
    else:
        raise FileValidationError(f"지원하지 않는 파일 형식입니다: {content_type}")
```

**설계 결정**:
- `ParsedAttachment` 데이터클래스로 이미지(vision_block)와 텍스트(extracted_text)를 통합 표현
- 이미지는 Claude Vision content block 형태로 직접 생성 → pipeline에서 messages API에 그대로 삽입
- PDF/TXT는 텍스트로 추출 → 질문 컨텍스트에 문자열로 병합
- 매직 바이트 검증으로 확장자 위조 방어
- EUC-KR fallback으로 한국어 레거시 텍스트 파일 지원
- 추출 텍스트 15,000자 제한으로 컨텍스트 폭발 방지

### 2.2 `app/models/schemas.py` (수정)

```python
"""요청/응답 스키마"""

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class Attachment(BaseModel):
    """Base64 인코딩된 첨부파일"""
    filename: str
    content_type: str
    data: str   # base64 encoded


class ChatWithFilesRequest(BaseModel):
    """파일 첨부 가능한 채팅 요청 (JSON body)"""
    message: str
    session_id: str | None = None
    attachments: list[Attachment] = []
```

**설계 결정**:
- `multipart/form-data` 대신 **JSON + base64** 방식 채택
  - 이유: SSE 스트리밍과 조합이 간단, Vercel 서버리스 호환성 우수, 프론트엔드 구현 단순
  - trade-off: base64 인코딩으로 ~33% 크기 증가 → 이미지 10MB 제한으로 충분히 감당 가능
- 기존 `ChatRequest`는 하위 호환을 위해 유지

### 2.3 `api/index.py` (수정)

기존 `GET /api/chat/stream` 유지 (하위 호환) + 새 `POST /api/chat/stream` 추가:

```python
# 기존 GET 엔드포인트 유지 (하위 호환)
@app.get("/api/chat/stream")
def chat_stream(message: str, session_id: str | None = None):
    # ... 기존 코드 그대로 ...


# 새 POST 엔드포인트 — 파일 첨부 지원
@app.post("/api/chat/stream")
def chat_stream_with_files(req: ChatWithFilesRequest):
    """SSE 스트리밍 응답 — 파일 첨부 지원"""
    config = get_config()
    session = get_or_create_session(req.session_id)

    # 첨부파일 파싱
    parsed_attachments = []
    if req.attachments:
        if len(req.attachments) > MAX_ATTACHMENTS:
            # 에러 이벤트 반환
            ...
        for att in req.attachments:
            data = base64.b64decode(att.data)
            parsed = parse_attachment(data, att.content_type, att.filename)
            parsed_attachments.append(parsed)

    def event_generator():
        yield f"data: {json.dumps({'type': 'session', 'session_id': session.id})}\n\n"

        for event in process_question(req.message, session, config,
                                       attachments=parsed_attachments):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), ...)
```

**설계 결정**:
- GET과 POST 양쪽 지원으로 하위 호환 보장
- 파일 파싱은 API 레이어에서 수행, pipeline에는 `ParsedAttachment` 리스트만 전달
- `FileValidationError`는 SSE 에러 이벤트로 클라이언트에 전달

### 2.4 `app/core/pipeline.py` (수정)

`process_question()` 시그니처 변경 및 내부 로직 수정:

```python
def process_question(query: str, session: Session, config: AppConfig,
                     attachments: list[ParsedAttachment] | None = None):
```

**변경 포인트 3곳**:

#### (A) 임금계산기 파라미터 추출 — 첨부 텍스트 포함

```python
# 첨부파일에서 추출된 텍스트를 질문에 병합
attachment_text = ""
if attachments:
    text_parts = []
    for att in attachments:
        if att.extracted_text:
            text_parts.append(f"[첨부: {att.filename}]\n{att.extracted_text}")
    attachment_text = "\n\n".join(text_parts)

combined_query = query
if attachment_text:
    combined_query = f"{query}\n\n첨부된 문서 내용:\n{attachment_text}"

params = _extract_calc_params(combined_query, config.claude_client)
```

#### (B) RAG 검색 — 질문 텍스트만 사용 (첨부 텍스트 제외)

```python
# RAG 검색은 사용자 질문 텍스트만으로 수행 (첨부 텍스트는 노이즈)
hits = _search(query, config)
```

#### (C) Claude 스트리밍 답변 — Vision 블록 + 텍스트 통합

```python
# messages 구성: 이미지는 Vision content block, 텍스트는 text content block
content_blocks = []

# 이미지 첨부 → Vision content block
if attachments:
    for att in attachments:
        if att.vision_block:
            content_blocks.append(att.vision_block)

# 텍스트 컨텍스트 (RAG + 계산기 + 질문 + 첨부 텍스트)
content_blocks.append({"type": "text", "text": user_message})

messages = session.recent()
messages.append({"role": "user", "content": content_blocks})
```

**설계 결정**:
- `attachments=None` 기본값으로 기존 호출 코드에 영향 없음
- 이미지는 Claude Vision API의 multi-content 형식 활용 (text + image 블록 혼합)
- PDF/TXT 추출 텍스트는 임금계산기 파라미터 추출에도 포함 (급여명세서에서 숫자 추출 가능)
- RAG 검색은 사용자 질문 텍스트만 사용 (첨부 문서 전문은 검색 쿼리로 부적합)

### 2.5 `public/index.html` (수정)

#### CSS 추가

```css
/* 파일 첨부 */
#attach-btn { background: none; border: 1px solid var(--border); border-radius: 8px;
  padding: 10px; cursor: pointer; font-size: 18px; color: var(--muted);
  display: flex; align-items: center; }
#attach-btn:hover { border-color: var(--primary); color: var(--primary); }

#file-preview { display: flex; gap: 6px; padding: 0 20px; flex-wrap: wrap; }
.file-chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px;
  background: var(--bg); border: 1px solid var(--border); border-radius: 16px;
  font-size: 12px; color: var(--text); }
.file-chip img { width: 20px; height: 20px; object-fit: cover; border-radius: 3px; }
.file-chip .remove { cursor: pointer; color: var(--muted); font-weight: bold; margin-left: 2px; }
.file-chip .remove:hover { color: #ef4444; }

/* 드래그앤드롭 오버레이 */
#drop-overlay { display: none; position: fixed; inset: 0; background: rgba(37,99,235,0.08);
  border: 3px dashed var(--primary); z-index: 100; align-items: center;
  justify-content: center; font-size: 18px; color: var(--primary); font-weight: 600; }
#drop-overlay.active { display: flex; }
```

#### HTML 변경

```html
<!-- input-area에 첨부 버튼 추가 -->
<div id="file-preview"></div>
<div id="input-area">
  <button id="attach-btn" title="파일 첨부 (이미지/PDF/TXT)">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
    </svg>
  </button>
  <input type="file" id="file-input" multiple accept="image/*,.pdf,.txt,.md" hidden>
  <input type="text" id="msg-input" placeholder="노동법 관련 질문을 입력하세요..." autocomplete="off">
  <button id="send-btn" onclick="send()">전송</button>
</div>
<div id="drop-overlay">파일을 여기에 놓으세요</div>
```

#### JavaScript 추가

```javascript
// 첨부 파일 상태 관리
let pendingFiles = [];   // [{file: File, dataUrl: string}]
const MAX_FILES = 3;
const attachBtn = document.getElementById('attach-btn');
const fileInput = document.getElementById('file-input');
const filePreview = document.getElementById('file-preview');
const dropOverlay = document.getElementById('drop-overlay');

// 첨부 버튼 클릭 → 파일 선택
attachBtn.addEventListener('click', () => fileInput.click());

// 파일 선택 이벤트
fileInput.addEventListener('change', e => {
  addFiles(Array.from(e.target.files));
  fileInput.value = '';
});

// 드래그앤드롭
document.addEventListener('dragover', e => { e.preventDefault(); dropOverlay.classList.add('active'); });
document.addEventListener('dragleave', e => {
  if (e.relatedTarget === null) dropOverlay.classList.remove('active');
});
document.addEventListener('drop', e => {
  e.preventDefault();
  dropOverlay.classList.remove('active');
  addFiles(Array.from(e.dataTransfer.files));
});

function addFiles(files) {
  for (const f of files) {
    if (pendingFiles.length >= MAX_FILES) {
      alert('파일은 최대 3개까지 첨부할 수 있습니다.');
      break;
    }
    // 형식 검증
    const ok = f.type.startsWith('image/') ||
               f.type === 'application/pdf' ||
               f.type === 'text/plain' || f.type === 'text/markdown' ||
               f.name.endsWith('.txt') || f.name.endsWith('.md');
    if (!ok) {
      alert(`지원하지 않는 파일 형식입니다: ${f.name}\n이미지(JPG/PNG), PDF, TXT 파일만 가능합니다.`);
      continue;
    }
    // 크기 검증 (클라이언트)
    const maxMB = f.type.startsWith('image/') ? 10 : f.type === 'application/pdf' ? 20 : 1;
    if (f.size > maxMB * 1024 * 1024) {
      alert(`파일이 너무 큽니다: ${f.name} (최대 ${maxMB}MB)`);
      continue;
    }
    pendingFiles.push(f);
  }
  renderPreview();
}

function renderPreview() {
  filePreview.innerHTML = '';
  pendingFiles.forEach((f, i) => {
    const chip = document.createElement('span');
    chip.className = 'file-chip';
    // 이미지는 썸네일
    if (f.type.startsWith('image/')) {
      const img = document.createElement('img');
      img.src = URL.createObjectURL(f);
      chip.appendChild(img);
    }
    const name = document.createElement('span');
    const sizeMB = (f.size / 1024 / 1024).toFixed(1);
    name.textContent = `${f.name} (${sizeMB}MB)`;
    chip.appendChild(name);
    const rm = document.createElement('span');
    rm.className = 'remove';
    rm.textContent = 'x';
    rm.onclick = () => { pendingFiles.splice(i, 1); renderPreview(); };
    chip.appendChild(rm);
    filePreview.appendChild(chip);
  });
}

// File → base64 string
function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      // data:image/png;base64,XXXX → XXXX 부분만
      const b64 = reader.result.split(',')[1];
      resolve(b64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
```

#### `send()` 함수 수정

```javascript
async function send() {
  const text = input.value.trim();
  if (!text && pendingFiles.length === 0) return;

  // 사용자 메시지 표시 (파일 이름 포함)
  let displayHtml = text.replace(/</g, '&lt;');
  if (pendingFiles.length > 0) {
    const names = pendingFiles.map(f => f.name).join(', ');
    displayHtml += `<br><span style="font-size:12px;opacity:0.8">📎 ${names}</span>`;
  }
  addMsg('user', displayHtml);

  // 첨부파일 base64 인코딩
  const attachments = [];
  for (const f of pendingFiles) {
    attachments.push({
      filename: f.name,
      content_type: f.type || 'application/octet-stream',
      data: await fileToBase64(f),
    });
  }

  // 상태 초기화
  input.value = '';
  pendingFiles = [];
  renderPreview();
  btn.disabled = true;

  const statusEl = addMsg('status', '질문 분석 중...');
  let assistantEl = null;
  let fullText = '';

  try {
    // 첨부파일이 있으면 POST, 없으면 기존 GET
    let resp;
    if (attachments.length > 0) {
      resp = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          session_id: sessionId,
          attachments,
        }),
      });
    } else {
      const params = new URLSearchParams({ message: text });
      if (sessionId) params.set('session_id', sessionId);
      resp = await fetch('/api/chat/stream?' + params);
    }

    // ... 이하 기존 SSE 읽기 코드 동일 ...
  }
}
```

### 2.6 `requirements.txt` (수정)

추가:
```
PyPDF2>=3.0.0
python-multipart>=0.0.9
```

## 3. 데이터 흐름도 (상세)

```
Frontend
  │
  ├─ [파일 없음] GET /api/chat/stream?message=...
  │    → pipeline.process_question(query, session, config)
  │
  └─ [파일 있음] POST /api/chat/stream
       Body: { message, session_id, attachments: [{filename, content_type, data(b64)}] }
       │
       ├─ api/index.py: base64 decode → file_parser.parse_attachment()
       │    ├─ 이미지 → ParsedAttachment(vision_block={type:image, source:{...}})
       │    ├─ PDF → ParsedAttachment(extracted_text="...")
       │    └─ TXT → ParsedAttachment(extracted_text="...")
       │
       └─ pipeline.process_question(query, session, config, attachments=[...])
            │
            ├─ Step 1: 임금계산기 추출
            │    query + attachment.extracted_text 병합하여 분석
            │
            ├─ Step 2: RAG 검색
            │    query 텍스트만으로 검색 (첨부 제외)
            │
            └─ Step 3: Claude 답변 생성
                 messages 구성:
                 [
                   ...session.recent(),
                   { role: "user", content: [
                       {type: "image", source: ...},    ← 이미지 첨부
                       {type: "text", text: "참고문서+계산기+질문+첨부텍스트"}
                   ]}
                 ]
```

## 4. 에러 처리

| 에러 상황 | 처리 방식 |
|-----------|-----------|
| 지원하지 않는 파일 형식 | 클라이언트: alert + 업로드 차단. 서버: SSE error 이벤트 |
| 파일 크기 초과 | 클라이언트: alert + 업로드 차단. 서버: SSE error 이벤트 |
| PDF 페이지 초과 (>20) | 서버: FileValidationError → SSE error 이벤트 |
| PDF 텍스트 추출 실패 (스캔 이미지) | 서버: "이미지 파일로 첨부해 주세요" 안내 |
| 텍스트 인코딩 인식 불가 | 서버: FileValidationError → SSE error 이벤트 |
| base64 디코딩 실패 | 서버: 400 Bad Request |

SSE 에러 이벤트 형식:
```json
{"type": "error", "text": "PDF는 20페이지 이하만 가능합니다. (contract.pdf: 35페이지)"}
```

## 5. 구현 순서

1. `requirements.txt` — PyPDF2, python-multipart 추가
2. `app/core/file_parser.py` — 파일 파싱 모듈 (독립 모듈, 의존 없음)
3. `app/models/schemas.py` — Attachment, ChatWithFilesRequest 모델 추가
4. `app/core/pipeline.py` — attachments 파라미터 추가 + Vision 블록 통합
5. `api/index.py` — POST /api/chat/stream 엔드포인트 추가
6. `public/index.html` — 첨부 UI + 전송 로직 수정

## 6. 하위 호환성

- 기존 `GET /api/chat/stream` 엔드포인트 유지 (프론트엔드 이전 버전 호환)
- `process_question(query, session, config)` 기존 호출 — `attachments=None` 기본값으로 동작
- `ChatRequest` 기존 모델 유지
- 파일 없이 텍스트만 전송 시 기존과 동일한 동작 보장
